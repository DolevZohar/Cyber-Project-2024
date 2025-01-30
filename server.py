import socket
import sqlite3
from Metrics import Metrics
from networkutils import send_pickle, recv_pickle  # Import the shared functions

HOST = '127.0.0.1'
PORT = 65432

def initialize_database():
    """Creates the SQLite database and metrics table if they don't exist."""
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            load_time REAL,
            memory_usage REAL,
            cpu_time REAL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

def insert_metrics(metrics):
    """Inserts received metrics into the SQLite database."""
    conn = sqlite3.connect("metrics.db")
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO metrics (url, load_time, memory_usage, cpu_time)
        VALUES (?, ?, ?, ?)
    ''', (metrics.url, metrics.load_time, metrics.memory_usage, metrics.cpu_time))
    conn.commit()
    conn.close()

def start_server():
    """Starts the server, listens for connections, and processes client requests."""
    initialize_database()  # Ensure the database is set up

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
                        send_pickle(conn, "exit")  # Notify client to exit
                        return  # Exit the server

                    send_pickle(conn, url)  # Send the URL to the client

                    while True:
                        metrics = recv_pickle(conn)  # Receive pickled Metrics object
                        if metrics is None:
                            print("Client disconnected.")
                            return

                        if isinstance(metrics, str) and metrics == "DONE":
                            print("All metrics received for the URL.")
                            break

                        if isinstance(metrics, Metrics):
                            print(f"Received Metrics Object: URL={metrics.url}, Load Time={metrics.load_time:.2f}s, "
                                  f"Memory={metrics.memory_usage:.2f}MB, CPU Time={metrics.cpu_time:.2f}s")

                            insert_metrics(metrics)  # Store in SQLite
                            print("Metrics inserted into the database.")

if __name__ == "__main__":
    start_server()
