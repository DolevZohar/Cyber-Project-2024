import socket
import sqlite3
import requests
from Metrics import Metrics
from networkutils import send_pickle, recv_pickle

HOST = '127.0.0.1'
PORT = 65432

def initialize_database():
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            load_time REAL,
            memory_usage REAL,
            cpu_time REAL,
            dom_nodes INTEGER,
            total_page_size REAL,
            fcp REAL,
            network_requests INTEGER,
            script_size REAL,
            broken_links TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def insert_metrics(metrics):
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (
            url, load_time, memory_usage, cpu_time, dom_nodes,
            total_page_size, fcp, network_requests, script_size, broken_links
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        metrics.url,
        getattr(metrics, 'load_time', None),
        getattr(metrics, 'memory_usage', None),
        getattr(metrics, 'cpu_time', None),
        getattr(metrics, 'dom_nodes', None),
        getattr(metrics, 'total_page_size', None),
        getattr(metrics, 'fcp', None),
        getattr(metrics, 'network_requests', None),
        getattr(metrics, 'script_size', None),
        ', '.join(metrics.broken_links) if metrics.broken_links else None
    ))
    conn.commit()
    conn.close()


# A function to follow redirections
def resolve_final_url(input_url):
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    try:
        response = requests.get(input_url, timeout=10, allow_redirects=True)
        return response.url
    except requests.RequestException as e:
        print(f"Failed to resolve URL: {e}")
        return None

def start_server():
    initialize_database()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        print(f"Server started. Listening on {HOST}:{PORT}")

        while True:
            print("Waiting for a client to connect...")
            conn, addr = server_socket.accept()
            print(f"Connected by {addr}")
            with conn:
                while True:
                    url = input("Enter the URL to test (or type 'exit' to quit): ").strip()
                    if url.lower() == "exit":
                        print("Shutting down the server.")
                        send_pickle(conn, "exit")
                        return

                    normalized_url = resolve_final_url(url)
                    if not normalized_url:
                        print("Invalid or unreachable URL. Try again.")
                        continue

                    send_pickle(conn, normalized_url)

                    while True:
                        metrics = recv_pickle(conn)
                        if metrics is None:
                            print("Client disconnected.")
                            return

                        if isinstance(metrics, str) and metrics == "DONE":
                            print("All metrics received for the URL.")
                            break

                        if isinstance(metrics, Metrics):
                            print(f"--- Metrics Received ---\n"
                                  f"URL: {metrics.url}\n"
                                  f"Load Time: {getattr(metrics, 'load_time', 'N/A'):.2f}s\n"
                                  f"FCP: {getattr(metrics, 'fcp', 'N/A'):.2f}s\n"
                                  f"Memory Usage: {getattr(metrics, 'memory_usage', 'N/A'):.2f}MB\n"
                                  f"CPU Time: {getattr(metrics, 'cpu_time', 'N/A'):.2f}s\n"
                                  f"DOM Nodes: {getattr(metrics, 'dom_nodes', 'N/A')}\n"
                                  f"Total Page Size: {getattr(metrics, 'total_page_size', 'N/A'):.2f}MB\n"
                                  f"Script Size: {getattr(metrics, 'script_size', 'N/A'):.2f}MB\n"
                                  f"Network Requests: {getattr(metrics, 'network_requests', 'N/A')}\n"
                                  f"Broken Links: {len(getattr(metrics, 'broken_links', []))}\n")

                            insert_metrics(metrics)
                            print("Metrics inserted into the database.")


if __name__ == "__main__":
    start_server()