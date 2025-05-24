import socket
import sqlite3
import requests
import threading
from Metrics import Metrics
from datetime import datetime
from networkutils import DynamicClientSocket, HandshakeSocket

HOST = '127.0.0.1'
PERMANENT_PORT = 65431
shutdown_event = threading.Event()
clients_threads = []

def initialize_databases():
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

def insert_metrics(metrics):
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (
            url, load_time, memory_usage, cpu_time, dom_nodes,
            total_page_size, fcp, network_requests, script_size, broken_links
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

def get_oldest_url():
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("SELECT url FROM urls ORDER BY last_checked ASC LIMIT 1")
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def update_last_checked(url):
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE urls SET last_checked = CURRENT_TIMESTAMP WHERE url = ?", (url,))
    conn.commit()
    conn.close()

def resolve_final_url(input_url):
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    try:
        response = requests.get(input_url, timeout=10, allow_redirects=True)
        return response.url
    except requests.RequestException as e:
        print(f"Failed to resolve URL: {e}")
        return None

def handle_client(conn, addr, dynamic_port):
    client_socket = DynamicClientSocket(conn)
    print(f"Sent dynamic port {dynamic_port} to client {addr}")
    try:
        while not shutdown_event.is_set():
            url = get_oldest_url()
            if not url:
                print("No URLs in database. Add some via the dashboard.")
                client_socket.send("exit")
                break

            normalized_url = resolve_final_url(url)
            if not normalized_url:
                print("Invalid or unreachable URL.")
                client_socket.send("exit")
                break

            client_socket.send(normalized_url)
            all_metrics = []

            while True:
                obj = client_socket.receive()
                if obj == "DONE":
                    print("Received 'DONE' from client.")
                    break
                if obj is None:
                    print("Received None object.")
                    return
                elif not hasattr(obj, 'url'):
                    print(f"Invalid object received: {type(obj)} - {obj}")
                    return
                all_metrics.append(obj)

            for metrics in all_metrics:
                insert_metrics(metrics)

            print(f"Inserted metrics for {url}. Waiting for 'DONE' signal...")
            done_signal = client_socket.receive()
            if done_signal == "DONE":
                print("Received 'DONE' from client.")
                update_last_checked(normalized_url)
                print(f"Updated last checked for {normalized_url}")
    finally:
        conn.close()
        print(f"[Thread Exit] Client thread for {addr} exiting.")

def console_listener():
    while not shutdown_event.is_set():
        command = input()
        if command.strip().lower() in ("exit", "shutdown"):
            print("Shutdown command received.")
            shutdown_event.set()
    print("[Thread Exit] Console listener thread exiting.")

def accept_dynamic_client(dynamic_socket, dynamic_port):
    try:
        conn, addr = dynamic_socket.accept()
        print(f"[+] Client connected on dynamic port {dynamic_port} from {addr}")
        handle_client(conn, addr, dynamic_port)
    except Exception as e:
        print(f"[!] Error accepting client on port {dynamic_port}: {e}")
    finally:
        dynamic_socket.close()
        print(f"[Thread Exit] accept_dynamic_client thread for port {dynamic_port} exiting.")

def start_server():
    initialize_databases()
    console_thread = threading.Thread(target=console_listener)
    console_thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handshake_socket:
        handshake_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        handshake_socket.bind((HOST, PERMANENT_PORT))
        handshake_socket.listen()
        handshake_socket.settimeout(1.0)  # 🔧 Add timeout to allow loop break

        print(f"Server started. Handshake listener on {HOST}:{PERMANENT_PORT}")

        try:
            while not shutdown_event.is_set():
                try:
                    handshake_conn, handshake_addr = handshake_socket.accept()
                except socket.timeout:
                    continue  # Retry until shutdown_event is set

                if shutdown_event.is_set():
                    handshake_conn.close()
                    break

                print(f"[+] Handshake from {handshake_addr}")
                handshake = HandshakeSocket(handshake_conn)

                dynamic_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dynamic_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                dynamic_socket.bind((HOST, 0))
                dynamic_port = dynamic_socket.getsockname()[1]
                dynamic_socket.listen()

                handshake.send(dynamic_port)
                handshake.close()

                client_thread = threading.Thread(
                    target=accept_dynamic_client,
                    args=(dynamic_socket, dynamic_port)
                )
                client_thread.start()
                clients_threads.append(client_thread)

        except Exception as e:
            print(f"[!] Handshake loop error: {e}")

        print("Waiting for all client threads to finish...")
        for i, thread in enumerate(clients_threads):
            print(f"Waiting on client thread #{i}")
            thread.join()
            print(f"Client thread #{i} joined.")

        print("All client threads finished.")
        console_thread.join()
        print("Console thread finished.")
        print("Server shut down cleanly.")

if __name__ == "__main__":
    start_server()
