import sqlite3
from PySide6.QtWidgets import (
    QDialog, QLabel, QVBoxLayout, QComboBox, QLineEdit, QPushButton, QMessageBox
)
from config import DB_PATH

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
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT u.url_id, u.url_nick FROM user_urls u
            JOIN urls l ON u.url_id = l.id
            WHERE u.user_id = ?
        """, (self.user_id,))
        self.url_map = {}
        for url_id, nick in cursor.fetchall():
            self.url_dropdown.addItem(nick, url_id)
            self.url_map[nick] = url_id
        conn.close()

    def load_user_email(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT email FROM users WHERE id = ?", (self.user_id,))
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

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                url_id INTEGER,
                metric TEXT,
                type TEXT CHECK(type IN ('hard_cap', 'percent_cap', 'on_down', 'on_broken_link')),
                threshold REAL,
                last_value REAL,
                email TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id),
                FOREIGN KEY(url_id) REFERENCES urls(id)
            )
        ''')
        cursor.execute('''
            INSERT INTO notifications (user_id, url_id, metric, type, threshold, email)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (self.user_id, url_id, metric, notif_type, threshold, email))
        cursor.execute("UPDATE users SET email = ? WHERE id = ?", (email, self.user_id))
        conn.commit()
        conn.close()
        QMessageBox.information(self, "Saved", "Notification preference saved.")
        self.accept()
