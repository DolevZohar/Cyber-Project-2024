import psycopg2
from config import get_db_conn
from datetime import datetime, timedelta
from emailUtils import send_notification_email
import time

def check_for_notifications():
    conn_metrics = get_db_conn()
    cursor_metrics = conn_metrics.cursor()

    conn_urls = get_db_conn()
    cursor_urls = conn_urls.cursor()

    now = now = datetime.now()
    cutoff = now - timedelta(minutes=15)

    cursor_urls.execute("""
        SELECT id, user_id, url_id, metric, type, threshold, last_value, email, last_notified 
        FROM notifications
        WHERE active = TRUE
    """)

    notifications = cursor_urls.fetchall()

    for notif in notifications:
        notif_id, user_id, url_id, metric, notif_type, threshold, last_value, email, last_notified = notif

        if last_notified and (now - last_notified).total_seconds() < 900:
            continue  # Skip if notified within the last 15 minutes

        cursor_urls.execute("SELECT url FROM urls WHERE id = %s", (url_id,))
        result = cursor_urls.fetchone()
        if not result:
            continue

        url = result[0]

        # Recent metrics
        cursor_metrics.execute("""
            SELECT * FROM metrics 
            WHERE url = %s AND timestamp >= %s 
            ORDER BY timestamp DESC
        """, (url, cutoff))
        recent_rows = cursor_metrics.fetchall()
        if not recent_rows:
            continue

        column_names = [desc[0] for desc in cursor_metrics.description]
        metrics_list = [dict(zip(column_names, row)) for row in recent_rows]
        latest_metrics = metrics_list[0]
        triggered = False

        if notif_type == "hard_cap" and metric in latest_metrics and latest_metrics[metric] is not None:
            if latest_metrics[metric] > threshold:
                triggered = True

        elif notif_type == "percent_cap" and metric in latest_metrics and latest_metrics[metric] is not None:
            # Calculate weekly average
            week_ago = week_ago = datetime.now() - timedelta(days=7)
            cursor_metrics.execute("""
                SELECT %s FROM metrics WHERE url = %s AND timestamp >= %s
            """ % (metric, "%s", "%s"), (url, week_ago))
            values = [row[0] for row in cursor_metrics.fetchall() if row[0] is not None]

            if values:
                weekly_avg = sum(values) / len(values)
                try:
                    percent_change = ((latest_metrics[metric] - weekly_avg) / weekly_avg) * 100
                    if percent_change >= threshold:
                        triggered = True
                except ZeroDivisionError:
                    continue

        elif notif_type == "on_down" and latest_metrics.get("is_up") == 0:
            triggered = True

        elif notif_type == "on_broken_link" and latest_metrics.get("broken_links"):
            triggered = True

        if triggered:
            send_notification_email(
                to_email=email,
                url=url,
                notif_type=notif_type,
                metric=metric,
                value=latest_metrics.get(metric),
                threshold=threshold
            )

            # Update last_notified time
            cursor_urls.execute ("UPDATE notifications SET last_notified = %s WHERE id = %s", (now, notif_id))

        # Always update last_value for percent notifications
        if notif_type == "percent_cap" and metric in latest_metrics and latest_metrics[metric] is not None:
            cursor_urls.execute("UPDATE notifications SET last_value = %s WHERE id = %s", (latest_metrics[metric], notif_id))

    conn_urls.commit()
    conn_metrics.close()
    conn_urls.close()

if __name__ == "__main__":
    while True:
        check_for_notifications()
        time.sleep(60)  # check every 60 seconds
