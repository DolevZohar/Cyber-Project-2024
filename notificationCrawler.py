import sqlite3
from config import DB_PATH, METRICS_PATH
from datetime import datetime
from emailUtils import send_notification_email

def check_for_notifications():
    conn_metrics = sqlite3.connect(METRICS_PATH)
    cursor_metrics = conn_metrics.cursor()

    conn_urls = sqlite3.connect(DB_PATH)
    cursor_urls = conn_urls.cursor()

    cursor_urls.execute("SELECT id, user_id, url_id, metric, type, threshold, last_value, email FROM notifications")
    notifications = cursor_urls.fetchall()

    for notif in notifications:
        notif_id, user_id, url_id, metric, notif_type, threshold, last_value, email = notif

        cursor_urls.execute("SELECT url FROM urls WHERE id = ?", (url_id,))
        result = cursor_urls.fetchone()
        if not result:
            continue

        url = result[0]
        cursor_metrics.execute("SELECT * FROM metrics WHERE url = ? ORDER BY timestamp DESC LIMIT 1", (url,))
        row = cursor_metrics.fetchone()
        if not row:
            continue

        column_names = [description[0] for description in cursor_metrics.description]
        metrics = dict(zip(column_names, row))
        triggered = False

        if notif_type == "hard_cap" and metric in metrics and metrics[metric] is not None:
            if metrics[metric] > threshold:
                triggered = True
        elif notif_type == "percent_cap" and metric in metrics and metrics[metric] is not None and last_value:
            try:
                percent_change = ((metrics[metric] - last_value) / last_value) * 100
                if percent_change >= threshold:
                    triggered = True
            except ZeroDivisionError:
                continue
        elif notif_type == "on_down":
            if metrics.get("is_up") == 0:
                triggered = True
        elif notif_type == "on_broken_link":
            if metrics.get("broken_links"):
                triggered = True

        if triggered:
            send_notification_email(
                to_email=email,
                url=url,
                notif_type=notif_type,
                metric=metric,
                value=metrics.get(metric),
                threshold=threshold
            )

        # update last value for percent check
        if notif_type == "percent_cap" and metric in metrics and metrics[metric] is not None:
            cursor_urls.execute("UPDATE notifications SET last_value = ? WHERE id = ?", (metrics[metric], notif_id))

    conn_urls.commit()
    conn_metrics.close()
    conn_urls.close()

if __name__ == "__main__":
    check_for_notifications()
