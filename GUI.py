import os
import sys
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
import psycopg2
from config import get_db_conn
from NotificationGUI import NotificationSettingsDialog
from PySide6.QtWidgets import QFormLayout, QDialog, QDialogButtonBox
from dotenv import set_key, load_dotenv
from pathlib import Path




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
    conn = get_db_conn()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE,
            password_hash TEXT,
            role TEXT DEFAULT 'user' CHECK (role IN ('user', 'admin', 'owner')),
            email TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS urls (
            id SERIAL PRIMARY KEY,
            url TEXT UNIQUE,
            last_checked TIMESTAMP DEFAULT '1970-01-01 00:00:00',
            referenced INTEGER DEFAULT 0,
            forceInactive INTEGER DEFAULT 0
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_urls (
            user_id INTEGER REFERENCES users(id),
            url_id INTEGER REFERENCES urls(id),
            url_nick TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client_groups (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS node_role (
            role TEXT CHECK(role IN ('client', 'server')) NOT NULL,
            active INTEGER DEFAULT 1 CHECK (active IN (0,1)),
            group_id INTEGER
        );
    ''')

    cursor.execute("SELECT id FROM users WHERE username = %s", ('owner',))
    if not cursor.fetchone():
        cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'owner')",
                       ('owner', hash_password('ownerpass')))

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics (
            id SERIAL PRIMARY KEY,
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
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            browser_id INTEGER,
            is_up INTEGER,
            group_id INTEGER
        );
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            url_id INTEGER REFERENCES urls(id),
            metric TEXT,
            type TEXT CHECK(type IN ('hard_cap', 'percent_cap', 'on_down', 'on_broken_link')),
            threshold REAL,
            last_value REAL,
            email TEXT
        );
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS server_info (
            id SERIAL PRIMARY KEY,
        encrypted_ip TEXT NOT NULL
    );
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
        self.canvas.setMouseTracking(True)
        self.canvas.figure.patch.set_facecolor('#1c1c1c')
        self.ax = self.canvas.figure.add_subplot(111)
        self.annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(20, 20), textcoords="offset points",
            bbox=dict(boxstyle="round", fc="#444444", ec="white", lw=1),
            fontsize=10, color="white",
            arrowprops=dict(arrowstyle="->", color="white")
        )
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
        self.notifications_btn = QPushButton("Notification Settings")
        self.notifications_btn.clicked.connect(self.open_notifications)
        left_layout.addWidget(self.notifications_btn)

        right_layout = QVBoxLayout()
        right_layout.addWidget(QLabel("Select Metric to View"))
        right_layout.addWidget(self.metric_dropdown)
        self.hover_label = QLabel("")
        self.hover_label.setStyleSheet("color: lightgreen")
        right_layout.addWidget(self.canvas)
        right_layout.addWidget(self.hover_label)
        right_layout.addWidget(self.stats_label)

        right_layout.addWidget(self.unfollow_btn)


        if self.role in ("admin", "owner"):
            # --- User Management Panel ---
            user_admin_label = QLabel("User Management")
            user_admin_label.setStyleSheet("color: white; font-weight: bold")
            self.user_list = QListWidget()
            self.user_search_input = QLineEdit()
            self.user_search_input.setPlaceholderText("Search users...")
            self.user_search_input.textChanged.connect(self.filter_users)
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
            right_layout.addWidget(user_admin_label)
            right_layout.addWidget(self.user_search_input)
            right_layout.addWidget(self.user_list)
            right_layout.addWidget(self.load_users_button)

            self.set_client_btn = QPushButton("Run as Client")
            self.set_server_btn = QPushButton("Run as Server")
            self.set_notif_btn = QPushButton("Run as Notification Crawler")
            self.set_client_btn.clicked.connect(self.set_as_client)
            self.set_server_btn.clicked.connect(self.set_as_server)
            self.set_notif_btn.clicked.connect(self.set_as_notification_crawler)
            right_layout.addWidget(self.set_client_btn)
            right_layout.addWidget(self.set_server_btn)
            right_layout.addWidget(self.set_notif_btn)

            self.group_manage_label = QLabel("Client Group Management")
            self.group_manage_label.setStyleSheet("color: white; font-weight: bold")
            self.group_create_input = QLineEdit()
            self.group_create_input.setPlaceholderText("New Group Name")
            self.create_group_btn = QPushButton("Create Group")
            self.delete_group_btn = QPushButton("Delete Selected Group")
            self.group_list = QComboBox()
            self.refresh_group_list()

            self.create_group_btn.clicked.connect(self.create_group)
            self.delete_group_btn.clicked.connect(self.delete_group)

            right_layout.addWidget(self.group_manage_label)
            right_layout.addWidget(self.group_create_input)
            right_layout.addWidget(self.create_group_btn)
            right_layout.addWidget(self.group_list)
            right_layout.addWidget(self.delete_group_btn)

        if self.role in ("admin", "owner"):
            self.deactivate_btn = QPushButton("Deactivate Selected URL")
            self.deactivate_btn.clicked.connect(self.deactivate_selected_url)
            right_layout.addWidget(self.deactivate_btn)

            self.reactivate_btn = QPushButton("Reactivate Selected URL")
            self.reactivate_btn.clicked.connect(self.reactivate_selected_url)
            right_layout.addWidget(self.reactivate_btn)

        self.group_filter = QComboBox()
        self.group_filter.addItem("All Groups", None)
        self.group_filter.currentIndexChanged.connect(self.update_metrics)
        right_layout.addWidget(QLabel("Filter by Group"))
        right_layout.addWidget(self.group_filter)
        self.refresh_groups()



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
        self.user_items = []
        self.user_list.clear()
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role FROM users")
        for uid, name, role in cursor.fetchall():
            entry = f"{uid} | {name} | {role}"
            self.user_items.append((entry.lower(), entry))
        conn.close()
        self.filter_users()

    def filter_users(self):
        term = self.user_search_input.text().lower()
        self.user_list.clear()
        for lower_text, full_text in self.user_items:
            if term in lower_text:
                self.user_list.addItem(full_text)

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
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'admin' WHERE id = %s", (user_id,))
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
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = 'user' WHERE id = %s", (user_id,))
        conn.commit()
        conn.close()
        self.load_users()
        QMessageBox.information(self, "Demoted", f"{username} is now a user.")

    def refresh_urls(self):
        self.url_items = []
        self.url_list.clear()
        conn = get_db_conn()
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
                WHERE uu.user_id = %s
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

        conn = get_db_conn()
        cursor = conn.cursor()

        # Check if user already used this nickname
        cursor.execute("""
            SELECT 1 FROM user_urls WHERE user_id = %s AND url_nick = %s
        """, (self.user_id, url_nick))
        if cursor.fetchone():
            QMessageBox.information(self, "Already Added", "You are already following this url.")
            conn.close()
            return

        # Check if normalized URL exists in urls table
        cursor.execute("SELECT id FROM urls WHERE url = %s", (url,))
        url_row = cursor.fetchone()

        if url_row:
            url_id = url_row[0]
            # Check if user already added this exact URL
            cursor.execute("""
                SELECT 1 FROM user_urls WHERE user_id = %s AND url_id = %s
            """, (self.user_id, url_id))
            if cursor.fetchone():
                QMessageBox.information(self, "Already Added", "This URL is already in your list.")
                conn.close()
                return
            # Update reference count
            cursor.execute("UPDATE urls SET referenced = referenced + 1 WHERE id = %s", (url_id,))
        else:
            # Insert new URL
            cursor.execute("INSERT INTO urls (url, referenced, forceInactive) VALUES (%s, 1, 0)", (url,))
            conn.commit()
            cursor.execute("SELECT id FROM urls WHERE url = %s", (url,))
            url_id = cursor.fetchone()[0]

        # Associate with user
        cursor.execute("INSERT INTO user_urls (user_id, url_id, url_nick) VALUES (%s, %s, %s)",
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
        conn_urls = get_db_conn()
        cursor_urls = conn_urls.cursor()
        cursor_urls.execute("SELECT url FROM urls WHERE id=%s", (url_id,))
        row = cursor_urls.fetchone()
        conn_urls.close()
        if not row:
            return
        url = row[0]
        conn_metrics = get_db_conn()
        cursor = conn_metrics.cursor()
        browser_map = {"chrome": 1, "edge": 2, "opera": 3}
        selected_browser_ids = [browser_map[name] for name, cb in self.browser_checkboxes.items() if cb.isChecked()]
        if not selected_browser_ids:
            self.metric_dropdown.clear()
            self.ax.clear()
            self.canvas.draw()
            self.stats_label.setText("No browsers selected.")
            return

        placeholders = ','.join(['%s'] * len(selected_browser_ids))
        cursor.execute(f"SELECT * FROM metrics WHERE url = %s AND browser_id IN ({placeholders}) ORDER BY timestamp",
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

        selected_gid = self.group_filter.currentData()
        if selected_gid is not None:
            cursor.execute(
                f"SELECT * FROM metrics WHERE url = %s AND browser_id IN ({placeholders}) AND group_id = %s ORDER BY timestamp",
                (url, *selected_browser_ids, selected_gid))
        else:
            cursor.execute(f"SELECT * FROM metrics WHERE url = %s AND browser_id IN ({placeholders}) ORDER BY timestamp",
                           (url, *selected_browser_ids))

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

        from matplotlib.dates import date2num

        self.line = None

        self.ax.clear()
        self.annot.set_visible(False)

        # Filter values and corresponding timestamps
        self.values = [v for v in self.metric_data[metric_name] if isinstance(v, (int, float)) and v != -1]
        self.timestamps = [
            ts if isinstance(ts, datetime) else datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
            for v, ts in zip(self.metric_data[metric_name], self.metric_data['timestamp'])
            if isinstance(v, (int, float)) and v != -1
        ]

        # Convert timestamps to numeric format for matplotlib
        x_vals = [date2num(ts) for ts in self.timestamps]

        # Plot the line with hover-friendly picker and markers
        self.line, = self.ax.plot(
            x_vals,
            self.values,
            label=metric_name,
            color='cyan',
            marker='o',
            markersize=8,
            picker=5  # Needed for .contains(event)
        )

        self.ax.xaxis_date()  # interpret x-axis as dates

        # Apply dark background styling
        self.ax.set_facecolor('#1c1c1c')
        self.ax.set_title(f"{metric_name} Over Time", color='white')
        self.ax.set_xlabel("Time", color='white')
        self.ax.set_ylabel(metric_name, color='white')
        self.ax.tick_params(colors='white')
        self.ax.legend(facecolor='#2e2e2e', edgecolor='white', labelcolor='white')

        # Update the canvas
        self.canvas.draw()

        # Show stats if any valid data
        valid_values = [v for v in self.values if isinstance(v, (int, float))]
        if valid_values:
            mean_val = statistics.mean(valid_values)
            std_val = statistics.stdev(valid_values) if len(valid_values) > 1 else 0
            self.stats_label.setText(
                f"<b style='color: white;'>Mean:</b> {mean_val:.2f}<br><b style='color: white;'>Std Dev:</b> {std_val:.2f}"
            )
        else:
            self.stats_label.setText("<span style='color:white;'>No valid data for statistics.</span>")

    def hover(self, event):
        if not hasattr(self, 'line') or self.line is None:
            return

        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            if hasattr(self, 'hover_marker'):
                self.hover_marker.remove()
                del self.hover_marker
            self.hover_label.setText("")
            self.canvas.draw_idle()
            return

        x_vals = self.line.get_xdata()
        y_vals = self.line.get_ydata()

        min_dist = float('inf')
        closest_index = None
        for i, (x, y) in enumerate(zip(x_vals, y_vals)):
            dist = (x - event.xdata) ** 2 + (y - event.ydata) ** 2
            if dist < min_dist:
                min_dist = dist
                closest_index = i

        if closest_index is not None:
            x = x_vals[closest_index]
            y = y_vals[closest_index]
            ts = self.timestamps[closest_index]

            # Update marker
            if hasattr(self, 'hover_marker'):
                self.hover_marker.remove()
            self.hover_marker = self.ax.plot(x, y, 'ro', markersize=10)[0]

            # Update label
            self.hover_label.setText(f"Hovered Point: {ts.strftime('%Y-%m-%d %H:%M:%S')} | Value: {y:.2f}")

            self.canvas.draw_idle()

    def remove_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to stop following.")
            return

        url_id = int(selected.text().split("|")[0].strip())

        conn = get_db_conn()
        cursor = conn.cursor()

        # Delete notifications related to this user and this URL
        cursor.execute("DELETE FROM notifications WHERE user_id = %s AND url_id = %s", (self.user_id, url_id))

        # Remove the URL-user association
        cursor.execute("DELETE FROM user_urls WHERE user_id = %s AND url_id = %s", (self.user_id, url_id))

        # Update the reference count for the URL
        cursor.execute("UPDATE urls SET referenced = referenced - 1 WHERE id = %s AND referenced > 0", (url_id,))

        conn.commit()
        conn.close()

        QMessageBox.information(self, "Unfollowed",
                                "You are no longer following this URL, and related notifications were deleted.")
        self.refresh_urls()

    def deactivate_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to deactivate.")
            return

        url_id = int(selected.text().split("|")[0].strip())
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE urls SET forceInactive = 1 WHERE id = %s", (url_id,))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Deactivated", "The selected URL has been deactivated.")

    def reactivate_selected_url(self):
        selected = self.url_list.currentItem()
        if not selected:
            QMessageBox.warning(self, "No Selection", "Please select a URL to reactivate.")
            return

        url_id = int(selected.text().split("|")[0].strip())

        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE urls SET forceInactive = 0 WHERE id = %s", (url_id,))
        conn.commit()
        conn.close()

        QMessageBox.information(self, "Reactivated", "The selected URL has been reactivated.")

    def set_as_server(self):
        from security import encrypt
        import socket
        fields = ["FERNET_KEY", "DB_USER", "DB_PASSWORD", "HANDSHAKE_PORT"]
        dialog = EnvSetupDialog(fields, self)
        if dialog.exec() == QDialog.Accepted:
            env_path = Path(".env")
            values = dialog.get_values()
            for key, value in values.items():
                set_key(str(env_path), key, value)
            load_dotenv()
            conn = get_db_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM node_role")
            cursor.execute("INSERT INTO node_role (role, active) VALUES ('server', 1)")
            # Store encrypted IP
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
            finally:
                s.close()
            set_key(str(env_path), "SERVER_IP", ip)
            encrypted_ip = encrypt({"ip": ip})
            cursor.execute("DELETE FROM server_info")
            cursor.execute("INSERT INTO server_info (encrypted_ip) VALUES (%s)", (encrypted_ip,))
            conn.commit()
            conn.close()
            QMessageBox.information(self, "Success", "This machine is now set as SERVER.")
            os.system("start cmd /k python server.py")

    def set_as_client(self):
        from security import decrypt
        fields = ["FERNET_KEY", "HANDSHAKE_PORT"]
        dialog = EnvSetupDialog(fields, self)

        if dialog.exec() == QDialog.Accepted:
            env_path = Path(".env")
            values = dialog.get_values()

            for key, value in values.items():
                set_key(str(env_path), key, value)
            load_dotenv()

            try:
                conn = get_db_conn()
                cursor = conn.cursor()

                # Retrieve encrypted IP from server_info (or node_role if you use that)
                cursor.execute("SELECT encrypted_ip FROM server_info LIMIT 1")
                row = cursor.fetchone()

                if row:
                    decrypted = decrypt(row[0])
                    server_ip = decrypted if isinstance(decrypted, str) else decrypted.get("ip")

                    if not server_ip:
                        QMessageBox.critical(self, "Decryption Error", "Decrypted IP is invalid.")
                        return

                    set_key(str(env_path), "SERVER_IP", server_ip)
                else:
                    QMessageBox.critical(self, "Missing IP", "No encrypted server IP found in database.")
                    return
            except Exception as e:
                QMessageBox.critical(self, "DB Error", f"Could not retrieve server IP.\n\n{e}")
                return
            finally:
                conn.close()

            # Get group and update role
            group_id = self.group_list.currentData()
            if group_id is None:
                QMessageBox.warning(self, "Select Group", "You must select a group before continuing.")
                return

            conn = get_db_conn()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM node_role")
            cursor.execute("INSERT INTO node_role (role, active, group_id) VALUES ('client', 1, %s)", (group_id,))
            conn.commit()
            conn.close()

            QMessageBox.information(self, "Client Set", f"This machine is now a CLIENT in group ID {group_id}.")
            os.system("start cmd /k python client_worker.py")

    def set_as_notification_crawler(self):
        fields = ["DB_USER", "DB_PASSWORD", "FERNET_KEY", "SENDER_EMAIL", "SENDER_PASSWORD"]
        dialog = EnvSetupDialog(fields, self)
        if dialog.exec() == QDialog.Accepted:
            env_path = Path(".env")
            for key, value in dialog.get_values().items():
                set_key(str(env_path), key, value)
            load_dotenv()
            QMessageBox.information(self, "Notification Crawler Set",
                                    "This machine is now set as a NOTIFICATION CRAWLER.")
            os.system("start cmd /k python notificationCrawler.py")

    def refresh_groups(self):
        self.group_filter.clear()
        self.group_filter.addItem("All Groups", None)
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT cg.id, cg.name
            FROM client_groups cg
            JOIN metrics m ON m.group_id = cg.id
        """)
        for gid, name in cursor.fetchall():
            self.group_filter.addItem(f"{name} (ID {gid})", gid)
        conn.close()

    def refresh_group_list(self):
        self.group_list.clear()
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM client_groups ORDER BY name")
        for gid, name in cursor.fetchall():
            self.group_list.addItem(f"{name} (ID {gid})", gid)
        conn.close()

    def create_group(self):
        name = self.group_create_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Input Error", "Group name cannot be empty.")
            return

        conn = get_db_conn()
        cursor = conn.cursor()
        try:
            # Check if name already exists
            cursor.execute("SELECT 1 FROM client_groups WHERE name = %s", (name,))
            if cursor.fetchone():
                QMessageBox.warning(self, "Duplicate Group", "A group with this name already exists.")
                return

            cursor.execute("INSERT INTO client_groups (name) VALUES (%s)", (name,))
            conn.commit()
            QMessageBox.information(self, "Success", f"Group '{name}' created successfully.")
            self.group_create_input.clear()
        except Exception as e:
            QMessageBox.critical(self, "Database Error", f"Failed to create group:\n{str(e)}")
        finally:
            conn.close()

        self.refresh_group_list()
        self.refresh_groups()

    def delete_group(self):
        group_id = self.group_list.currentData()
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM node_role WHERE group_id = %s", (group_id,))
        if cursor.fetchone()[0] > 0:
            QMessageBox.warning(self, "Error", "Cannot delete group in use.")
        else:
            cursor.execute("DELETE FROM client_groups WHERE id = %s", (group_id,))
            conn.commit()
            QMessageBox.information(self, "Deleted", "Group deleted.")
        conn.close()
        self.refresh_group_list()
        self.refresh_groups()

    def open_notifications(self):
        dialog = NotificationSettingsDialog(self.user_id)
        dialog.exec()


class EnvSetupDialog(QDialog):
    def __init__(self, fields, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Environment Variables")
        layout = QVBoxLayout()
        self.inputs = {}
        form_layout = QFormLayout()
        for field in fields:
            input_field = QLineEdit()
            form_layout.addRow(QLabel(field + ":"), input_field)
            self.inputs[field] = input_field
        layout.addLayout(form_layout)

        self.button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)
        self.setLayout(layout)

    def get_values(self):
        return {field: input_field.text().strip() for field, input_field in self.inputs.items()}

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
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id, role FROM users WHERE username=%s AND password_hash=%s", (username, password_hash))
        user = cursor.fetchone()
        conn.close()
        if user:
            self.login_callback(user[0], user[1])
        else:
            QMessageBox.warning(self, "Login Failed", "Invalid credentials.")

    def register(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        if not username or not password:
            QMessageBox.warning(self, "Missing Fields", "Please fill in all fields.")
            return

        if len(username) > 20 or len(password) > 20:
            QMessageBox.warning(self, "Input Too Long", "Username and password must not exceed 20 characters.")
            return

        hashed_pw = hash_password(password)

        conn = get_db_conn()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
                (username, hashed_pw)
            )
            conn.commit()
            QMessageBox.information(self, "Registered", "User registered successfully.")
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            QMessageBox.warning(self, "Exists", "Username already exists.")
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
