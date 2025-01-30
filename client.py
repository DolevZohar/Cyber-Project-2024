import socket
from Metrics import Metrics
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from networkutils import send_pickle, recv_pickle  # Import the shared functions

SERVER_HOST = '127.0.0.1'
SERVER_PORT = 65432

def setup_browser():
    chrome_options = Options()
    chrome_options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    service = Service()
    driver = webdriver.Chrome(service=service, options=chrome_options)
    return driver

def track_statistics(url, driver):
    driver.execute_cdp_cmd("Performance.enable", {})
    driver.get(url)
    timing = driver.execute_script("return window.performance.timing.toJSON()")
    load_time = (timing["loadEventEnd"] - timing["navigationStart"]) / 1000
    metrics = driver.execute_cdp_cmd("Performance.getMetrics", {})
    driver.execute_cdp_cmd("Performance.disable", {})

    memory_usage = next((item["value"] for item in metrics["metrics"] if item["name"] == "JSHeapUsedSize"), 0) / (1024 * 1024)
    cpu_time = next((item["value"] for item in metrics["metrics"] if item["name"] == "TaskDuration"), 0)

    return Metrics(url, load_time, memory_usage, cpu_time)

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

            driver = setup_browser()
            for i in range(5):  # Perform 5 tests
                metrics_obj = track_statistics(url, driver)
                send_pickle(client_socket, metrics_obj)  # Send pickled Metrics object
                print(f"Run {i + 1} - Load Time: {metrics_obj.load_time:.2f}s, "
                      f"Memory: {metrics_obj.memory_usage:.2f}MB, CPU Time: {metrics_obj.cpu_time:.2f}s")

            driver.quit()

            send_pickle(client_socket, "DONE")  # Send "DONE" as a pickled object
            print("All metrics sent to the server.")

if __name__ == "__main__":
    main()
