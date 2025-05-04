import sqlite3
import requests
from urllib.parse import urlparse
from datetime import datetime
import statistics


def resolve_final_url(input_url):
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    try:
        response = requests.get(input_url, timeout=10, allow_redirects=True)
        return response.url
    except requests.RequestException:
        return None


def initialize_url_database():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            last_checked DATETIME DEFAULT '1970-01-01 00:00:00'
        )
    ''')
    conn.commit()
    conn.close()


def insert_url():
    url_input = input("Enter a new URL: ").strip()
    normalized_url = resolve_final_url(url_input)
    if not normalized_url:
        print("Failed to resolve or reach the URL.")
        return

    try:
        response = requests.get(normalized_url, timeout=5)
        if response.status_code != 200:
            print("URL responded with status:", response.status_code)
            return
    except requests.RequestException as e:
        print("URL unreachable:", e)
        return

    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO urls (url) VALUES (?)", (normalized_url,))
        conn.commit()
        print("URL added successfully.")
    finally:
        conn.close()


def list_urls():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, url, last_checked FROM urls")
    urls = cursor.fetchall()
    conn.close()

    if not urls:
        print("No URLs found.")
        return []

    for row in urls:
        print(f"{row[0]}. {row[1]} (Last Checked: {row[2]})")
    return urls


def choose_url():
    urls = list_urls()
    if not urls:
        return None

    try:
        url_id = int(input("Enter the ID of the URL you want to analyze: "))
        ids = [row[0] for row in urls]
        if url_id not in ids:
            print("Invalid ID.")
            return None
    except ValueError:
        print("Invalid input.")
        return None

    return urls[[row[0] for row in urls].index(url_id)][1]


def show_statistics_for_url(url):
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM metrics WHERE url = ?", (url,))
    rows = cursor.fetchall()
    if not rows:
        print("No data for this URL.")
        return

    column_names = [description[0] for description in cursor.description]
    metrics_to_show = ['load_time', 'memory_usage', 'cpu_time', 'dom_nodes',
                       'total_page_size', 'fcp', 'network_requests', 'script_size']

    for i, name in enumerate(column_names):
        if name in metrics_to_show:
            values = [row[i] for row in rows if isinstance(row[i], (int, float))]
            if values:
                mean_val = statistics.mean(values)
                std_val = statistics.stdev(values) if len(values) > 1 else 0
                print(f"{name}: mean = {mean_val:.2f}, std = {std_val:.2f}")
            else:
                print(f"{name}: No valid data.")
    conn.close()


def main():
    initialize_url_database()
    while True:
        print("\n--- Dashboard Menu ---")
        print("1. Insert a new URL")
        print("2. List URLs and choose one to view stats")
        print("3. Exit")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            insert_url()
        elif choice == "2":
            url = choose_url()
            if url:
                show_statistics_for_url(url)
        elif choice == "3":
            break
        else:
            print("Invalid choice.")


if __name__ == "__main__":
    main()
