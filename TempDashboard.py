from metrics import Metrics
import sqlite3

def initializeDatabase():
    """Creates the SQLite database and urls table if they don't exist."""
    conn = sqlite3.connect("urls.db")
    cursor = conn.cursor()
    cursor.execute('''
            CREATE TABLE IF NOT EXISTS urls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT
            )
        ''')
    conn.commit()
    conn.close()

def chooseUrl():
    maxId=0
    conn = sqlite3.connect("url.db")
    cursor = conn.cursor()
    table = cursor.fetchall()
    for row in table:
        print("1. "row.url)
        ++maxId

    id = input("Enter desired id")
    if id>maxId
        raise Exception("There is no url with such id")
    if id<0
        raise Exception("Id must not be negative")

def getStatistics(url):
