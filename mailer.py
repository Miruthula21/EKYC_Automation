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
from teams_reporter import send_teams_report


def _html_escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_report(status: str, video_path: str, log_lines: list, step_results: list, duration: str = ""):
    receivers = EMAIL_REPORT["receiver"]
    if isinstance(receivers, str):
        receivers = [receivers]

    color = "#16a34a" if status == "PASS" else "#dc2626"
    now = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
    subject = f"E-KYC Automation Report - {status} | {now}"
    total_count = len(step_results)
    pass_count = sum(1 for step in step_results if step.get("status") == "PASS")
    fail_count = sum(1 for step in step_results if step.get("status") != "PASS")
    display_duration = duration or "0m 0s"

    step_rows = ""
    for step in step_results:
        passed = step["status"] == "PASS"
        s_icon = "PASS" if passed else "FAIL"
        s_color = "#dcfce7" if passed else "#fee2e2"
        testcase_id = (
            step.get("Test Case ID")
            or step.get("testcase_id")
            or step.get("case_id")
            or step.get("id")
            or step.get("step_id")
            or ""
        )
        step_rows += f"""
        <tr style="background:{s_color}">
            <td style="padding:10px;border:1px solid #d1d5db">{_html_escape(testcase_id)}</td>
            <td style="padding:10px;border:1px solid #d1d5db">{_html_escape(step['step'])}</td>
            <td style="padding:10px;border:1px solid #d1d5db;font-weight:700;color:{color}">{s_icon}</td>
            <td style="padding:10px;border:1px solid #d1d5db">{_html_escape(step.get('step',''))}</td>
            <td style="padding:10px;border:1px solid #d1d5db">{_html_escape(step.get('note',''))}</td>
        </tr>"""

    safe_video_path = _html_escape(video_path) if video_path else ""
    html = f"""
    <html>
    <body style="margin:0;background:#f4f6f8;font-family:Arial,sans-serif;color:#111827">
        <div style="max-width:1080px;margin:0 auto;padding:20px">
            <div style="background:#ffffff;border:1px solid #e5e7eb">
                <div style="background:#1f3f68;color:#ffffff;padding:22px 24px">
                    <div style="font-size:22px;font-weight:700">E-KYC Automation Report</div>
                    <div style="font-size:13px;margin-top:6px">Generated: {now} | Duration: {_html_escape(display_duration)}</div>
                </div>
                <div style="padding:18px 24px 24px">
                    <div style="font-size:14px;font-weight:700;margin-bottom:14px">
                        Code Review: PASS &nbsp;|&nbsp; Test Execution:
                        <span style="background:{'#dcfce7' if status == 'PASS' else '#fee2e2'};color:{color};padding:7px 18px;border-radius:5px">{status}</span>
                    </div>
                    <div style="font-size:14px;font-weight:700;margin-bottom:14px">
                        Total Testcases: {total_count} &nbsp;|&nbsp; Pass: {pass_count} &nbsp;|&nbsp; Fail: {fail_count}
                    </div>
                    <table style="width:100%;border-collapse:collapse;font-size:13px">
                        <thead>
                            <tr style="background:#344153;color:#ffffff;text-align:left">
                                <th style="padding:10px;border:1px solid #4b5563">Test Case ID</th>
                                <th style="padding:10px;border:1px solid #4b5563">Step</th>
                                <th style="padding:10px;border:1px solid #4b5563">Status</th>
                                <th style="padding:10px;border:1px solid #4b5563">Name</th>
                                <th style="padding:10px;border:1px solid #4b5563">Reason</th>
                            </tr>
                        </thead>
                        <tbody>{step_rows}</tbody>
                    </table>
                    <div style="font-size:12px;color:#4b5563;margin-top:14px">
                        Video: {"Attached" if video_path else "No video recording found"}
                        {f"<br>Video File: {safe_video_path}" if video_path else ""}
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
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

            smtp_username = EMAIL_REPORT.get("username", EMAIL_REPORT["sender"])
            server.login(smtp_username, EMAIL_REPORT["password"])
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
            send_teams_report(
                title=subject,
                status=status,
                html_body=html,
                video_path=video_path,
                step_results=step_results,
            )
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
                send_teams_report(
                    title=subject,
                    status=status,
                    html_body=html,
                    video_path=video_path,
                    step_results=step_results,
                )
                return
            except Exception as exc:
                last_error = exc
                if attempt == 1:
                    print(f"[Mailer] Send without video failed, retrying once: {exc}")
                    time.sleep(3)

    raise RuntimeError(f"Failed to send email: {last_error}")
