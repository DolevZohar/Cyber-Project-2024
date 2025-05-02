import socket
import json
from Metrics import Metrics
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from networkutils import send_pickle, recv_pickle
import requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException

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
        metrics_dict[name] = None

def track_statistics(url, driver, session):
    driver.execute_cdp_cmd("Performance.disable", {})
    driver.execute_cdp_cmd("Performance.setTimeDomain", {"timeDomain": "threadTicks"})
    driver.execute_cdp_cmd("Performance.enable", {})
    driver.execute_cdp_cmd('Network.enable', {})

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
        # Wait for script elements to be present in the DOM
        WebDriverWait(driver, 10).until(EC.presence_of_all_elements_located((By.TAG_NAME, "script")))
        scripts = driver.find_elements("tag name", "script")
        total_script_bytes = 0
        inline_script_bytes = 0

        for script in scripts:
            try:
                src = script.get_attribute("src")
                if src:
                    try:
                        response = requests.get(src, timeout=5)
                        total_script_bytes += len(response.content)
                    except requests.RequestException:
                        continue
                else:
                    inner = driver.execute_script("return arguments[0].innerText;", script)
                    inline_script_bytes += len(inner or "")
            except StaleElementReferenceException:
                continue  # Skip this script tag if it became stale

        total_script_bytes += inline_script_bytes
        return total_script_bytes / (1024 * 1024)  # Return size in MB

    def get_broken_links():
        links = driver.find_elements("tag name", "a")
        hrefs = [link.get_attribute("href") for link in links if link.get_attribute("href")]
        full_urls = [urljoin(driver.current_url, href) for href in hrefs]
        broken = []

        def check_link(url):
            try:
                response = session.head(url, allow_redirects=True, timeout=5)
                if response.status_code >= 400:
                    return url
            except requests.RequestException:
                return url
            return None

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_url = {executor.submit(check_link, url): url for url in full_urls}
            for future in as_completed(future_to_url):
                result = future.result()
                if result:
                    broken.append(result)

        return broken

    # Run all metrics
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

        session = requests.Session()

        while True:
            url = recv_pickle(client_socket)

            if url == "exit":
                print("Exiting client.")
                break

            print(f"Received URL to test: {url}")

            for i in range(5):
                driver = setup_browser()
                try:
                    metrics_obj = track_statistics(url, driver, session)
                    send_pickle(client_socket, metrics_obj)

                    print(f"Run {i + 1} - "
                          f"Load Time: {metrics_obj.load_time:.2f}s, "
                          f"FCP: {metrics_obj.fcp:.2f}s, "
                          f"Memory: {metrics_obj.memory_usage:.2f}MB, "
                          f"CPU Time: {metrics_obj.cpu_time:.2f}s, "
                          f"DOM Nodes: {metrics_obj.dom_nodes}, "
                          f"Page Size: {metrics_obj.total_page_size:.2f}MB, "
                          f"Script Size: {metrics_obj.script_size:.2f}MB, "
                          f"Requests: {metrics_obj.network_requests}, "
                          f"Broken Links: {len(metrics_obj.broken_links)}")
                finally:
                    driver.quit()

            send_pickle(client_socket, "DONE")
            print("All metrics sent to the server.")

if __name__ == "__main__":
    main()
