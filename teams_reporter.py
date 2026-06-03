import datetime
import json
import os
import re
import urllib.error
import urllib.request

DEFAULT_WEBHOOK_URL = "https://defaultb5be2d2cde3a4b3680d7e5445c6627.3b.environment.api.powerplatform.com:443/powerautomate/automations/direct/workflows/33cc75b6bb2f4f7ead2c738312a3a30c/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=yIByMt1vgl_cLYJ6y6SZQz5f513zKO-pCtjlASjr9Zw"

try:
    from config import TEAMS_REPORT
except Exception:
    TEAMS_REPORT = {}


def _configured_webhook_url():
    webhook_url = os.environ.get("TEAMS_WEBHOOK_URL", "").strip()
    if webhook_url:
        return webhook_url
    if isinstance(TEAMS_REPORT, dict):
        webhook_url = str(TEAMS_REPORT.get("webhook_url", "")).strip()
        if webhook_url:
            return webhook_url
    return DEFAULT_WEBHOOK_URL


def _teams_enabled():
    disabled = os.environ.get("TEAMS_REPORT_ENABLED", "").strip().lower()
    if disabled in {"0", "false", "no", "off"}:
        return False
    return bool(_configured_webhook_url())


def _html_to_text(html_body):
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", html_body or "", flags=re.IGNORECASE)
    text = re.sub(r"</\s*(p|tr|h[1-6]|div|table)\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s+", "\n", text)
    return text.strip()


def _summary_from_steps(step_results):
    if not step_results:
        return {}

    def step_status(step):
        return str(step.get("status") or step.get("Status") or "").upper()

    not_automated = sum(1 for step in step_results if step_status(step) == "NOT_AUTOMATED")
    return {
        "total_tests": str(len(step_results)),
        "passed": str(sum(1 for step in step_results if step_status(step) == "PASS")),
        "failed": str(sum(1 for step in step_results if step_status(step) == "FAIL")),
        "not_automated": str(not_automated),
    }


def _summary_from_html(html_body):
    patterns = [
        r"Total:\s*</b>\s*(\d+)\s*\|\s*<b>Pass:\s*</b>\s*(\d+)\s*\|\s*<b>Fail:\s*</b>\s*(\d+)\s*\|\s*<b>Not Automated:\s*</b>\s*(\d+)",
        r"Total Tests?\s*:?\s*(\d+).*?Pass(?:ed)?\s*:?\s*(\d+).*?Fail(?:ed)?\s*:?\s*(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, html_body or "", flags=re.IGNORECASE | re.DOTALL)
        if match:
            groups = match.groups()
            return {
                "total_tests": groups[0],
                "passed": groups[1],
                "failed": groups[2],
                "not_automated": groups[3] if len(groups) > 3 else "",
            }
    return {}


def _project_name(title, flow_details):
    if flow_details and flow_details.get("report_name"):
        return str(flow_details["report_name"])
    title = str(title or "Automation Report")
    title = re.sub(r"\s*[-|]\s*(PASS|FAIL|ERROR).*$", "", title, flags=re.IGNORECASE)
    title = title.replace("Report", "Report").strip()
    return title or "Automation Report"


def send_teams_report(
    title,
    status,
    html_body="",
    report_path="",
    video_path="",
    step_results=None,
    duration="",
    flow_details=None,
):
    if not _teams_enabled():
        print("[Teams] Teams report sharing is disabled")
        return False

    webhook_url = _configured_webhook_url()
    if not webhook_url:
        print("[Teams] Teams webhook URL is not configured")
        return False

    status_text = str(status or "").upper()
    report_name = _project_name(title, flow_details or {})
    card_title = f"{report_name} - {status_text}"
    run_date = datetime.datetime.now().strftime("%d %b %Y %I:%M %p")
    summary = _summary_from_html(html_body) or _summary_from_steps(step_results)
    flow_details = flow_details or {}

    facts = [
        {"title": "Date", "value": run_date},
        {"title": "Duration", "value": str(duration or "")},
        {"title": "Status", "value": status_text},
        {"title": "Last Passed Step", "value": str(flow_details.get("last_passed_stage", ""))},
        {"title": "Failed/Stopped Step", "value": str(flow_details.get("stopped_stage", ""))},
        {"title": "Passed", "value": str(summary.get("passed", ""))},
        {"title": "Failed", "value": str(summary.get("failed", ""))},
        {"title": "Not Automated", "value": str(summary.get("not_automated", ""))},
        {"title": "Total Tests", "value": str(summary.get("total_tests", ""))},
        {"title": "Code Review", "value": str(flow_details.get("code_review", "PASS"))},
    ]

    adaptive_card = {
        "type": "AdaptiveCard",
        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
        "version": "1.4",
        "body": [
            {
                "type": "TextBlock",
                "text": card_title,
                "weight": "Bolder",
                "size": "Large",
                "color": "Good" if status_text == "PASS" else "Attention",
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
        ],
    }
    payload = {
        "type": "message",
        "title": card_title,
        "report_title": card_title,
        "report_name": report_name,
        "status": status_text,
        "date": run_date,
        "duration": str(duration or ""),
        "passed": str(summary.get("passed", "")),
        "failed": str(summary.get("failed", "")),
        "not_automated": str(summary.get("not_automated", "")),
        "total_tests": str(summary.get("total_tests", "")),
        "code_review": str(flow_details.get("code_review", "PASS")),
        "last_passed_stage": str(flow_details.get("last_passed_stage", "")),
        "stopped_stage": str(flow_details.get("stopped_stage", "")),
        "failed_step": str(flow_details.get("stopped_stage", "")),
        "stop_reason": str(flow_details.get("stop_reason", "")),
        "report_path": str(report_path or ""),
        "video_path": str(video_path or ""),
        "text_summary": _html_to_text(html_body)[:1500],
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": adaptive_card,
            }
        ],
    }

    request = urllib.request.Request(
        webhook_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status >= 400:
                raise RuntimeError(f"Teams returned HTTP {response.status}")
        print("[Teams] Report shared successfully")
        return True
    except (urllib.error.URLError, RuntimeError) as exc:
        print(f"[Teams] Report sharing failed: {exc}")
        return False
