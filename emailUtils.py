import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# Gmail-specific configuration
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

def send_notification_email(to_email, url, notif_type, metric=None, value=None, threshold=None):
    if not SENDER_EMAIL or not SENDER_PASSWORD:
        print("ERROR: Missing SENDER_EMAIL or SENDER_PASSWORD environment variables.")
        return False

    if not to_email:
        print("ERROR: No recipient email specified.")
        return False

    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = f"[ALERT] {notif_type.upper()} triggered for {url}"

    body = f"""
Hello,

This is an automated notification from the URL Monitoring System.

Alert Type: {notif_type}
URL: {url}
"""

    if notif_type in ("hard_cap", "percent_cap") and metric is not None:
        body += f"""
Metric: {metric}
Value: {value}
Threshold: {threshold}
"""

    if notif_type == "on_down":
        body += "\nThe site appears to be DOWN.\n"
    elif notif_type == "on_broken_link":
        body += "\nThe page contains broken link(s).\n"

    body += "\nThis message was generated automatically by the system."

    msg.attach(MIMEText(body, 'plain'))

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        server.quit()
        print(f"[EMAIL SENT] to {to_email} for {notif_type} alert on {url}")
        return True
    except smtplib.SMTPAuthenticationError:
        print("[SMTP ERROR] Authentication failed. Use an App Password if using Gmail with 2FA.")
    except Exception as e:
        print(f"[SMTP ERROR] {e}")

    return False
