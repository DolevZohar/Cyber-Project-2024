# security.py
import os
import json
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

FERNET_KEY = os.getenv("FERNET_KEY")
fernet = Fernet(FERNET_KEY)


def encrypt(data):
    # Attempt to make all supported data JSON serializable
    if isinstance(data, (dict, str, int, float, list, bool)) or data is None:
        try:
            json_string = json.dumps(data)
        except (TypeError, ValueError) as e:
            raise ValueError(f"Data could not be serialized to JSON: {e}")
    else:
        print(f"[DEBUG] Non-serializable value encountered in encrypt: {repr(data)} (type: {type(data)})")
        raise ValueError(
            f"Only JSON-serializable types (dict, str, int, float, list, bool, None) are supported for encryption. Got: {type(data)}")

    encrypted = fernet.encrypt(json_string.encode()).decode()
    return encrypted

def decrypt(token):
    if isinstance(token, bytes):
        token = token.decode()
    if not isinstance(token, str):
        raise ValueError("Token must be a string")
    decrypted_bytes = fernet.decrypt(token.encode())  # string → encode to bytes
    try:
        return json.loads(decrypted_bytes)
    except json.JSONDecodeError:
        return decrypted_bytes.decode()
