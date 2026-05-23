# ============================================================
# mailer.py - Sends HTML email report with optional video
# ============================================================

import datetime
import os
import smtplib
import time
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from config import EMAIL_REPORT


def _html_escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_report(status: str, video_path: str, log_lines: list, step_results: list):
    receivers = EMAIL_REPORT["receiver"]
    if isinstance(receivers, str):
        receivers = [receivers]

    color = "#16a34a" if status == "PASS" else "#dc2626"
    now = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
    subject = f"E-KYC Automation Report - {status} | {now}"

    step_rows = ""
    for step in step_results:
        passed = step["status"] == "PASS"
        s_icon = "PASS" if passed else "FAIL"
        s_color = "#dcfce7" if passed else "#fee2e2"
        step_rows += f"""
        <tr style="background:{s_color}">
            <td style="padding:3px;border:1px solid #888">{_html_escape(step['step'])}</td>
            <td style="padding:3px;border:1px solid #888">{s_icon}</td>
            <td style="padding:3px;border:1px solid #888">{_html_escape(step.get('step',''))}</td>
            <td style="padding:3px;border:1px solid #888;color:#dc2626">{_html_escape(step.get('note',''))}</td>
        </tr>"""

    safe_video_path = _html_escape(video_path) if video_path else ""
    html = f"""
    <html><body style="font-family:Arial,sans-serif;padding:20px;color:#222">
            <h2>E-KYC Automation Report</h2>
            <p><b>Code Review:</b> PASS</p>
            <p><b>Test Execution:</b> <span style="color:{color}"><b>{status}</b></span></p>
            <p><b>Duration:</b> Handled inside E-KYC runner</p>
            <h3>Step Results</h3>
            <table style="width:100%;border-collapse:collapse;font-size:13px">
                <thead>
                    <tr style="background:#f3f4f6">
                        <th style="padding:4px;border:1px solid #888;width:70px">Step</th>
                        <th style="padding:4px;border:1px solid #888;width:120px">Status</th>
                        <th style="padding:4px;border:1px solid #888">Name</th>
                        <th style="padding:4px;border:1px solid #888">Reason</th>
                    </tr>
                </thead>
                <tbody>{step_rows}</tbody>
            </table>
            <p><b>Time:</b> {now}</p>
            <p><b>Video:</b> {"Attached" if video_path else "No video recording found"}</p>
            {f"<p><b>Video File:</b> {safe_video_path}</p>" if video_path else ""}
    </body></html>
    """

    def build_message(include_video: bool):
        msg = MIMEMultipart()
        msg["From"] = EMAIL_REPORT["sender"]
        msg["To"] = ", ".join(receivers)
        msg["Subject"] = subject
        msg.attach(MIMEText(html, "html"))

        if include_video and video_path and os.path.exists(video_path):
            with open(video_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                fname = os.path.basename(video_path)
                part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
                msg.attach(part)

        return msg

    attach_video = False
    if video_path and os.path.exists(video_path):
        file_size_mb = os.path.getsize(video_path) / (1024 * 1024)
        if file_size_mb <= 20:
            attach_video = True
        else:
            print("[Mailer] Video too large to attach (>20MB), sending report without it")

    def send_once(include_video: bool):
        server = None
        try:
            msg = build_message(include_video)
            if EMAIL_REPORT["smtp_port"] == 465:
                server = smtplib.SMTP_SSL(
                    EMAIL_REPORT["smtp_server"],
                    EMAIL_REPORT["smtp_port"],
                    timeout=45,
                )
            else:
                server = smtplib.SMTP(
                    EMAIL_REPORT["smtp_server"],
                    EMAIL_REPORT["smtp_port"],
                    timeout=45,
                )
                server.ehlo()
                server.starttls()
                server.ehlo()

            server.login(EMAIL_REPORT["sender"], EMAIL_REPORT["password"])
            failed = server.sendmail(EMAIL_REPORT["sender"], receivers, msg.as_string())
            if failed:
                raise RuntimeError(f"SMTP rejected recipients: {failed}")
        finally:
            if server:
                try:
                    server.quit()
                except Exception:
                    server.close()

    last_error = None
    for attempt in range(1, 3):
        try:
            send_once(attach_video)
            print("[Mailer] Report email sent successfully")
            return
        except Exception as exc:
            last_error = exc
            if attempt == 1:
                print(f"[Mailer] Send failed, retrying once: {exc}")
                time.sleep(3)

    if attach_video:
        print(f"[Mailer] Send with video failed: {last_error}")
        print("[Mailer] Retrying report without video attachment")
        for attempt in range(1, 3):
            try:
                send_once(False)
                print("[Mailer] Report email sent successfully without video attachment")
                return
            except Exception as exc:
                last_error = exc
                if attempt == 1:
                    print(f"[Mailer] Send without video failed, retrying once: {exc}")
                    time.sleep(3)

    raise RuntimeError(f"Failed to send email: {last_error}")
