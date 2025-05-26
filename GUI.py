import os
import sys
import sqlite3
import requests
import hashlib
import statistics
from datetime import datetime
from urllib.parse import urlparse
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QPushButton, QVBoxLayout,
    QLabel, QLineEdit, QListWidget, QMessageBox,
    QComboBox, QSplitter, QCheckBox, QHBoxLayout
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

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
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'user' CHECK (role IN ('user', 'admin', 'owner'))
        );
        CREATE TABLE IF NOT EXISTS urls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            last_checked DATETIME DEFAULT '1970-01-01 00:00:00',
            referenced INTEGER DEFAULT 0,
            forceInactive INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS user_urls (
            user_id INTEGER,
            url_id INTEGER,
            url_nick TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(url_id) REFERENCES urls(id)
        );
    ''')
    # Ensure owner user exists
    cursor.execute("SELECT id FROM users WHERE username = 'owner'")
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'owner')",
                       ('owner', hash_password('ownerpass')))
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
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            browser_id INTEGER,
            is_up INTEGER
        )
    ''')
    conn.commit()
    conn.close()


class Dashboard(QWidget):
    def __init__(self, user_id, role, logout_callback):
        super().__init__()
        self.user_id = user_id
        self.role = role
        self.logout_callback = logout_callback
        self.setWindowTitle("Dashboard")

        self.metric_data = {}

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL")
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search URLs...")
        self.add_btn = QPushButton("Add URL")
        self.url_list = QListWidget()
        self.metric_dropdown = QComboBox()
        self.stats_label = QLabel()
        self.unfollow_btn = QPushButton("Stop Following This URL")
        self.unfollow_btn.clicked.connect(self.remove_selected_url)

        self.browser_checkboxes = {
            "chrome": QCheckBox("Chrome"),
            "edge": QCheckBox("Edge"),
            "opera": QCheckBox("Opera")
        }
        for cb in self.browser_checkboxes.values():
            cb.setChecked(cb.text().lower() == "chrome")
            cb.stateChanged.connect(self.update_metrics)

        self.canvas = FigureCanvas(Figure(figsize=(5, 3)))
        self.canvas.figure.patch.set_facecolor('#1c1c1c')
        self.ax = self.canvas.figure.add_subplot(111)
        self.annot = self.ax.annotate("", xy=(0, 0), xytext=(20, 20), textcoords="offset points",
                                      bbox=dict(boxstyle="round", fc="#2e2e2e", ec="white", lw=0.5),
                                      color='white', fontsize=9,
                                      arrowprops=dict(arrowstyle="->", color='white'))
        self.annot.set_visible(False)
        self.canvas.mpl_connect("motion_notify_event", self.hover)

        self.add_btn.clicked.connect(self.add_url)
        self.search_input.textChanged.connect(self.filter_urls)
        self.url_list.itemSelectionChanged.connect(self.update_metrics)
        self.metric_dropdown.currentTextChanged.connect(self.update_plot)

        left_layout = QVBoxLayout()
        left_layout.addWidget(QLabel("Add or Select URL"))
        left_layout.addWidget(self.url_input)
        left_layout.addWidget(self.add_btn)
        left_layout.addWidget(self.search_input)
        left_layout.addWidget(QLabel("Select Browser"))
        for cb in self.browser_checkboxes.values():
            left_layout.addWidget(cb)
        left_layout.addWidget(self.url_list)
        left_layout.addWidget(QPushButton("Log out", clicked=self.logout_callback))

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Select Metric to View"))
        right_layout.addWidget(self.metric_dropdown)
        right_layout.addWidget(self.canvas)
        right_layout.addWidget(self.stats_label)
        right_layout.addWidget(self.unfollow_btn)
        if self.role in ("admin", "owner"):
            # --- User Management Panel ---
            user_admin_label = QLabel("User Management")
            user_admin_label.setStyleSheet("color: white; font-weight: bold")
            self.user_list = QListWidget()
            self.load_users_button = QPushButton("Load Users")
            self.promote_button = QPushButton("Promote to Admin")
            self.demote_button = QPushButton("Demote to User")

            self.load_users_button.clicked.connect(self.load_users)
            self.promote_button.clicked.connect(self.promote_user)
            self.demote_button.clicked.connect(self.demote_user)

            right_layout.addWidget(user_admin_label)
            right_layout.addWidget(self.user_list)
            right_layout.addWidget(self.load_users_button)
            right_layout.addWidget(self.promote_button)
            right_layout.addWidget(self.demote_button)

        if self.role in ("admin", "owner"):
            self.deactivate_btn = QPushButton("Deactivate Selected URL")
            self.deactivate_btn.clicked.connect(self.deactivate_selected_url)
            right_layout.addWidget(self.deactivate_btn)

            self.reactivate_btn = QPushButton("Reactivate Selected URL")
            self.reactivate_btn.clicked.connect(self.reactivate_selected_url)
            right_layout.addWidget(self.reactivate_btn)



        splitter = QSplitter()
        left_widget = QWidget()
        left_widget.setLayout(left_layout)
        right_widget = QWidget()
        right_widget.setLayout(right_layout)
        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([200, 600])

        main_layout = QVBoxLayout()
        main_layout.addWidget(splitter)
        self.setLayout(main_layout)

        self.refresh_urls()

    def load_users(self):
        self.user_list.clear()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users")
        for uid, name, role in cursor.fetchall():
            self.user_list.addItem(f"{uid} | {name} | {role}")
        conn.close()

    def promote_user(self):
        selected = self.user_list.currentItem()
        if not selected:
            return
        user_id, username, role = [s.strip() for s in selected.text().split("|")]
        if role == "admin":
            QMessageBox.information(self, "Already Admin", f"{username} is already an admin.")
            return
        if role == "owner":
            QMessageBox.warning(self, "Invalid", "Cannot change role of owner.")
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'admin' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        self.load_users()
        QMessageBox.information(self, "Promoted", f"{username} is now an admin.")

    def demote_user(self):
        selected = self.user_list.currentItem()
        if not selected:
            return
        user_id, username, role = [s.strip() for s in selected.text().split("|")]
        if role == "user":
            QMessageBox.information(self, "Already User", f"{username} is already a user.")
            return
        if role == "owner":
            QMessageBox.warning(self, "Invalid", "Cannot demote the owner.")
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'user' WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
        self.load_users()
        QMessageBox.information(self, "Demoted", f"{username} is now a user.")

    def refresh_urls(self):
        self.url_items = []
        self.url_list.clear()
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        if self.role in ("admin", "owner"):
            cursor.execute('''
                SELECT u.id, u.url, u.last_checked, u.forceInactive, u.referenced
                FROM urls u
            ''')
            for url_id, url, checked, inactive, referenced in cursor.fetchall():
                status = "Inactive" if inactive else "Active"
                text = f"{url_id} | {url} (Last checked: {checked}, Status: {status}, Referenced: {referenced})"
                self.url_items.append((text.lower(), text))
        else:
            cursor.execute('''
                SELECT uu.url_id, uu.url_nick, u.last_checked
                FROM user_urls uu
                JOIN urls u ON uu.url_id = u.id
                WHERE uu.user_id = ?
            ''', (self.user_id,))
            for url_id, nick, checked in cursor.fetchall():
                text = f"{url_id} | {nick} (Last checked: {checked})"
                self.url_items.append((text.lower(), text))
        self.filter_urls()
        conn.close()


    def filter_urls(self):
        search_term = self.search_input.text().lower()
        self.url_list.clear()
        for text_lower, full_text in self.url_items:
            if search_term in text_lower:
                self.url_list.addItem(full_text)

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

        # Check if user already used this nickname
        cursor.execute("""
            SELECT 1 FROM user_urls WHERE user_id = ? AND url_nick = ?
        """, (self.user_id, url_nick))
        if cursor.fetchone():
            QMessageBox.information(self, "Already Added", "You are already following this url.")
            conn.close()
            return

        # Check if normalized URL exists in urls table
        cursor.execute("SELECT id FROM urls WHERE url = ?", (url,))
        url_row = cursor.fetchone()

        if url_row:
            url_id = url_row[0]
            # Check if user already added this exact URL
            cursor.execute("""
                SELECT 1 FROM user_urls WHERE user_id = ? AND url_id = ?
            """, (self.user_id, url_id))
            if cursor.fetchone():
                QMessageBox.information(self, "Already Added", "This URL is already in your list.")
                conn.close()
                return
            # Update reference count
            cursor.execute("UPDATE urls SET referenced = referenced + 1 WHERE id = ?", (url_id,))
        else:
            # Insert new URL
            cursor.execute("INSERT INTO urls (url, referenced, forceInactive) VALUES (?, 1, 0)", (url,))
            conn.commit()
            cursor.execute("SELECT id FROM urls WHERE url = ?", (url,))
            url_id = cursor.fetchone()[0]

        # Associate with user
        cursor.execute("INSERT INTO user_urls (user_id, url_id, url_nick) VALUES (?, ?, ?)",
                       (self.user_id, url_id, url_nick))
        conn.commit()
        conn.close()
        self.url_input.clear()
        self.refresh_urls()

    def update_metrics(self):
        selected = self.url_list.currentItem()
        if not selected:
            return
        url_id = int(selected.text().split("|")[0].strip())
        conn_urls = sqlite3.connect(DB_PATH)
        cursor_urls = conn_urls.cursor()
        cursor_urls.execute("SELECT url FROM urls WHERE id=?", (url_id,))
        row = cursor_urls.fetchone()
        conn_urls.close()
        if not row:
            return
        url = row[0]
        conn_metrics = sqlite3.connect(METRICS_PATH)
        cursor = conn_metrics.cursor()
        browser_map = {"chrome": 1, "edge": 2, "opera": 3}
        selected_browser_ids = [browser_map[name] for name, cb in self.browser_checkboxes.items() if cb.isChecked()]
        if not selected_browser_ids:
            self.metric_dropdown.clear()
            self.ax.clear()
            self.canvas.draw()
            self.stats_label.setText("No browsers selected.")
            return

        placeholders = ','.join(['?'] * len(selected_browser_ids))
        cursor.execute(f"SELECT * FROM metrics WHERE url = ? AND browser_id IN ({placeholders}) ORDER BY timestamp",
                       (url, *selected_browser_ids))

        rows = cursor.fetchall()
        if not rows:
            self.metric_dropdown.clear()
            self.ax.clear()
            self.canvas.draw()
            self.stats_label.setText("No data available.")
            return
        column_names = [description[0] for description in cursor.description]
        hide_fcp = 3 in selected_browser_ids

        metric_cols = [
            'load_time', 'memory_usage', 'cpu_time', 'dom_nodes',
            'total_page_size', 'fcp', 'network_requests',
            'script_size', 'timestamp', 'is_up'
        ]
        if hide_fcp:
            metric_cols.remove("fcp")

        self.metric_data = {col: [] for col in column_names if col in metric_cols}
        for row in rows:
            for i, name in enumerate(column_names):
                if name in self.metric_data:
                    self.metric_data[name].append(row[i])
        self.metric_dropdown.clear()
        self.metric_dropdown.addItems([key for key in self.metric_data if key != 'timestamp'])
        self.update_plot(self.metric_dropdown.currentText())
        conn_metrics.close()

    def update_plot(self, metric_name):
        if not self.metric_data or metric_name not in self.metric_data:
            return
        self.ax.clear()
        self.annot.set_visible(False)
        self.values = [v for v in self.metric_data[metric_name] if isinstance(v, (int, float)) and v != -1]
        self.timestamps = [
            datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            for v, ts in zip(self.metric_data[metric_name], self.metric_data['timestamp'])
            if isinstance(v, (int, float)) and v != -1
        ]
        self.line, = self.ax.plot(self.timestamps, self.values, label=metric_name, color='cyan', marker='o')
        self.ax.set_facecolor('#1c1c1c')
        self.ax.set_title(f"{metric_name} Over Time", color='white')
        self.ax.set_xlabel("Time", color='white')
        self.ax.set_ylabel(metric_name, color='white')
        self.ax.tick_params(colors='white')
        self.ax.legend(facecolor='#2e2e2e', edgecolor='white', labelcolor='white')
        self.canvas.draw()
        valid_values = [v for v in self.values if isinstance(v, (int, float))]
        if valid_values:
            mean_val = statistics.mean(valid_values)
            std_val = statistics.stdev(valid_values) if len(valid_values) > 1 else 0
            self.stats_label.setText(f"<b style='color: white;'>Mean:</b> {mean_val:.2f}<br><b style='color: white;'>Std Dev:</b> {std_val:.2f}")
        else:
            self.stats_label.setText("<span style='color:white;'>No valid data for statistics.</span>")

    def hover(self, event):
        if event.inaxes != self.ax or not hasattr(self, 'line'):
            self.annot.set_visible(False)
            self.canvas.draw_idle()
            return
        cont, ind = self.line.contains(event)
        if cont:
            i = ind["ind"][0]
            x = self.timestamps[i]
            y = self.values[i]
            self.annot.xy = (mdates.date2num(x), y)
            self.annot.set_text(f"{x.strftime('%Y-%m-%d %H:%M:%S')}\n{y:.2f}")
            self.annot.set_visible(True)
            self.canvas.draw_idle()
        else:
            self.annot.set_visible(False)
            self.canvas.draw_idle()

    def remove_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to stop following.")
            return

        url_id = int(selected.text().split("|")[0].strip())

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("DELETE FROM user_urls WHERE user_id = ? AND url_id = ?", (self.user_id, url_id))
        cursor.execute("UPDATE urls SET referenced = referenced - 1 WHERE id = ? AND referenced > 0", (url_id,))

        conn.commit()
        conn.close()

        QMessageBox.information(self, "Unfollowed", "You are no longer following this URL.")
        self.refresh_urls()

    def deactivate_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to deactivate.")
            return

        url_id = int(selected.text().split("|")[0].strip())
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE urls SET forceInactive = 1 WHERE id = ?", (url_id,))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Deactivated", "The selected URL has been deactivated.")

    def reactivate_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to reactivate.")
            return

        url_id = int(selected.text().split("|")[0].strip())

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE urls SET forceInactive = 0 WHERE id = ?", (url_id,))
        conn.commit()
        conn.close()

        QMessageBox.information(self, "Reactivated", "The selected URL has been reactivated.")


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
        cursor.execute("SELECT id, role FROM users WHERE username=? AND password_hash=?", (username, password_hash))
        user = cursor.fetchone()
        conn.close()
        if user:
            self.login_callback(user[0], user[1])
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


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("URL Metrics App")
        self.setMinimumSize(900, 600)
        self.login_form = LoginForm(self.login_success, self.show_login)
        self.setCentralWidget(self.login_form)

    def login_success(self, user_id, role):
        self.dashboard = Dashboard(user_id, role, self.show_login)
        self.setCentralWidget(self.dashboard)

    def show_login(self):
        self.login_form = LoginForm(self.login_success, self.show_login)
        self.setCentralWidget(self.login_form)


def apply_dark_theme(app):
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.Window, QColor(30, 30, 30))
    dark_palette.setColor(QPalette.WindowText, Qt.white)
    dark_palette.setColor(QPalette.Base, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.AlternateBase, QColor(60, 60, 60))
    dark_palette.setColor(QPalette.ToolTipBase, Qt.white)
    dark_palette.setColor(QPalette.ToolTipText, Qt.white)
    dark_palette.setColor(QPalette.Text, Qt.white)
    dark_palette.setColor(QPalette.Button, QColor(45, 45, 45))
    dark_palette.setColor(QPalette.ButtonText, Qt.white)
    dark_palette.setColor(QPalette.BrightText, Qt.red)
    dark_palette.setColor(QPalette.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.HighlightedText, Qt.black)
    app.setStyle("Fusion")
    app.setPalette(dark_palette)


def main():
    initialize_databases()
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = AppWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
