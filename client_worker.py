import socket
from multiprocessing import Process, Queue
from networkutils import HandshakeSocket, DynamicClientSocket
import requests
from client_browsers import browser_loop

SERVER_HOST = '127.0.0.1'
PERMANENT_PORT = 65431
BROWSERS = ["chrome", "edge", "opera"]

def connect_to_server():
    handshake = HandshakeSocket.create(SERVER_HOST, PERMANENT_PORT)
    dynamic_port = handshake.receive()
    handshake.close()
    return DynamicClientSocket.connect_to_dynamic(SERVER_HOST, dynamic_port)

def main():
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

            client_socket.send_metrics(flattened_metrics)
            client_socket.send_done()
            print("Sent all metrics to server.")

    finally:
        client_socket.close()
        for p in processes:
            p.join()
        print("Client shutdown complete.")

if __name__ == "__main__":
    main()
