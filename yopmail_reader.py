# ============================================================
#  yopmail_reader.py — Reads OTP from YOPmail inbox
# ============================================================
import re
import time

YEAR_FILTER = {"2026", "2025", "2024", "2023", "2022"}


def get_otp_from_yopmail_new_tab(context, yopmail_username, max_wait=60, digits=None):
    """
    Opens yopmail, logs in, clicks the latest email, and extracts OTP.

    Args:
        context          : Playwright BrowserContext
        yopmail_username : full email (xxx@yopmail.com) or just username
        max_wait         : max seconds to wait (default 60)
        digits           : expected OTP digit length — 4 or 6
                           if None, accepts any 4–8 digit number
    """
    username_only = yopmail_username.replace("@yopmail.com", "").strip()

    yopmail_page = context.new_page()

    # ── Step 1: Open yopmail and log in ──
    try:
        print(f"[YOPmail] Navigating to inbox for: {username_only}")
        yopmail_page.goto("https://yopmail.com/en/wm", wait_until="domcontentloaded", timeout=30000)
        yopmail_page.wait_for_timeout(2000)

        login_field = yopmail_page.locator("input[name='login'], #login, .ycptinput").first
        login_field.wait_for(state="visible", timeout=10000)
        login_field.fill(username_only)
        yopmail_page.keyboard.press("Enter")
        yopmail_page.wait_for_timeout(3000)
        print(f"[YOPmail] Logged in as: {username_only}")

    except Exception as e:
        print(f"[YOPmail] Login failed: {e}")
        yopmail_page.close()
        return None

    otp = None
    attempts = 0
    max_attempts = max(max_wait // 5, 3)

    while attempts < max_attempts:
        try:
            # ── Step 2: Refresh inbox ──
            try:
                refresh_btn = yopmail_page.locator("button#refresh").first
                refresh_btn.wait_for(state="visible", timeout=3000)
                refresh_btn.click()
                print("[YOPmail] Inbox refreshed")
                yopmail_page.wait_for_timeout(2000)
            except Exception:
                pass  # refresh failure is non-fatal

            # ── Step 3: Click latest email ──
            inbox_frame = yopmail_page.frame_locator("iframe#ifinbox")
            latest = inbox_frame.locator(".m, .lm").first
            try:
                latest.wait_for(state="visible", timeout=5000)
                latest.click()
                print("[YOPmail] Latest email clicked")
                yopmail_page.wait_for_timeout(2000)
            except Exception as ce:
                print(f"[YOPmail] No email visible yet: {ce}")
                attempts += 1
                print(f"[YOPmail] Waiting for email... ({attempts * 5}s / {max_wait}s)")
                time.sleep(5)
                continue

            # ── Step 4: Read email body ──
            mail_frame = yopmail_page.frame_locator("iframe#ifmail")
            body_text = ""

            try:
                mail_frame.locator("body").wait_for(timeout=8000)
                body_text = mail_frame.locator("body").inner_text(timeout=5000)
                print(f"[YOPmail] Email preview: {body_text[:250]}")
            except Exception:
                try:
                    body_text = mail_frame.locator("body").inner_html(timeout=5000)
                    print(f"[YOPmail] Email HTML preview: {body_text[:250]}")
                except Exception as he:
                    print(f"[YOPmail] Could not read email body: {he}")

            if not body_text.strip():
                print("[YOPmail] Empty email body — retrying...")
                attempts += 1
                time.sleep(5)
                continue

            # ── Step 5: Extract OTP ──
            if digits:
                # Exact digit-length match first
                pattern = rf"\b(\d{{{digits}}})\b"
                matches = re.findall(pattern, body_text)
                print(f"[YOPmail] {digits}-digit candidates: {matches}")
                filtered = [m for m in matches if m not in YEAR_FILTER]
            else:
                # Accept any 4–8 digit number
                matches = re.findall(r"\b(\d{4,8})\b", body_text)
                print(f"[YOPmail] OTP candidates: {matches}")
                filtered = [m for m in matches if m not in YEAR_FILTER]

            if filtered:
                otp = filtered[-1]
                print(f"[YOPmail] ✅ OTP found: {otp}")
                break

            # Fallback: try 4–8 range if exact match found nothing
            if digits and not filtered:
                fallback = re.findall(r"\b(\d{4,8})\b", body_text)
                fallback_filtered = [m for m in fallback if m not in YEAR_FILTER]
                if fallback_filtered:
                    otp = fallback_filtered[-1]
                    print(f"[YOPmail] ✅ OTP found (fallback range): {otp}")
                    break

            print(f"[YOPmail] No valid OTP found yet — retrying...")

        except Exception as ex:
            print(f"[YOPmail] Attempt {attempts + 1} error: {ex}")

        attempts += 1
        print(f"[YOPmail] Waiting for email... ({attempts * 5}s / {max_wait}s)")
        time.sleep(5)

    yopmail_page.close()
    print("[YOPmail] Tab closed")

    if not otp:
        print(f"[YOPmail] ❌ OTP not found within {max_wait}s")

    return otp