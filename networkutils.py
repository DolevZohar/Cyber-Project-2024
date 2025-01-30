import pickle
import struct

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
