import socket
import json
import pickle
from Metrics import Metrics

HOST = '127.0.0.1'  # Localhost
PORT = 65432        # Port to listen on


def start_server():
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
                    decision = input("Type 1 for database access and 2 to input a url: (or type 'exit' to quit) ")
                    if decision.lower() == 'exit':
                        print("Shutting down the server.")
                        conn.sendall(b'exit')
                        return  # Exit the entire server loop
                    elif decision == '1':
                        #database access should go here
                    elif decision == '2':
                        # Send URL to the client
                        url = input("Enter the URL to test (or type 'exit' to quit): ").strip()
                        if url.lower() == "exit":
                            print("Shutting down the server.")
                            conn.sendall(b'exit')
                            return  # Exit the entire server loop

                        conn.sendall(url.encode())

                        # Receive metrics line by line
                        buffer = ""
                        while True:
                            try:
                                data = conn.recv(1024).decode()
                                if not data:
                                    print("Client disconnected.")
                                    return  # Stop processing if the client disconnects

                                buffer += data
                                while "\n" in buffer:  # Process each line in the buffer
                                    line, buffer = buffer.split("\n", 1)
                                    if line == "DONE":
                                        print("All metrics received for the URL.")
                                        break
                                    try:
                                        metrics = json.loads(line)
                                        print(f"Received metrics: {metrics}")
                                    except json.JSONDecodeError:
                                        print(f"Failed to decode line: {line}")
                                if "DONE" in line:
                                    break  # Exit inner loop when "DONE" is received
                            except ConnectionResetError:
                                print("Connection with client was reset.")
                                return


def main():
    start_server()


if __name__ == "__main__":
    main()
