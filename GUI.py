import os
import sys
import sqlite3
import requests
import hashlib
import statistics
from urllib.parse import urlparse
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QMessageBox)
from PySide6.QtCore import Qt

# Ensure we use the script's directory as base
BASE_DIR = os.path.dirname(os.path.realpath(sys.argv[0]))
DB_PATH = os.path.join(BASE_DIR, "urls.db")
METRICS_PATH = os.path.join(BASE_DIR, "metrics.db")

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def resolve_final_url(input_url):
    if not input_url.startswith("http://") and not input_url.startswith("https://"):
        input_url = "https://" + input_url
    try:
        response = requests.get(input_url, timeout=10, allow_redirects=True)
        return response.url
    except requests.RequestException:
        return None

def initialize_databases():
    print(f"Using DB path: {DB_PATH}")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT
        );
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            last_checked DATETIME DEFAULT '1970-01-01 00:00:00'
        );
        CREATE TABLE IF NOT EXISTS user_urls (
            user_id INTEGER,
            url_id INTEGER,
            url_nick TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(url_id) REFERENCES urls(id)
        );
    ''')
    conn.commit()
    conn.close()

    conn = sqlite3.connect(METRICS_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            load_time REAL,
            memory_usage REAL,
            cpu_time REAL,
            dom_nodes INTEGER,
            total_page_size REAL,
            fcp REAL,
            network_requests INTEGER,
            script_size REAL,
            broken_links TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


class LoginForm(QWidget):
    def __init__(self, login_callback, register_callback):
        super().__init__()
        self.login_callback = login_callback
        self.register_callback = register_callback
        self.setWindowTitle("Login")
        layout = QVBoxLayout()

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)

        login_btn = QPushButton("Login")
        register_btn = QPushButton("Register")

        login_btn.clicked.connect(self.login)
        register_btn.clicked.connect(self.register)

        layout.addWidget(QLabel("Welcome - Please login or register"))
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(login_btn)
        layout.addWidget(register_btn)
        self.setLayout(layout)

    def login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        password_hash = hash_password(password)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username=? AND password_hash=?", (username, password_hash))
        user = cursor.fetchone()
        conn.close()

        if user:
            self.login_callback(user[0])
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid credentials.")

    def register(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()
        password_hash = hash_password(password)

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            QMessageBox.information(self, "Success", "Registration successful. Please log in.")
        except sqlite3.IntegrityError:
            QMessageBox.warning(self, "Error", "Username already exists.")
        finally:
            conn.close()

class Dashboard(QWidget):
    def __init__(self, user_id, logout_callback):
        super().__init__()
        self.user_id = user_id
        self.logout_callback = logout_callback
        self.setWindowTitle("Dashboard")

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL")
        self.add_btn = QPushButton("Add URL")
        self.url_list = QListWidget()
        self.stats_btn = QPushButton("Show Stats")
        self.logout_btn = QPushButton("Log out")

        self.add_btn.clicked.connect(self.add_url)
        self.stats_btn.clicked.connect(self.show_stats)
        self.logout_btn.clicked.connect(self.logout)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Dashboard"))
        layout.addWidget(self.url_input)
        layout.addWidget(self.add_btn)
        layout.addWidget(QLabel("Your URLs:"))
        layout.addWidget(self.url_list)
        layout.addWidget(self.stats_btn)
        layout.addWidget(self.logout_btn)
        self.setLayout(layout)

        self.refresh_urls()

    def refresh_urls(self):
        self.url_list.clear()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT uu.url_id, uu.url_nick, u.last_checked
            FROM user_urls uu
            JOIN urls u ON uu.url_id = u.id
            WHERE uu.user_id = ?
        ''', (self.user_id,))
        for url_id, nick, checked in cursor.fetchall():
            self.url_list.addItem(f"{url_id} | {nick} (Last checked: {checked})")
        conn.close()

    def add_url(self):
        url_nick = self.url_input.text().strip()
        if not url_nick:
            return

        url = resolve_final_url(url_nick)
        if not url:
            QMessageBox.warning(self, "Error", "Could not resolve URL.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO urls (url) VALUES (?)", (url,))
        conn.commit()
        cursor.execute("SELECT id FROM urls WHERE url=?", (url,))
        url_id = cursor.fetchone()[0]
        cursor.execute("INSERT INTO user_urls (user_id, url_id, url_nick) VALUES (?, ?, ?)",
                       (self.user_id, url_id, url_nick))
        conn.commit()
        conn.close()

        self.url_input.clear()
        self.refresh_urls()

    def show_stats(self):
        selected = self.url_list.currentItem()
        if not selected:
            return
        url_id = int(selected.text().split("|")[0].strip())

        conn = sqlite3.connect(METRICS_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM metrics WHERE url = (SELECT url FROM urls WHERE id=?)", (url_id,))
        rows = cursor.fetchall()
        if not rows:
            QMessageBox.information(self, "No Data", "No metrics available.")
            return

        column_names = [description[0] for description in cursor.description]
        text = ""
        metrics_to_show = ['load_time', 'memory_usage', 'cpu_time', 'dom_nodes',
                           'total_page_size', 'fcp', 'network_requests', 'script_size']

        for i, name in enumerate(column_names):
            if name in metrics_to_show:
                values = [row[i] for row in rows if isinstance(row[i], (int, float))]
                if values:
                    mean_val = statistics.mean(values)
                    std_val = statistics.stdev(values) if len(values) > 1 else 0
                    text += f"{name}: mean = {mean_val:.2f}, std = {std_val:.2f}\n"

        QMessageBox.information(self, "Stats", text)
        conn.close()

    def logout(self):
        self.logout_callback()

class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("URL Metrics App")
        self.setMinimumSize(500, 400)
        self.login_form = LoginForm(self.login_success, self.show_login)
        self.setCentralWidget(self.login_form)

    def login_success(self, user_id):
        self.dashboard = Dashboard(user_id, self.show_login)
        self.setCentralWidget(self.dashboard)

    def show_login(self):
        self.login_form = LoginForm(self.login_success, self.show_login)
        self.setCentralWidget(self.login_form)

def main():
    initialize_databases()
    app = QApplication(sys.argv)
    window = AppWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
