import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import EMAIL_REPORT

sender = EMAIL_REPORT["sender"]
username = EMAIL_REPORT.get("username", sender)
password = EMAIL_REPORT["password"]
receiver = EMAIL_REPORT["receiver"]
if isinstance(receiver, str):
    receiver = [receiver]

msg = MIMEMultipart("alternative")
msg["Subject"] = "EKYC Email Test"
msg["From"]    = sender
msg["To"]      = ", ".join(receiver)
msg.attach(MIMEText("<h2>Email is working!</h2>", "html"))

try:
    with smtplib.SMTP_SSL(EMAIL_REPORT["smtp_server"], EMAIL_REPORT["smtp_port"]) as server:
        server.login(username, password)
        server.sendmail(sender, receiver, msg.as_string())
    print("✅ Email sent successfully!")
except Exception as e:
    print(f"❌ Email failed: {e}")
