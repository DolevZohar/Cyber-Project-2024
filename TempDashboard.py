from metrics import Metrics
import sqlite3
import requests
from urllib.parse import urlparse

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
    maxId=1
    conn = sqlite3.connect("url.db")
    cursor = conn.cursor()
    table = cursor.fetchall()
    for row in table:
        print("1. "row.url)
        ++maxId

    id = input("Enter desired id")
    if id>maxId:
        raise Exception("There is no url with such id")
    if id<1:
        raise Exception("Id must be at least 1")

    return table[id]

def ValidateUrl(url):
    if not urlparse.scheme(url):
        url = 'http://' + url
    return url

def CheckUrlIntegrity(url):
    url = ValidateUrl(url)

    try:
        response = requests.get(url)
        # If the status code is 200, the URL is reachable
        if response.status_code == 200:
            print("URL is valid and reachable.")
            return True
        else:
            print(f"URL returned status code: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        # Handling errors
        print(f"An error occurred: {e}")
        return False

def getUrl():
    url = input("Enter your desired url")
    if (CheckUrlIntegrity(url))
        GetDesiredVariables(ValidateUrl(url))
    else:
        print("Invalid url")
    return

def GetDesiredVariables(url):
    finished = false
    while not finished:
        try:
            cpu_time_weight = input("Enter weight for cpu_time")
            if (cpu_time_weight<0)
                raise

def getStatistics(url):
