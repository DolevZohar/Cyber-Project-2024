import socket
import json
import pickle
from Metrics import Metrics
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options


SERVER_HOST = '127.0.0.1'  # Server's IP address
SERVER_PORT = 65432        # Server's port



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
    memory_usage = next((item["value"] for item in metrics["metrics"] if item["name"] == "JSHeapUsedSize"), 0) / (
            1024 * 1024)
    cpu_time = next((item["value"] for item in metrics["metrics"] if item["name"] == "TaskDuration"), 0)
    return {
        "url": url,
        "load_time": load_time,
        "memory_usage": memory_usage,
        "cpu_time": cpu_time,
    }


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client_socket:
        client_socket.connect((SERVER_HOST, SERVER_PORT))
        print("Connected to the server.")

        while True:
            # Receive URL from the server
            url = client_socket.recv(1024).decode()
            if url == 'exit':
                print("Exiting client.")
                break

            print(f"Received URL to test: {url}")

            # Perform tests
            driver = setup_browser()
            for i in range(5):  # Perform 5 tests
                stats = track_statistics(url, driver)
                message = json.dumps(stats) + "\n"  # Add a newline delimiter
                client_socket.sendall(message.encode())
                print(
                    f"Run {i + 1} - Load Time: {stats['load_time']:.2f}s, Memory: {stats['memory_usage']:.2f}MB, CPU Time: {stats['cpu_time']:.2f}s"
                )
            driver.quit()

            # Send a "DONE" signal to indicate completion
            client_socket.sendall(b"DONE\n")
            print("All metrics sent to the server.")


if __name__ == "__main__":
    main()
