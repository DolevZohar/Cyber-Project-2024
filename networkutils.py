import pickle
import struct
import socket

def send_pickle(conn, obj):
    """Serialize and send a pickled object with a length prefix."""
    data = pickle.dumps(obj)
    length = struct.pack("!I", len(data))  # Pack length as a 4-byte integer
    conn.sendall(length + data)  # Send length + serialized object

def recv_pickle(conn):
    """Receive a pickled object with a length prefix."""
    length_data = conn.recv(4)  # Read the first 4 bytes (length)
    if not length_data:
        return None
    length = struct.unpack("!I", length_data)[0]  # Unpack the length
    data = b""
    while len(data) < length:
        packet = conn.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return pickle.loads(data)

class CustomSocket:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def send(self, data):
        send_pickle(self.sock, data)

    def receive(self):
        return recv_pickle(self.sock)

    def close(self):
        self.sock.close()


class HandshakeSocket(CustomSocket):
    @classmethod
    def create(cls, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        return cls(sock)


class DynamicClientSocket(CustomSocket):
    @classmethod
    def connect_to_dynamic(cls, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        return cls(sock)

    def send_url(self, url):
        self.send(url)

    def send_done(self):
        self.send("DONE")

    def send_metrics(self, metrics_list):
        for metric in metrics_list:
            self.send(metric)
        self.send_done()

    def receive_url(self):
        return self.receive()
