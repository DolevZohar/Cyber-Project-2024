import psycopg2
from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QComboBox, QLineEdit, QPushButton, QMessageBox
)
from config import get_db_conn
import re

class NotificationSettingsDialog(QDialog):
    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id
        self.setWindowTitle("Notification Settings")
        self.setMinimumWidth(400)

        layout = QVBoxLayout()

        self.url_dropdown = QComboBox()
        self.metric_dropdown = QComboBox()
        self.type_dropdown = QComboBox()
        self.threshold_input = QLineEdit()
        self.email_input = QLineEdit()
        self.save_btn = QPushButton("Save Notification")
        self.notification_dropdown = QComboBox()
        self.remove_btn = QPushButton("Remove Selected Notification")
        self.disable_btn = QPushButton("Disable Selected Notification")
        self.enable_btn = QPushButton("Enable Selected Notification")




        layout.addWidget(QLabel("Select URL:"))
        layout.addWidget(self.url_dropdown)
        layout.addWidget(QLabel("Notification Type:"))
        layout.addWidget(self.type_dropdown)
        layout.addWidget(QLabel("Metric:"))
        layout.addWidget(self.metric_dropdown)
        layout.addWidget(QLabel("Threshold (for cap types):"))
        layout.addWidget(self.threshold_input)
        layout.addWidget(QLabel("Notification Email:"))
        layout.addWidget(self.email_input)
        layout.addWidget(self.save_btn)
        layout.addWidget(QLabel("Your Notifications:"))
        layout.addWidget(self.notification_dropdown)
        layout.addWidget(self.remove_btn)
        layout.addWidget(self.disable_btn)
        layout.addWidget(self.enable_btn)


        self.load_notifications()
        self.remove_btn.clicked.connect(self.remove_notification)
        self.disable_btn.clicked.connect(self.disable_notification)
        self.enable_btn.clicked.connect(self.enable_notification)

        self.setLayout(layout)

        self.type_dropdown.addItems([
            "hard_cap", "percent_cap", "on_down", "on_broken_link"
        ])
        self.metric_dropdown.addItems([
            "load_time", "memory_usage", "cpu_time", "dom_nodes",
            "total_page_size", "fcp", "network_requests", "script_size"
        ])

        self.type_dropdown.currentTextChanged.connect(self.update_input_visibility)
        self.update_input_visibility(self.type_dropdown.currentText())

        self.populate_urls()
        self.load_user_email()

        self.save_btn.clicked.connect(self.save_notification)

    def update_input_visibility(self, notif_type):
        if notif_type in ("hard_cap", "percent_cap"):
            self.metric_dropdown.setEnabled(True)
            self.threshold_input.setEnabled(True)
        else:
            self.metric_dropdown.setEnabled(False)
            self.threshold_input.setEnabled(False)

    def populate_urls(self):
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.url_id, u.url_nick FROM user_urls u
            JOIN urls l ON u.url_id = l.id
            WHERE u.user_id = %s
        """, (self.user_id,))
        self.url_map = {}
        for url_id, nick in cursor.fetchall():
            self.url_dropdown.addItem(nick, url_id)
            self.url_map[nick] = url_id
        conn.close()

    def load_user_email(self):
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE id = %s", (self.user_id,))
        result = cursor.fetchone()
        if result and result[0]:
            self.email_input.setText(result[0])
        conn.close()

    def save_notification(self):
        url_id = self.url_dropdown.currentData()
        metric = self.metric_dropdown.currentText()
        notif_type = self.type_dropdown.currentText()
        threshold = self.threshold_input.text().strip()
        email = self.email_input.text().strip()

        if notif_type in ("hard_cap", "percent_cap"):
            try:
                threshold = float(threshold)
            except ValueError:
                QMessageBox.warning(self, "Invalid Input", "Threshold must be a number.")
                return
        else:
            threshold = None
            metric = None

        if not email:
            QMessageBox.warning(self, "Missing Email", "Please enter your email.")
            return

        # Basic email format validation
        email_pattern = r'^[\w\.-]+@[\w\.-]+\.\w+$'
        if not re.match(email_pattern, email):
            QMessageBox.warning(self, "Invalid Email", "Please enter a valid email address.")
            return

        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INTEGER,
                url_id INTEGER,
                metric TEXT,
                type TEXT CHECK(type IN ('hard_cap', 'percent_cap', 'on_down', 'on_broken_link')),
                threshold REAL,
                last_value REAL,
                email TEXT,
                last_notified TIMESTAMP,
                active BOOLEAN DEFAULT TRUE,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(url_id) REFERENCES urls(id)
            )
        ''')
        cursor.execute('''
            INSERT INTO notifications (user_id, url_id, metric, type, threshold, email)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (self.user_id, url_id, metric, notif_type, threshold, email))
        cursor.execute("UPDATE users SET email = %s WHERE id = %s", (email, self.user_id))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Saved", "Notification preference saved.")
        self.accept()

    def load_notifications(self):
        self.notification_dropdown.clear()
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT n.id, n.type, n.metric, n.threshold, uu.url_nick, n.active
            FROM notifications n
            JOIN user_urls uu ON n.url_id = uu.url_id AND n.user_id = uu.user_id
            WHERE n.user_id = %s
        """, (self.user_id,))
        self.notifications_map = {}
        for notif_id, notif_type, metric, threshold, url_nick, active in cursor.fetchall():
            label = f"{url_nick}: {notif_type} - {metric or 'N/A'} - {threshold or 'N/A'}"
            if not active:
                label += " [DISABLED]"
            self.notification_dropdown.addItem(label, notif_id)
            self.notifications_map[label] = notif_id
        conn.close()

    def remove_notification(self):
        notif_id = self.notification_dropdown.currentData()
        if notif_id is None:
            QMessageBox.warning(self, "Selection Required", "Please select a notification to remove.")
            return

        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM notifications WHERE id = %s", (notif_id,))
        conn.commit()
        conn.close()

        QMessageBox.information(self, "Deleted", "Notification removed.")
        self.load_notifications()  # Refresh list

    def disable_notification(self):
        notif_id = self.notification_dropdown.currentData()
        if notif_id is None:
            QMessageBox.warning(self, "Selection Required", "Please select a notification to disable.")
            return
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET active = FALSE WHERE id = %s", (notif_id,))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Disabled", "Notification disabled.")
        self.load_notifications()

    def enable_notification(self):
        notif_id = self.notification_dropdown.currentData()
        if notif_id is None:
            QMessageBox.warning(self, "Selection Required", "Please select a notification to enable.")
            return
        conn = get_db_conn()
        cursor = conn.cursor()
        cursor.execute("UPDATE notifications SET active = TRUE WHERE id = %s", (notif_id,))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Enabled", "Notification enabled.")
        self.load_notifications()
