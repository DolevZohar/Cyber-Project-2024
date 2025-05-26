from Metrics import Metrics
import requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException
import psutil
import time
import json

BROWSER_IDS = {"chrome": 1, "edge": 2, "opera": 3}


def setup_browser(browser_name="chrome"):
    import os
    import shutil
    import platform
    from selenium import webdriver

    browser_name = browser_name.lower()

    if browser_name == "chrome":
        from selenium.webdriver.chrome.service import Service as ChromeService
        from selenium.webdriver.chrome.options import Options

        options = Options()
        try:
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        except Exception:
            pass  # Continue without logging if unsupported

        service = ChromeService()
        driver = webdriver.Chrome(service=service, options=options)

    elif browser_name == "edge":
        from selenium.webdriver.edge.options import Options as EdgeOptions
        from selenium.webdriver.edge.service import Service as EdgeService

        options = EdgeOptions()
        try:
            options.set_capability("ms:loggingPrefs", {"performance": "ALL"})
        except Exception:
            pass

        service = EdgeService()
        driver = webdriver.Edge(service=service, options=options)


    elif browser_name == "opera":
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.chrome.service import Service as ChromeService
        def get_opera_path():
            possible_paths = [
                r"C:\Users\User\AppData\Local\Programs\Opera\opera.exe",
            ]
            for path in possible_paths:
                if os.path.isfile(path):
                    return path
            return shutil.which("opera")
        opera_binary = get_opera_path()
        if not opera_binary:
            raise FileNotFoundError("Opera browser not found.")
        chromedriver_path = os.getenv("CHROMEDRIVER_PATH", r"C:\Webdrivers\chromedriver-win64\chromedriver.exe")
        if not os.path.isfile(chromedriver_path):
            raise FileNotFoundError(f"ChromeDriver not found at {chromedriver_path}")
        options = ChromeOptions()
        options.binary_location = opera_binary
        # Optional: use a temporary user-data-dir to avoid blank data:; screen
        temp_profile_dir = os.path.abspath("temp_opera_profile")
        os.makedirs(temp_profile_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={temp_profile_dir}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--start-maximized")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        try:
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        except Exception:
            pass
        service = ChromeService(executable_path=chromedriver_path)
        driver = webdriver.Chrome(service=service, options=options)

    else:
        raise ValueError(f"Unsupported browser: {browser_name}")

    return driver


def safe_metric(name, func, metrics_dict, failed_list):
    try:
        metrics_dict[name] = func()
    except Exception as e:
        print(f"[x] Failed to collect '{name}': {e}")
        failed_list.append(name)
        metrics_dict[name] = None


def track_statistics(url, driver, session, browser_name):

    browser_id = BROWSER_IDS.get(browser_name, 0)

    is_up = 1
    try:
        driver.get(url)
    except Exception as e:
        print(f"Failed to access {url}: {e}")
        is_up = 0

    # Normalize browser names
    if browser_name == "microsoftedge":
        browser_name = "edge"

    driver.execute_cdp_cmd("Performance.disable", {})
    driver.execute_cdp_cmd("Performance.setTimeDomain", {"timeDomain": "threadTicks"})
    driver.execute_cdp_cmd("Performance.enable", {})
    driver.execute_cdp_cmd("Network.enable", {})

    if browser_name in ['chrome', 'edge', 'opera']:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    window.fcpTime = null;
                    try {
                        const observer = new PerformanceObserver((list) => {
                            for (const entry of list.getEntries()) {
                                if (entry.name === 'first-contentful-paint') {
                                    window.fcpTime = entry.startTime;
                                    observer.disconnect();
                                }
                            }
                        });
                        observer.observe({ type: 'paint', buffered: true });
                    } catch (e) {
                        console.warn("PerformanceObserver failed", e);
                    }
                """
            }
        )

    driver.get(url)

    metrics_data = {}
    failed_metrics = []


    def get_load_time():
        timing = driver.execute_script("return window.performance.timing.toJSON()")
        return (timing["loadEventEnd"] - timing["navigationStart"]) / 1000

    def get_performance_metrics():
        return driver.execute_cdp_cmd("Performance.getMetrics", {})

    def get_memory_usage():
        if browser_name in ("firefox", "opera"):
            try:
                parent_pid = driver.service.process.pid
                parent = psutil.Process(parent_pid)
                children = parent.children(recursive=True)
                processes = [parent] + children
                total_rss = sum(p.memory_info().rss for p in processes if p.is_running())
                return total_rss / (1024 * 1024)
            except Exception as e:
                print(f"Memory check failed for {browser_name}: {e}")
                return 0.0
        else:
            try:
                metrics = get_performance_metrics()
                return next((m["value"] for m in metrics["metrics"] if m["name"] == "JSHeapUsedSize"), 0) / (1024 * 1024)
            except Exception as e:
                print(f"CDP memory check failed: {e}")
                return 0.0

    def get_cpu_time():
        if browser_name == 'firefox':
            try:
                browser_pid = driver.service.process.pid
                proc = psutil.Process(browser_pid)
                children = proc.children(recursive=True)
                all_procs = [proc] + children
                return sum((p.cpu_times().user + p.cpu_times().system) for p in all_procs if p.is_running())
            except Exception as e:
                print(f"[x] Failed to collect CPU time via psutil: {e}")
                return None
        else:
            try:
                metrics = get_performance_metrics()
                return next((m["value"] for m in metrics["metrics"] if m["name"] == "TaskDuration"), 0)
            except Exception as e:
                print(f"[x] Failed to collect CPU time via CDP: {e}")
                return None

    def get_dom_nodes():
        return driver.execute_script("return document.getElementsByTagName('*').length")

    def get_total_page_size():
        try:
            if browser_name in ("chrome", "edge", "opera"):
                logs = driver.get_log("performance")
                total_size = sum(
                    json.loads(e["message"])["message"]["params"].get("encodedDataLength", 0)
                    for e in logs
                    if json.loads(e["message"])["message"].get("method") == "Network.loadingFinished"
                )
                return total_size / (1024 * 1024)
            elif browser_name == "firefox":
                resources = driver.execute_script("return performance.getEntriesByType('resource');")
                total_size = sum(res.get('transferSize', 0) for res in resources)
                return total_size / (1024 * 1024)
            else:
                print(f"Unsupported browser for page size: {browser_name}")
                return None
        except Exception as e:
            print(f"Failed to get page size for {browser_name}: {e}")
            return None

    def get_fcp():
        if browser_name == 'opera':
            return None
        for _ in range(20):
            try:
                result = driver.execute_script("return window.fcpTime;")
                if result is not None:
                    return result / 1000
            except Exception:
                pass  # optional: log if needed

            time.sleep(0.1)

        try:
            fcp_entry = driver.execute_script("""
            const paints = performance.getEntriesByType('paint');
            for (let entry of paints) {
                if (entry.name === 'first-contentful-paint') return entry.startTime;
            }
            return null;
            """)
            if fcp_entry is not None:
                return fcp_entry / 1000
        except Exception as e:
            print(f"[FCP fallback] Failed: {e}")

        return None

    def get_network_request_count():
        if browser_name == "firefox":
            try:
                resources = driver.execute_script("return performance.getEntriesByType('resource');")
                return len(resources)
            except Exception as e:
                print(f"[x] Failed to get network requests in Firefox: {e}")
                return None
        try:
            logs = driver.get_log("performance")
            return sum(
                1 for e in logs
                if json.loads(e["message"])["message"].get("method") == "Network.responseReceived"
            )
        except Exception as e:
            print(f"[x] Failed to collect 'network_requests': {e}")
            return None

    def get_total_script_size():
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
                continue
        total_script_bytes += inline_script_bytes
        return total_script_bytes / (1024 * 1024)

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

    # Run metrics
    if (is_up):
        safe_metric("load_time", get_load_time, metrics_data, failed_metrics)
        safe_metric("memory_usage", get_memory_usage, metrics_data, failed_metrics)
        safe_metric("cpu_time", get_cpu_time, metrics_data, failed_metrics)
        safe_metric("dom_nodes", get_dom_nodes, metrics_data, failed_metrics)
        safe_metric("total_page_size", get_total_page_size, metrics_data, failed_metrics)
        time.sleep(3)
        safe_metric("fcp", get_fcp, metrics_data, failed_metrics)
        safe_metric("network_requests", get_network_request_count, metrics_data, failed_metrics)
        safe_metric("script_size", get_total_script_size, metrics_data, failed_metrics)
        safe_metric("broken_links", get_broken_links, metrics_data, failed_metrics)

    metrics_data["failed_metrics"] = failed_metrics
    metrics_data["browser_id"] = browser_id
    metrics_data["is_up"] = is_up
    return Metrics(url, **metrics_data)

def worker_process(url, browser_name, session_headers):
    session = requests.Session()
    session.headers.update(session_headers)
    results = []

    for i in range(2):  # Run twice
        driver = setup_browser(browser_name)
        try:
            metric = track_statistics(url, driver, session, browser_name)
            results.append(metric)  # Send Metrics object, not dict
            print(f"[{browser_name.upper()} Run {i + 1}] Done")
        finally:
            driver.quit()

    return results

def browser_loop(browser_name, url_queue, result_queue, session_headers):
    while True:
        url = url_queue.get()
        if url == "exit":
            print(f"[{browser_name}] Exiting")
            break

        results = worker_process(url, browser_name, session_headers)
        result_queue.put(results)
