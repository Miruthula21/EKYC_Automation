import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sender   = "miruthulak21@gmail.com"
password = "jbor rqbh eniq pkpw"   # Replace with your new App Password
receiver = ["miruthulak21@gmail.com", "elamukil@navia.co.in"]

msg = MIMEMultipart("alternative")
msg["Subject"] = "EKYC Email Test"
msg["From"]    = sender
msg["To"]      = ", ".join(receiver)
msg.attach(MIMEText("<h2>Email is working!</h2>", "html"))

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, receiver, msg.as_string())
    print("✅ Email sent successfully!")
except Exception as e:
    print(f"❌ Email failed: {e}")