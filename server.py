import os
import socket
import psycopg2
import requests
import threading
from Metrics import Metrics
from datetime import datetime
from networkutils import DynamicClientSocket, HandshakeSocket
from config import get_db_conn, HANDSHAKE_PORT
from dotenv import load_dotenv


load_dotenv()
HOST = os.getenv('SERVER_IP')
PERMANENT_PORT = HANDSHAKE_PORT
shutdown_event = threading.Event()
clients_threads = []


def initialize_databases():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id SERIAL PRIMARY KEY,
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
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            browser_id INTEGER,
            is_up INTEGER,
            group_id INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id SERIAL PRIMARY KEY,
            url TEXT UNIQUE,
            last_checked TIMESTAMP DEFAULT '1970-01-01 00:00:00',
            referenced INTEGER DEFAULT 0,
            forceInactive INTEGER DEFAULT 0
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS node_role (
            role TEXT CHECK(role IN ('client', 'server')) NOT NULL,
            active INTEGER DEFAULT 1 CHECK (active IN (0,1))
        );
    ''')
    conn.commit()
    conn.close()


def validate_server_role():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM node_role WHERE role = 'server' AND active = 1")
    count = cursor.fetchone()[0]
    conn.close()
    if count > 1:
        print("[ERROR] Multiple active servers detected.")
        exit(1)


def insert_metrics(metrics):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (
            url, load_time, memory_usage, cpu_time, dom_nodes,
            total_page_size, fcp, network_requests, script_size,
            broken_links, timestamp, browser_id, is_up, group_id
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
        ', '.join(metrics.broken_links) if getattr(metrics, 'broken_links', None) else None,
        getattr(metrics, 'timestamp', datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        getattr(metrics, 'browser_id', None),
        getattr(metrics, 'is_up', None),
        getattr(metrics, 'group_id', None)
    ))
    conn.commit()
    conn.close()


def get_oldest_url():
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT url FROM urls
        WHERE referenced > 0 AND forceInactive = 0
        ORDER BY last_checked ASC LIMIT 1
    """)
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def update_last_checked(url):
    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE urls SET last_checked = CURRENT_TIMESTAMP WHERE url = %s", (url,))
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

            client_socket.send(url)

            all_metrics = []

            while True:
                obj = client_socket.receive()
                if obj == "DONE":
                    print("Received 'DONE' from client.")
                    break
                if obj is None:
                    print("Received None object.")
                    return
                if isinstance(obj, list):
                    for m in obj:
                        if isinstance(m, dict):
                            m = Metrics.from_dict(m)
                        if not hasattr(m, 'url'):
                            print(f"Invalid object in list: {type(m)} - {m}")
                            continue
                        all_metrics.append(m)
                elif hasattr(obj, 'url'):
                    all_metrics.append(obj)
                else:
                    print(f"Invalid object received: {type(obj)} - {obj}")
                    return

            for metrics in all_metrics:
                insert_metrics(metrics)

            print(f"Inserted metrics for {url}. Waiting for 'DONE' signal...")
            update_last_checked(url)
            print(f"Updated last checked for {url}")
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
    validate_server_role()
    console_thread = threading.Thread(target=console_listener)
    console_thread.start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handshake_socket:
        handshake_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        handshake_socket.bind((HOST, PERMANENT_PORT))
        handshake_socket.listen()
        handshake_socket.settimeout(1.0)

        print(f"Server started. Handshake listener on {HOST}:{PERMANENT_PORT}")

        try:
            while not shutdown_event.is_set():
                try:
                    handshake_conn, handshake_addr = handshake_socket.accept()
                except socket.timeout:
                    continue

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
