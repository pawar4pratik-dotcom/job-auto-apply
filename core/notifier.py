import os
import urllib.request
import urllib.parse
import smtplib
from email.mime.text import MIMEText
import importlib
import config.profile
import config.secrets

_alert_buffer = []
_buffering_enabled = False

def enable_buffering():
    global _alert_buffer, _buffering_enabled
    _alert_buffer = []
    _buffering_enabled = True
    print("[NOTIFIER] Session buffering enabled. Alerts will be compiled into a single report.")

def disable_buffering():
    global _buffering_enabled
    _buffering_enabled = False

def send_session_report() -> None:
    global _alert_buffer, _buffering_enabled
    _buffering_enabled = False  # Temporarily disable to bypass buffering on send
    
    if not _alert_buffer:
        print("[NOTIFIER] No alerts buffered during this session.")
        return
        
    import datetime
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    subject = f"Job Bot Session Report - {now_str}"
    
    body_parts = [
        "🤖 JOB HUNT BOT - SESSION SUMMARY REPORT",
        f"Generated: {now_str}",
        f"Total Alerts: {len(_alert_buffer)}",
        "=" * 50,
        ""
    ]
    for i, msg in enumerate(_alert_buffer, 1):
        body_parts.append(f"[{i}] {msg.strip()}")
        body_parts.append("-" * 50)
        body_parts.append("")
        
    report_body = "\n".join(body_parts)
    send_alert(subject, report_body)
    _alert_buffer = []

def send_telegram_alert(message: str) -> bool:
    """Send a Telegram notification using urllib."""
    try:
        importlib.reload(config.profile)
        importlib.reload(config.secrets)
        token = getattr(config.profile, "TELEGRAM_BOT_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", "")
        chat_id = getattr(config.profile, "TELEGRAM_CHAT_ID", "") or os.getenv("TELEGRAM_CHAT_ID", "")
        
        if not token or not chat_id:
            return False

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception as e:
        print(f"[NOTIFIER][WARN] Telegram alert failed: {e}")
        return False

def send_email_alert(subject: str, message: str) -> bool:
    """Send an email alert via Gmail SMTP using IMAP credentials."""
    try:
        importlib.reload(config.profile)
        importlib.reload(config.secrets)
        email = getattr(config.profile, "IMAP_EMAIL", "") or os.getenv("IMAP_EMAIL", "")
        password = getattr(config.profile, "IMAP_PASSWORD", "") or os.getenv("IMAP_PASSWORD", "")
        
        if not email or not password:
            return False

        # Build email message
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = email
        msg["To"] = email  # Send to self

        # Connect to Gmail SMTP
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(email, password)
        server.sendmail(email, [email], msg.as_string())
        server.quit()
        return True
    except Exception as e:
        print(f"[NOTIFIER][WARN] Email alert failed: {e}")
        return False

def send_alert(subject: str, message: str) -> None:
    """Sends notifications to all enabled channels in parallel thread."""
    global _alert_buffer, _buffering_enabled
    if _buffering_enabled:
        _alert_buffer.append(f"{subject}\n{message}")
        print(f"[NOTIFIER] Buffered alert: {subject}")
        return

    def _task():
        try:
            importlib.reload(config.profile)
            channels = getattr(config.profile, "NOTIFICATION_CHANNELS", ["email"])
            
            # Send Telegram if enabled
            if "telegram" in channels:
                success = send_telegram_alert(message)
                if success:
                    print("[NOTIFIER] Telegram alert sent successfully.")
            
            # Send Email if enabled
            if "email" in channels:
                success = send_email_alert(subject, message)
                if success:
                    print("[NOTIFIER] Email alert sent successfully.")
        except Exception as e:
            print(f"[NOTIFIER][ERROR] Failed to execute send_alert task: {e}")

    import threading
    threading.Thread(target=_task, daemon=True).start()

