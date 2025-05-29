import json
import socket

class BaseSocket:
    def __init__(self, conn):
        self.conn = conn
        self.buffer = b""

    def send(self, obj):
        if isinstance(obj, (dict, list, int, float, bool, str, type(None))):
            json_string = json.dumps(obj)
            self.conn.sendall((json_string + '\n').encode('utf-8'))  # Ensure bytes
        else:
            raise TypeError(f"Only JSON-serializable types can be sent. Got: {type(obj)}")

    def receive(self):
        while b'\n' not in self.buffer:
            chunk = self.conn.recv(4096)
            if not chunk:
                return None
            self.buffer += chunk

        line, self.buffer = self.buffer.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))  # Convert bytes to str

    def close(self):
        self.conn.close()


class HandshakeSocket(BaseSocket):
    @classmethod
    def create(cls, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, port))
        return cls(sock)


class DynamicClientSocket(BaseSocket):
    @classmethod
    def connect_to_dynamic(cls, host, port):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect((host, int(port)))  # Ensure port is int
        return cls(sock)

    def send_metrics(self, metrics_list):
        serializable_data = [m.to_dict() for m in metrics_list]
        self.send(serializable_data)

    def send_done(self):
        self.send("DONE")

    def receive_url(self):
        return self.receive()
