from multiprocessing import Process, Queue
from networkutils import HandshakeSocket, DynamicClientSocket
import requests
from client_browsers import browser_loop
import psutil
import os
import sys
import psycopg2
from config import get_db_conn, HANDSHAKE_PORT

SERVER_HOST = os.getenv("SERVER_IP")
PERMANENT_PORT = HANDSHAKE_PORT
BROWSERS = ["chrome", "edge", "opera"]

LOCK_FILE = ".client.lock"

def is_another_client_running():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                pid = int(f.read().strip())
            if psutil.pid_exists(pid):
                print(f"[ERROR] Another client is already running (PID {pid}). Exiting.")
                return True
        except Exception as e:
            print(f"[WARN] Could not validate lock file: {e}")
    return False

def write_lock_file():
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))

def remove_lock_file():
    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except Exception as e:
        print(f"[WARN] Could not delete lock file: {e}")

def connect_to_server():
    handshake = HandshakeSocket.create(SERVER_HOST, PERMANENT_PORT)
    dynamic_port = handshake.receive()
    handshake.close()
    return DynamicClientSocket.connect_to_dynamic(SERVER_HOST, dynamic_port)

def main():
    if is_another_client_running():
        sys.exit(1)

    write_lock_file()

    conn = get_db_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT group_id FROM node_role WHERE role = 'client' AND active = 1")
    group_row = cursor.fetchone()
    group_id = group_row[0] if group_row else None
    conn.close()

    client_socket = connect_to_server()
    session = requests.Session()

    url_queue = Queue()
    result_queue = Queue()

    processes = [
        Process(target=browser_loop, args=(browser, url_queue, result_queue, dict(session.headers)))
        for browser in BROWSERS
    ]
    for p in processes:
        p.start()

    try:
        while True:
            url = client_socket.receive_url()

            if url is None or url == "exit":
                print("Received shutdown signal or no URL to process.")
                for _ in BROWSERS:
                    url_queue.put("exit")
                break

            print(f"Received URL: {url}")
            for _ in BROWSERS:
                url_queue.put(url)

            flattened_metrics = []
            for _ in BROWSERS:
                browser_results = result_queue.get()
                flattened_metrics.extend(browser_results)

            for m in flattened_metrics:
                m.group_id = group_id

            client_socket.send_metrics(flattened_metrics)
            client_socket.send_done()
            print("Sent all metrics to server.")

    finally:
        client_socket.close()
        for p in processes:
            p.join()

        remove_lock_file()
        print("Client shutdown complete.")

if __name__ == "__main__":
    main()
