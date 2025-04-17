import socket
import json
from Metrics import Metrics
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from networkutils import send_pickle, recv_pickle  # Import the shared functions
import requests
from urllib.parse import urljoin

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65432

def setup_browser():
        chrome_options = Options()
        chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        service = Service()
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver

def safe_metric(name, func, metrics_dict, failed_list):
    try:
        metrics_dict[name] = func()
    except Exception as e:
        print(f"[x] Failed to collect '{name}': {e}")
        failed_list.append(name)


def track_statistics(url, driver):
    driver.execute_cdp_cmd("Performance.disable", {})
    driver.execute_cdp_cmd("Performance.setTimeDomain", {"timeDomain": "threadTicks"})
    driver.execute_cdp_cmd("Performance.enable", {})

    driver.get(url)

    metrics_data = {}
    failed_metrics = []

    def get_load_time():
        timing = driver.execute_script("return window.performance.timing.toJSON()")
        return (timing["loadEventEnd"] - timing["navigationStart"]) / 1000

    def get_performance_metrics():
        return driver.execute_cdp_cmd("Performance.getMetrics", {})

    def get_memory_usage():
        metrics = get_performance_metrics()
        return next((m["value"] for m in metrics["metrics"] if m["name"] == "JSHeapUsedSize"), 0) / (1024 * 1024)

    def get_cpu_time():
        metrics = get_performance_metrics()
        return next((m["value"] for m in metrics["metrics"] if m["name"] == "TaskDuration"), 0)

    def get_dom_nodes():
        return driver.execute_script("return document.getElementsByTagName('*').length")

    def get_total_page_size():
        logs = driver.get_log("performance")
        return sum(
            json.loads(e["message"])["message"]["params"].get("encodedDataLength", 0)
            for e in logs
            if json.loads(e["message"])["message"].get("method") == "Network.loadingFinished"
        ) / (1024 * 1024)

    def get_fcp():
        entry = driver.execute_script("return performance.getEntriesByName('first-contentful-paint')[0];")
        return entry['startTime'] / 1000 if entry else None

    def get_network_request_count():
        logs = driver.get_log("performance")
        return sum(
            1 for e in logs
            if json.loads(e["message"])["message"].get("method") == "Network.responseReceived"
        )

    def get_total_script_size():
        logs = driver.get_log("performance")
        total_bytes = 0
        for entry in logs:
            log = json.loads(entry["message"])["message"]
            if log["method"] == "Network.loadingFinished":
                request_id = log["params"]["requestId"]
                match = next((e for e in logs if json.loads(e["message"])["message"]
                              .get("params", {}).get("requestId") == request_id and
                              json.loads(e["message"])["message"].get("method") == "Network.responseReceived"), None)
                if match:
                    type_ = json.loads(match["message"])["message"]["params"]["type"]
                    if type_ == "Script":
                        total_bytes += log["params"].get("encodedDataLength", 0)
        return total_bytes / (1024 * 1024)

    def get_broken_links():
        links = driver.find_elements("tag name", "a")
        broken = []
        for link in links:
            href = link.get_attribute("href")
            if href:
                full_url = urljoin(driver.current_url, href)
                try:
                    response = requests.head(full_url, allow_redirects=True, timeout=5)
                    if response.status_code >= 400:
                        broken.append(full_url)
                except requests.RequestException:
                    broken.append(full_url)
        return broken

    # Add all metric collectors here
    safe_metric("load_time", get_load_time, metrics_data, failed_metrics)
    safe_metric("memory_usage", get_memory_usage, metrics_data, failed_metrics)
    safe_metric("cpu_time", get_cpu_time, metrics_data, failed_metrics)
    safe_metric("dom_nodes", get_dom_nodes, metrics_data, failed_metrics)
    safe_metric("total_page_size", get_total_page_size, metrics_data, failed_metrics)
    safe_metric("fcp", get_fcp, metrics_data, failed_metrics)
    safe_metric("network_requests", get_network_request_count, metrics_data, failed_metrics)
    safe_metric("script_size", get_total_script_size, metrics_data, failed_metrics)
    safe_metric("broken_links", get_broken_links, metrics_data, failed_metrics)

    driver.execute_cdp_cmd("Performance.disable", {})
    metrics_data["failed_metrics"] = failed_metrics
    return Metrics(url, **metrics_data)




def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((SERVER_HOST, SERVER_PORT))
        print("Connected to the server.")

        while True:
            url = recv_pickle(client_socket)

            if url == "exit":
                print("Exiting client.")
                break

            print(f"Received URL to test: {url}")

            for i in range(5):
                driver = setup_browser()
                try:
                    metrics_obj = track_statistics(url, driver)
                    send_pickle(client_socket, metrics_obj)

                    print(f"Run {i + 1} - "
                          f"Load Time: {getattr(metrics_obj, 'load_time', 'N/A'):.2f}s, "
                          f"FCP: {getattr(metrics_obj, 'fcp', 'N/A'):.2f}s, "
                          f"Memory: {getattr(metrics_obj, 'memory_usage', 'N/A'):.2f}MB, "
                          f"CPU Time: {getattr(metrics_obj, 'cpu_time', 'N/A'):.2f}s, "
                          f"DOM Nodes: {getattr(metrics_obj, 'dom_nodes', 'N/A')}, "
                          f"Page Size: {getattr(metrics_obj, 'total_page_size', 'N/A'):.2f}MB, "
                          f"Script Size: {getattr(metrics_obj, 'script_size', 'N/A'):.2f}MB, "
                          f"Requests: {getattr(metrics_obj, 'network_requests', 'N/A')}, "
                          f"Broken Links: {len(getattr(metrics_obj, 'broken_links', []))}")
                finally:
                    driver.quit()

            send_pickle(client_socket, "DONE")
            print("All metrics sent to the server.")


if __name__ == "__main__":
    main()
