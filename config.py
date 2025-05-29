import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()


DB_PARAMS = {
    'dbname': os.getenv('DB_NAME'),
    'user': os.getenv('DB_USER'),
    'password': os.getenv('DB_PASSWORD'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}
HANDSHAKE_PORT = int(os.getenv("HANDSHAKE_PORT", "65431"))


def get_db_conn():
    return psycopg2.connect(**DB_PARAMS)
