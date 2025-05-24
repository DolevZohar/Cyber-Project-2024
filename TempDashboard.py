import sqlite3
import requests
import hashlib
from urllib.parse import urlparse
from datetime import datetime
import statistics


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def resolve_final_url(input_url):
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    try:
        response = requests.get(input_url, timeout=10, allow_redirects=True)
        return response.url
    except requests.RequestException:
        return None

def initialize_databases():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            last_checked DATETIME DEFAULT '1970-01-01 00:00:00'
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_urls (
            user_id INTEGER,
            url_id INTEGER,
            url_nick TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(url_id) REFERENCES urls(id)
        )
    ''')
    conn.commit()
    conn.close()

def register_user():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    username = input("Choose a username: ").strip()
    password = input("Choose a password: ").strip()
    password_hash = hash_password(password)
    try:
        cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
        conn.commit()
        print("Registration successful.")
    except sqlite3.IntegrityError:
        print("Username already exists.")
    finally:
        conn.close()

def login_user():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    username = input("Username: ").strip()
    password = input("Password: ").strip()
    password_hash = hash_password(password)
    cursor.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", (username, password_hash))
    result = cursor.fetchone()
    conn.close()
    if result:
        print("Login successful.")
        return result[0]
    else:
        print("Invalid username or password.")
        return None

def insert_url(user_id):
    url_input = input("Enter a new URL: ").strip()
    normalized_url = resolve_final_url(url_input)
    if not normalized_url:
        print("Failed to resolve or reach the URL.")
        return

    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO urls (url) VALUES (?)", (normalized_url,))
    conn.commit()
    cursor.execute("SELECT id FROM urls WHERE url = ?", (normalized_url,))
    url_id = cursor.fetchone()[0]
    url_nick = url_input
    cursor.execute("INSERT INTO user_urls (user_id, url_id, url_nick) VALUES (?, ?, ?)", (user_id, url_id, url_nick))
    conn.commit()
    print("URL added successfully.")
    conn.close()

def list_user_urls(user_id):
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute('''
        SELECT uu.url_id, uu.url_nick, u.last_checked
        FROM user_urls uu
        JOIN urls u ON uu.url_id = u.id
        WHERE uu.user_id = ?
    ''', (user_id,))
    urls = cursor.fetchall()
    conn.close()

    if not urls:
        print("No URLs found.")
        return []

    for row in urls:
        print(f"{row[0]}. {row[1]} (Last Checked: {row[2]})")
    return urls

def choose_url(user_id):
    urls = list_user_urls(user_id)
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

    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urls WHERE id = ?", (url_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

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

def user_dashboard(user_id):
    while True:
        print("\n--- Dashboard Menu ---")
        print("1. Insert a new URL")
        print("2. List URLs and choose one to view stats")
        print("3. Log out")

        choice = input("Choose an option: ").strip()

        if choice == "1":
            insert_url(user_id)
        elif choice == "2":
            url = choose_url(user_id)
            if url:
                show_statistics_for_url(url)
        elif choice == "3":
            print("Logging out...")
            break
        else:
            print("Invalid choice.")

def main():
    initialize_databases()
    while True:
        print("\n--- Welcome ---")
        print("1. Login")
        print("2. Register")
        print("3. Exit")
        action = input("Choose an action: ").strip()

        if action == "1":
            user_id = login_user()
            if user_id:
                user_dashboard(user_id)
        elif action == "2":
            register_user()
        elif action == "3":
            print("Goodbye.")
            break
        else:
            print("Invalid option.")

if __name__ == "__main__":
    main()