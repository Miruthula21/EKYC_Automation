# ============================================================
#  scheduler.py — Runs E-KYC test on a schedule
#  Run this file and leave it running in the background
# ============================================================

import schedule
import time
import datetime
from config import SCHEDULE_TIME
from test_ekyc import run_ekyc_test


def job():
    now = datetime.datetime.now().strftime("%d %b %Y %I:%M %p")
    print(f"\n{'='*50}")
    print(f"  Scheduled Run Triggered at {now}")
    print(f"{'='*50}\n")
    try:
        result = run_ekyc_test()
        print(f"\n  Run completed: {result}")
    except Exception as e:
        print(f"  Scheduler error: {e}")


# Runs every day at the time set in config.py
schedule.every().day.at(SCHEDULE_TIME).do(job)

print(f"✅ Scheduler started.")
print(f"   Next run scheduled at: {SCHEDULE_TIME} daily")
print(f"   Press Ctrl+C to stop.\n")

while True:
    schedule.run_pending()
    time.sleep(30)