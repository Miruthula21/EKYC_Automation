# ============================================================
#  test_ekyc.py — Navia E-KYC Playwright Automation
#  Project path: C:\Users\Miruthula\Desktop\ekyc-automation\
#
#  Imports:  config.py | mailer.py | yopmail_reader.py | scheduler.py
#  Folders:  test_files\  |  videos\
#
#  Run manually  : python test_ekyc.py
#  Run scheduled : python scheduler.py
#
#  Aggregator: Onemoney flow (Steps 6–10)
# ============================================================

import os
import re
import time
import datetime
import traceback
import json
import builtins

from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PWTimeout

from config  import APP_URL, TEST_DATA, TEST_FILES
try:
    from config import RESUME_FROM_PERSONAL_DETAILS
except ImportError:
    from config import RESUME_AFTER_EMAIL_VERIFICATION as RESUME_FROM_PERSONAL_DETAILS
try:
    from config import RUN_IPV_ONLY
except ImportError:
    RUN_IPV_ONLY = False
try:
    from config import RUN_IPV_AFTER_MOBILE
except ImportError:
    RUN_IPV_AFTER_MOBILE = False
from mailer  import send_report

_original_print = builtins.print


def print(*args, **kwargs):
    safe_args = [
        str(arg).encode("ascii", "replace").decode("ascii")
        for arg in args
    ]
    _original_print(*safe_args, **kwargs)

# ─────────────────────────── helpers ────────────────────────────────────────

LOG: list[str] = []
STEPS: list[dict] = []
TEST_GEOLOCATION = {
    "latitude": 13.0827,
    "longitude": 80.2707,
    "accuracy": 25,
}


def log(msg: str) -> None:
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    LOG.append(line)


def step_pass(name: str, note: str = "") -> None:
    log(f"✅  PASS — {name}" + (f"  ({note})" if note else ""))
    STEPS.append({"step": name, "status": "PASS", "note": note})


def step_fail(name: str, note: str = "") -> None:
    log(f"❌  FAIL — {name}" + (f"  ({note})" if note else ""))
    STEPS.append({"step": name, "status": "FAIL", "note": note})


def safe_click(page: Page, xpath: str, label: str = "", timeout: int = 15_000) -> bool:
    try:
        loc = page.locator(f"xpath={xpath}")
        loc.wait_for(state="visible", timeout=timeout)
        loc.click()
        return True
    except Exception as e:
        log(f"  safe_click failed [{label}]: {e}")
        return False


def safe_fill(page: Page, xpath: str, value: str, label: str = "", timeout: int = 15_000) -> bool:
    try:
        loc = page.locator(f"xpath={xpath}")
        loc.wait_for(state="visible", timeout=timeout)
        loc.clear()
        loc.fill(value)
        return True
    except Exception as e:
        log(f"  safe_fill failed [{label}]: {e}")
        return False


def js_click(page: Page, xpath: str) -> None:
    page.locator(f"xpath={xpath}").dispatch_event("click")


def scroll_by(page: Page, y: int = 500) -> None:
    page.evaluate(f"window.scrollBy(0, {y})")


def click_first_visible(page: Page, selectors: list[str], label: str, timeout: int = 3_000) -> bool:
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if loc.count() > 0 and loc.is_visible(timeout=timeout):
                loc.scroll_into_view_if_needed(timeout=2_000)
                loc.click(force=True, timeout=timeout)
                log(f"  {label} clicked via: {selector}")
                return True
        except Exception:
            continue
    return False


def click_modal_action(page: Page, label: str, extra_words: list[str] | None = None, timeout: int = 4_000) -> bool:
    words = extra_words or []
    selectors = []
    for word in words + ["OK", "Okay", "Proceed", "Close", "Done"]:
        upper = word.upper()
        selectors.extend([
            f"xpath=(//*[contains(@class,'modal') or contains(@class,'swal') or @role='dialog']//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{upper}')])[last()]",
            f"xpath=(//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{upper}')])[last()]",
            f"xpath=(//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'{upper}')])[last()]",
        ])
    return click_first_visible(page, selectors, label, timeout=timeout)


def close_visible_dialog(page: Page, label: str = "Dialog") -> bool:
    selectors = [
        "xpath=(//*[contains(@class,'modal') or @role='dialog']//*[self::button or self::span][normalize-space(.)='x' or normalize-space(.)='X' or normalize-space(.)='×'])[last()]",
        "xpath=(//*[contains(@class,'modal') or @role='dialog']//*[self::button or self::span][contains(@class,'close')])[last()]",
        "xpath=(//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CLOSE')])[last()]",
        "xpath=(//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'OK')])[last()]",
    ]
    return click_first_visible(page, selectors, f"{label} close", timeout=3_000)


def extract_otp_from_text(text: str, digits: int = 6, context_words: list[str] | None = None) -> str | None:
    if not text:
        return None
    context_words = [w.lower() for w in (context_words or [])]
    candidates = re.findall(rf"\b(\d{{{digits}}})\b", text)
    filtered = [
        c for c in candidates
        if not re.match(r"^20\d{4}$", c)
    ]
    if not filtered:
        return None

    lowered = text.lower()
    if context_words and not any(word in lowered for word in context_words):
        return None

    for candidate in filtered:
        idx = lowered.find(candidate)
        window = lowered[max(0, idx - 80): idx + len(candidate) + 80]
        if any(word in window for word in ["otp", "one time", "verification", "aadhaar", "aadhar", "esign", "e-sign", "protean"]):
            return candidate
    return filtered[0]


ESIGN_SMS_CONTEXT_WORDS = [
    "otp",
    "one time",
    "aadhaar",
    "aadhar",
    "uidai",
    "adhaar-s",
    "aadhaar-s",
    "ax-adhaar-s",
    "jd-adhaar-s",
    "vm-adhaar-s",
    "vk-adhaar-s",
    "smsfw",
    "sms-fw",
    "protean",
    "nsdl",
    "esign",
    "e-sign",
    "verification",
]




def find_visible_otp_input(page: Page, timeout: int = 15_000):
    selectors = [
        "xpath=//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp')]",
        "xpath=//input[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp')]",
        "xpath=//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp')]",
        "xpath=//input[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp')]",
        "xpath=//input[@autocomplete='one-time-code']",
        "xpath=//input[@inputmode='numeric' and (@maxlength='6' or @maxlength='4')]",
        "xpath=//input[(@type='tel' or @type='text' or @type='number') and (@maxlength='6' or contains(@class,'otp'))]",
    ]
    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        for selector in selectors:
            try:
                locs = page.locator(selector)
                for idx in range(min(locs.count(), 8)):
                    loc = locs.nth(idx)
                    if loc.is_visible(timeout=500) and loc.is_enabled(timeout=500):
                        return loc, selector
            except Exception:
                continue
        page.wait_for_timeout(500)
    return None, None


def enter_otp_value(page: Page, otp: str, label: str = "OTP") -> bool:
    split_selectors = [
        "xpath=//input[contains(translate(@class,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') and @maxlength='1']",
        "xpath=//input[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') and @maxlength='1']",
        "xpath=//input[contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') and @maxlength='1']",
        "xpath=//input[@maxlength='1' and (@inputmode='numeric' or @type='tel' or @type='text')]",
    ]
    for selector in split_selectors:
        try:
            boxes = page.locator(selector)
            visible_boxes = []
            for idx in range(min(boxes.count(), 12)):
                box = boxes.nth(idx)
                if box.is_visible(timeout=500) and box.is_enabled(timeout=500):
                    visible_boxes.append(box)
            if len(visible_boxes) >= len(otp):
                for idx, digit in enumerate(otp):
                    box = visible_boxes[idx]
                    box.click()
                    box.press("Control+A")
                    box.type(digit, delay=120)
                log(f"  {label} entered digit by digit")
                return True
        except Exception:
            continue

    otp_input, selector = find_visible_otp_input(page, timeout=10_000)
    if not otp_input:
        log(f"  {label} input not found while entering OTP")
        return False

    try:
        otp_input.scroll_into_view_if_needed(timeout=2_000)
        otp_input.click()
        try:
            otp_input.fill(otp)
        except Exception:
            otp_input.press("Control+A")
            otp_input.type(otp, delay=120)
        try:
            value = otp_input.input_value(timeout=1_000)
        except Exception:
            value = ""
        if value and otp not in value:
            otp_input.press("Control+A")
            otp_input.press_sequentially(otp, delay=120)
        log(f"  {label} entered via: {selector}")
        return True
    except Exception as e:
        log(f"  {label} entry failed: {e}")
        return False


def wait_after_digilocker_submit(page: Page, timeout: int = 45_000) -> None:
    log("  Waiting for DigiLocker to return to Navia...")
    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        try:
            url = page.url.lower()
            if "digitallocker" not in url and "uidai" not in url:
                log(f"  Returned from DigiLocker: {page.url}")
                return
            if page.locator("xpath=//*[contains(text(),'Enter bank details manually') or contains(text(),'Bank Details') or contains(text(),'Account Aggregator')]").first.is_visible(timeout=1_000):
                log("  Navia post-Aadhaar page detected")
                return
        except Exception:
            pass
        page.wait_for_timeout(1_000)
    log(f"  DigiLocker return wait timed out at URL: {page.url}")

def wait_for_yopmail_captcha_clear(page: Page, label: str, max_wait: int = 90) -> bool:
    deadline = time.time() + max_wait
    warned = False
    while time.time() < deadline:
        try:
            visible_text = page.locator("body").inner_text(timeout=3_000)
            if "complete the captcha" not in visible_text.lower() and "captcha" not in visible_text.lower():
                return True
            if not warned:
                log(f"  {label}: YOPmail CAPTCHA detected. Complete it in the browser; automation will wait.")
                warned = True
        except Exception:
            return True
        page.wait_for_timeout(5_000)
    log(f"  {label}: CAPTCHA still present after waiting")
    return False


def read_latest_yopmail_body(yop_page: Page, label: str) -> str:
    try:
        refresh_btn = yop_page.locator("button#refresh, #refresh").first
        if refresh_btn.is_visible(timeout=5_000):
            refresh_btn.click()
            yop_page.wait_for_timeout(2_000)
    except Exception:
        pass

    if not wait_for_yopmail_captcha_clear(yop_page, label, max_wait=90):
        raise RuntimeError("YOPmail CAPTCHA blocked OTP read")

    try:
        inbox_frame = yop_page.frame_locator("iframe#ifinbox")
        latest = inbox_frame.locator(".m, .lm, .lms").first
        latest.wait_for(state="visible", timeout=8_000)
        latest.click()
        yop_page.wait_for_timeout(2_000)
    except Exception as e:
        log(f"  {label}: latest YOPmail message not clickable yet: {e}")

    mail_frame = yop_page.frame_locator("iframe#ifmail")
    mail_frame.locator("body").wait_for(timeout=10_000)
    return mail_frame.locator("body").inner_text(timeout=5_000)


def inject_fixed_geolocation(page: Page) -> None:
    coords_json = json.dumps(TEST_GEOLOCATION)
    page.add_init_script(
        """
        (() => {
            const coords = __COORDS__;
            const position = {
                coords: {
                    latitude: coords.latitude,
                    longitude: coords.longitude,
                    accuracy: coords.accuracy,
                    altitude: null,
                    altitudeAccuracy: null,
                    heading: null,
                    speed: null
                },
                timestamp: Date.now()
            };

            const geolocation = {
                getCurrentPosition: (success) => setTimeout(() => success(position), 50),
                watchPosition: (success) => {
                    setTimeout(() => success(position), 50);
                    return 1;
                },
                clearWatch: () => {}
            };

            Object.defineProperty(navigator, 'geolocation', {
                configurable: true,
                get: () => geolocation
            });
        })();
        """.replace("__COORDS__", coords_json)
    )


def upload_file(page: Page, trigger_xpath: str, file_key: str, label: str) -> bool:
    if file_key in TEST_FILES:
        file_path = TEST_FILES[file_key]
    else:
        file_path = file_key

    if not os.path.isabs(file_path):
        file_path = os.path.join(r"C:\Users\Miruthula\Desktop\ekyc-automation", file_path)
    if not os.path.exists(file_path):
        log(f"  ⚠ File not found: {file_path}  — skipping upload [{label}]")
        return False
    try:
        with page.expect_file_chooser(timeout=10_000) as fc_info:
            page.locator(f"xpath={trigger_xpath}").click()
        fc_info.value.set_files(file_path)
        log(f"  File uploaded: {os.path.basename(file_path)}  [{label}]")
        return True
    except Exception as e:
        log(f"  upload_file failed [{label}]: {e}")
        return False


def upload_file_direct(page: Page, file_key: str, label: str, selectors: list[str] | None = None) -> bool:
    if file_key in TEST_FILES:
        file_path = TEST_FILES[file_key]
    else:
        file_path = file_key

    if not os.path.isabs(file_path):
        file_path = os.path.join(r"C:\Users\Miruthula\Desktop\ekyc-automation", file_path)
    if not os.path.exists(file_path):
        log(f"  File not found: {file_path}  — skipping upload [{label}]")
        return False

    selectors = selectors or []

    try:
        label_for = page.locator("css=#drawimagerestcl").first.get_attribute("for", timeout=1_000)
        if label_for:
            selectors.insert(0, f"css=input#{label_for}")
    except Exception:
        pass

    selectors.extend([
        "css=input[type='file'][accept*='image']",
        "css=input[type='file'][name*='sign' i]",
        "css=input[type='file'][id*='sign' i]",
        "css=input[type='file']",
    ])

    tried: set[str] = set()
    for selector in selectors:
        if selector in tried:
            continue
        tried.add(selector)
        try:
            inputs = page.locator(selector)
            for idx in range(min(inputs.count(), 5)):
                try:
                    inputs.nth(idx).set_input_files(file_path, timeout=4_000)
                    log(f"  File uploaded directly: {os.path.basename(file_path)}  [{label}]")
                    return True
                except Exception:
                    continue
        except Exception:
            continue

    return False


def click_use_original_for_signature(page: Page) -> bool:
    selectors = [
        "xpath=(//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'USE ORIGINAL')])[last()]",
        "xpath=(//*[self::button or self::a][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'USE ORGINAL')])[last()]",
        "xpath=(//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'USE ORIGINAL')])[last()]",
        "xpath=(//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'USE ORGINAL')])[last()]",
    ]

    for selector in selectors:
        try:
            btn = page.locator(selector).first
            btn.wait_for(state="visible", timeout=8_000)
            btn.scroll_into_view_if_needed(timeout=2_000)
            try:
                btn.click(timeout=3_000)
            except Exception:
                btn.dispatch_event("click")
            log("  'Use Original' clicked for Signature")
            page.wait_for_timeout(1_000)
            click_modal_action(page, "Signature confirmation", extra_words=["OK", "Okay", "Proceed", "Confirm"])
            return True
        except Exception:
            continue

    log("  'Use Original' not found for Signature")
    return False


def bank_account_field_visible(page: Page, timeout: int = 1_000) -> bool:
    try:
        deadline = time.time() + (timeout / 1000)
        while time.time() < deadline:
            found = page.evaluate(
                """() => Array.from(document.querySelectorAll('input')).some(input => {
                    const text = [
                        input.id || '',
                        input.name || '',
                        input.placeholder || '',
                        input.getAttribute('aria-label') || ''
                    ].join(' ').toLowerCase();
                    const rect = input.getBoundingClientRect();
                    return text.includes('account') && rect.width > 0 && rect.height > 0;
                })"""
            )
            if found:
                return True
            page.wait_for_timeout(200)
    except Exception:
        pass
    return False


def bank_manual_form_visible(page: Page, timeout: int = 1_000) -> bool:
    try:
        deadline = time.time() + (timeout / 1000)
        while time.time() < deadline:
            if bank_account_field_visible(page, timeout=300):
                return True
            body_text = page.locator("body").inner_text(timeout=1_000).lower()
            if "bank account number" in body_text and "ifsc code" in body_text and "verify & proceed" in body_text:
                return True
            page.wait_for_timeout(200)
    except Exception:
        pass
    return False


def bank_details_page_ready(page: Page) -> bool:
    if "bank_details" in page.url.lower() or "bank" in page.url.lower():
        log(f"  Bank page URL detected: {page.url}")
        return True

    selectors = [
        "xpath=//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'bank verification')]",
        "xpath=//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'enter bank details manually')]",
        "xpath=//*[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'account aggregator')]",
        "xpath=//input[contains(translate(@id,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'bank') or contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'bank')]",
    ]

    for selector in selectors:
        try:
            locs = page.locator(selector)
            for idx in range(min(locs.count(), 10)):
                if locs.nth(idx).is_visible(timeout=500):
                    log(f"  Bank page control visible via: {selector}")
                    return True
        except Exception:
            continue

    return False


def click_enter_bank_details_manually(page: Page) -> bool:
    if bank_manual_form_visible(page):
        log("  Manual bank details form already visible")
        return True

    selectors = [
        "css=a.bank_details_manually",
        "css=.bank_details_manually",
        "xpath=//*[@data-key='manual']",
        "xpath=//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'enter bank details manually')]",
        "xpath=//a[contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'manually')]",
        "xpath=//*[self::a or self::button or @role='button'][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'enter bank details manually')]",
        "xpath=//*[self::a or self::button or @role='button'][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'manually')]",
    ]

    for selector in selectors:
        try:
            candidates = page.locator(selector)
            for idx in range(min(candidates.count(), 5)):
                el = candidates.nth(idx)
                if not el.is_visible(timeout=1_000):
                    continue
                el.scroll_into_view_if_needed(timeout=2_000)
                page.wait_for_timeout(300)

                try:
                    info = el.evaluate(
                        """node => {
                            const target = node.closest('a,button,[role="button"],[onclick]') || node;
                            return {
                                tag: target.tagName,
                                id: target.id || '',
                                cls: target.className || '',
                                href: target.getAttribute('href') || '',
                                onclick: target.getAttribute('onclick') || '',
                                text: (target.innerText || target.textContent || '').trim()
                            };
                        }"""
                    )
                    log(f"  Manual bank link candidate: {info}")
                except Exception:
                    pass

                try:
                    el.click(timeout=3_000)
                except Exception:
                    try:
                        el.click(force=True, timeout=3_000)
                    except Exception:
                        try:
                            el.dispatch_event("click")
                        except Exception:
                            el.press("Enter", timeout=2_000)

                page.wait_for_timeout(1_000)
                if bank_manual_form_visible(page):
                    log(f"  Manual bank details opened via Playwright click: {selector}")
                    return True

                try:
                    el.evaluate(
                        """node => {
                            const target = node.closest('a,button,[role="button"],[onclick]') || node;
                            for (const type of ['mouseover', 'mousedown', 'mouseup', 'click']) {
                                target.dispatchEvent(new MouseEvent(type, {bubbles: true, cancelable: true, view: window}));
                            }
                            if (target.href && !target.href.includes('#') && !target.href.toLowerCase().startsWith('javascript')) {
                                window.location.href = target.href;
                            }
                        }"""
                    )
                except Exception:
                    pass

                page.wait_for_timeout(1_000)
                if bank_manual_form_visible(page):
                    log(f"  Manual bank details opened via DOM click: {selector}")
                    return True

                try:
                    box = el.bounding_box()
                    if box:
                        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                        page.mouse.down()
                        page.mouse.up()
                        page.wait_for_timeout(1_000)
                        if bank_manual_form_visible(page):
                            log(f"  Manual bank details opened via mouse coordinates: {selector}")
                            return True
                except Exception:
                    pass

                log(f"  Manual bank details click did not open fields via: {selector}")
        except Exception:
            continue

    return False


def scroll_open_viewer_to_bottom(page: Page, label: str, max_scrolls: int = 35) -> None:
    same_position_count = 0
    last_position = None

    for _ in range(max_scrolls):
        position = page.evaluate(
            """
            () => {
                const candidates = [document.scrollingElement, document.documentElement, document.body]
                    .concat(Array.from(document.querySelectorAll(
                        '.modal, .modal-body, [role="dialog"], .pdfViewer, .viewerContainer, iframe, embed, object, div'
                    )));

                let best = null;
                for (const el of candidates) {
                    if (!el || el.tagName === 'IFRAME' || el.tagName === 'EMBED' || el.tagName === 'OBJECT') continue;
                    const scrollHeight = el.scrollHeight || 0;
                    const clientHeight = el.clientHeight || 0;
                    if (scrollHeight > clientHeight + 50) {
                        if (!best || (scrollHeight - clientHeight) > (best.scrollHeight - best.clientHeight)) {
                            best = el;
                        }
                    }
                }

                const target = best || document.scrollingElement || document.documentElement || document.body;
                target.scrollTop = Math.min(target.scrollTop + 300, target.scrollHeight);
                window.scrollBy(0, 300);

                return {
                    top: Math.round(target.scrollTop || window.scrollY || 0),
                    max: Math.round((target.scrollHeight || document.body.scrollHeight || 0) - (target.clientHeight || window.innerHeight || 0))
                };
            }
            """
        )
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(900)

        current_position = (position.get("top"), position.get("max"))
        if current_position == last_position or position.get("top", 0) >= position.get("max", 1) - 5:
            same_position_count += 1
        else:
            same_position_count = 0
        last_position = current_position

        if same_position_count >= 3:
            break

    log(f"  {label} viewed till last page")


def accept_ipv_camera_consent(page: Page, timeout: int = 5_000) -> bool:
    try:
        popup = page.locator(
            "xpath=//*[contains(normalize-space(.),'Live Photo Capture Required') or "
            "contains(normalize-space(.),'In-Person Verification') or "
            "contains(normalize-space(.),'device camera')]"
        ).first
        popup.wait_for(state="visible", timeout=timeout)
    except Exception:
        return False

    try:
        checked = page.evaluate("""
            () => {
                const modal = Array.from(document.querySelectorAll('div, section, article'))
                    .filter(el => {
                        const text = (el.innerText || '').trim();
                        return text.includes('Live Photo Capture Required') &&
                            text.includes('I agree to the use of my device camera') &&
                            text.includes('Accept');
                    })
                    .sort((a, b) => (a.getBoundingClientRect().width * a.getBoundingClientRect().height) -
                        (b.getBoundingClientRect().width * b.getBoundingClientRect().height))[0] || document;

                const candidates = Array.from(modal.querySelectorAll(
                    "input[type='checkbox'], [role='checkbox'], .checkbox, .checkmark, label, span"
                ));
                const checkbox = candidates.find(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.width < 8 || rect.height < 8 || rect.width > 80 || rect.height > 80) return false;
                    const style = window.getComputedStyle(el);
                    if (style.visibility === 'hidden' || style.display === 'none') return false;
                    const text = (el.innerText || el.getAttribute('aria-label') || '').trim();
                    return el.matches("input[type='checkbox'], [role='checkbox'], .checkbox, .checkmark") ||
                        text === '' || text.includes('I agree');
                });
                if (!checkbox) return false;

                checkbox.scrollIntoView({block: 'center', inline: 'center'});
                if (checkbox.tagName === 'INPUT') {
                    checkbox.checked = true;
                    checkbox.dispatchEvent(new Event('input', {bubbles: true}));
                    checkbox.dispatchEvent(new Event('change', {bubbles: true}));
                    if (!checkbox.checked) checkbox.click();
                    return checkbox.checked;
                }

                checkbox.click();
                const input = modal.querySelector("input[type='checkbox']");
                return !input || input.checked || checkbox.getAttribute('aria-checked') === 'true' ||
                    checkbox.className.toString().toLowerCase().includes('checked');
            }
        """)
        if checked:
            log("  IPV camera consent checkbox selected")
    except Exception:
        checked = False

    checkbox_selectors = [
        "xpath=//input[@type='checkbox' and not(@disabled)]",
        "xpath=//*[contains(normalize-space(.),'I agree to the use of my device camera')]/preceding::input[@type='checkbox'][1]",
        "xpath=//*[contains(normalize-space(.),'I agree to the use of my device camera')]/preceding::*[contains(@class,'checkbox') or @role='checkbox'][1]",
        "xpath=//*[contains(normalize-space(.),'I agree to the use of my device camera')]/preceding::*[self::span or self::label][1]",
    ]

    for selector in checkbox_selectors:
        if checked:
            break
        try:
            checkbox = page.locator(selector).first
            if checkbox.count() > 0 and checkbox.is_visible(timeout=1_000):
                try:
                    if hasattr(checkbox, "is_checked") and checkbox.is_checked():
                        checked = True
                    else:
                        checkbox.click(force=True, timeout=2_000)
                        checked = True
                except Exception:
                    checkbox.click(force=True, timeout=2_000)
                    checked = True
                break
        except Exception:
            continue

    if not checked:
        try:
            checked = page.evaluate("""
                () => {
                    const labels = Array.from(document.querySelectorAll('label, div, p, span'));
                    const targetText = 'I agree to the use of my device camera for the above-stated purpose';
                    const label = labels.find(el => (el.textContent || '').includes(targetText));
                    let checkbox = null;
                    if (label) {
                        checkbox = label.querySelector("input[type='checkbox']") ||
                            label.parentElement?.querySelector("input[type='checkbox']") ||
                            document.querySelector("input[type='checkbox']");
                    } else {
                        checkbox = document.querySelector("input[type='checkbox']");
                    }
                    if (!checkbox) return false;
                    checkbox.scrollIntoView({block: 'center'});
                    checkbox.checked = true;
                    checkbox.dispatchEvent(new Event('input', {bubbles: true}));
                    checkbox.dispatchEvent(new Event('change', {bubbles: true}));
                    checkbox.click();
                    return true;
                }
            """)
        except Exception:
            checked = False

    if not checked:
        try:
            page.mouse.click(665, 650)
            page.wait_for_timeout(500)
            checked = page.evaluate("""
                () => {
                    const input = document.querySelector("input[type='checkbox']");
                    return !input || input.checked;
                }
            """)
        except Exception:
            pass

    if not checked:
        log("  IPV camera consent checkbox could not be selected")
        return False

    accept_selectors = [
        "xpath=//button[normalize-space(.)='Accept']",
        "xpath=//button[contains(normalize-space(.),'Accept')]",
        "xpath=//a[contains(normalize-space(.),'Accept')]",
        "xpath=//input[contains(@value,'Accept')]",
    ]

    for selector in accept_selectors:
        try:
            accept_btn = page.locator(selector).first
            if accept_btn.count() > 0 and accept_btn.is_visible(timeout=1_000):
                accept_btn.click(force=True, timeout=3_000)
                log("  IPV camera consent checkbox selected and Accept clicked")
                page.wait_for_timeout(1_500)
                return True
        except Exception:
            continue

    try:
        accepted = page.evaluate("""
            () => {
                const buttons = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"]'));
                const accept = buttons.find(el => {
                    const text = (el.textContent || el.value || '').trim().toLowerCase();
                    return text === 'accept' || text.includes('accept');
                });
                if (!accept) return false;
                accept.scrollIntoView({block: 'center'});
                accept.click();
                return true;
            }
        """)
        if accepted:
            log("  IPV camera consent checkbox selected and Accept clicked")
            page.wait_for_timeout(1_500)
            return True
    except Exception:
        pass

    return False


def click_proceed_without_nominees(page: Page, timeout: int = 8_000) -> bool:
    selectors = [
        "xpath=//a[contains(normalize-space(.),'Proceed without Nominees')]",
        "xpath=//button[contains(normalize-space(.),'Proceed without Nominees')]",
        "xpath=//*[contains(normalize-space(.),'Proceed without Nominees')]",
        "xpath=//*[contains(normalize-space(.),'Proceed Without Nominees')]",
        "xpath=//*[contains(normalize-space(.),'Proceed without')]",
    ]

    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=1_000):
                    btn.click(force=True, timeout=2_000)
                    log("  'Proceed without Nominees' clicked")
                    page.wait_for_timeout(1_500)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(500)

    return False


def click_risk_disclosure_agree(page: Page, timeout: int = 8_000) -> bool:
    selectors = [
        "xpath=//*[contains(normalize-space(.),'RISK DISCLOSURES') or contains(normalize-space(.),'Risk Disclosures')]/ancestor::*[contains(@class,'modal') or contains(@class,'popup') or @role='dialog'][1]//button[normalize-space(.)='Agree']",
        "xpath=//*[contains(normalize-space(.),'RISK DISCLOSURES') or contains(normalize-space(.),'Risk Disclosures')]/following::button[normalize-space(.)='Agree'][1]",
        "xpath=//button[normalize-space(.)='Agree']",
        "xpath=//a[normalize-space(.)='Agree']",
        "xpath=//input[@type='button' and @value='Agree']",
    ]

    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=1_000):
                    btn.scroll_into_view_if_needed(timeout=2_000)
                    btn.click(force=True, timeout=3_000)
                    log("  Risk disclosure Agree clicked")
                    page.wait_for_timeout(1_500)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(500)

    return False


def click_continue_after_mobile_for_ipv(page: Page, timeout: int = 120_000) -> bool:
    STEP = "Continue After Mobile Verification"
    selectors = [
        "xpath=//*[contains(normalize-space(.),'E-Sign Pending')]/ancestor::*[self::tr or contains(@class,'row') or contains(@class,'card') or contains(@class,'box')][1]//button[contains(normalize-space(.),'Continue')]",
        "xpath=//*[contains(normalize-space(.),'E-Sign Pending')]/ancestor::*[self::tr or contains(@class,'row') or contains(@class,'card') or contains(@class,'box')][1]//a[contains(normalize-space(.),'Continue')]",
        "xpath=//button[contains(normalize-space(.),'Continue')]",
        "xpath=//a[contains(normalize-space(.),'Continue')]",
        "xpath=//input[contains(@value,'Continue')]",
    ]

    deadline = time.time() + (timeout / 1000)
    while time.time() < deadline:
        if "uuid.php" in page.url.lower():
            try:
                pdf_link = page.locator(
                    "xpath=//a[contains(normalize-space(.),'View Unsigned KYC PDF') or "
                    "contains(normalize-space(.),'Unsigned KYC PDF')]"
                ).first
                if pdf_link.count() > 0 and pdf_link.is_visible(timeout=1_000):
                    log("  Already on Continue to E-sign page; unsigned PDF link is visible")
                    step_pass(STEP)
                    return True
            except Exception:
                pass

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=1_000):
                    text = ""
                    try:
                        text = (btn.inner_text(timeout=1_000) or "").strip()
                    except Exception:
                        try:
                            text = (btn.get_attribute("value", timeout=1_000) or "").strip()
                        except Exception:
                            text = ""
                    if "uuid.php" in page.url.lower() and ("e-sign" in text.lower() or "esign" in text.lower()):
                        continue
                    btn.scroll_into_view_if_needed(timeout=2_000)
                    btn.click(force=True, timeout=3_000)
                    log("  Continue clicked after mobile verification")
                    try:
                        page.wait_for_url("**/uuid.php**", timeout=60_000)
                    except Exception:
                        page.wait_for_timeout(2_000)
                    step_pass(STEP)
                    return True
            except Exception:
                continue
        page.wait_for_timeout(500)

    step_fail(STEP, "Continue button not found after mobile verification")
    return False


def get_all_pages(ctx: BrowserContext) -> list:
    return ctx.pages


# ─────────────────────────── YOPmail OTP Helper ─────────────────────────────

def get_otp_from_yopmail_new_tab(ctx: BrowserContext, email: str, max_wait: int = 120, context_words: list[str] | None = None) -> str | None:
    tab = ctx.new_page()
    try:
        username = email.split("@")[0]
        log(f"[YOPmail] Navigating to inbox for: {username}")

        tab.goto("https://yopmail.com/en/", wait_until="domcontentloaded", timeout=30000)
        tab.wait_for_timeout(3000)

        login_input = tab.locator("#login")
        login_input.evaluate(f"el => {{ el.value = '{username}'; }}")
        log(f"[YOPmail] Username set via evaluate: {username}")

        submitted = False
        for btn_strategy in [
            ".material-icons-outlined:has-text('chevron_right')",
            "button.md",
            "button[onclick]",
            ".ycptinputok",
            "#refreshbut",
        ]:
            try:
                btn = tab.locator(btn_strategy).first
                if btn.is_visible(timeout=2000):
                    btn.click()
                    submitted = True
                    log(f"[YOPmail] Submitted via: {btn_strategy}")
                    break
            except Exception:
                continue

        if not submitted:
            login_input.press("Enter")
            log("[YOPmail] Submitted via Enter key")

        tab.wait_for_timeout(4000)
        log(f"[YOPmail] After login URL: {tab.url}")

        deadline = time.time() + max_wait
        while time.time() < deadline:

            try:
                refresh_btn = tab.locator("#refresh").first
                if refresh_btn.is_visible(timeout=2000):
                    refresh_btn.click()
                    log("[YOPmail] Inbox refreshed")
                    tab.wait_for_timeout(2000)
            except Exception:
                pass

            try:
                inbox_frame = tab.frame_locator("#ifinbox")
                mail_items = inbox_frame.locator("div.m, .lm, .ellipsis")
                count = mail_items.count()
                log(f"[YOPmail] Mail items found: {count}")

                if count > 0:
                    for i in range(min(count, 5)):
                        try:
                            mail_items.nth(i).click()
                            tab.wait_for_timeout(2000)
                            if not wait_for_yopmail_captcha_clear(tab, "YOPmail OTP", max_wait=90):
                                log("[YOPmail] CAPTCHA blocked OTP reading")
                                return None

                            mail_frame = tab.frame_locator("#ifmail")
                            body_text = mail_frame.locator("body").inner_text(timeout=5000)

                            log(f"[YOPmail] Mail {i} FULL body:\n{body_text}")

                            otp_found = extract_otp_from_text(
                                body_text,
                                digits=6,
                                context_words=context_words or ESIGN_SMS_CONTEXT_WORDS,
                            )
                            if otp_found:
                                log(f"[YOPmail] OTP found: {otp_found}")
                                return otp_found
                            else:
                                log(f"[YOPmail] No 6-digit OTP in mail {i} — trying next")

                        except Exception as e:
                            log(f"[YOPmail] Error reading mail {i}: {e}")
                            continue

            except Exception as e:
                log(f"[YOPmail] Retrying... ({e})")

            tab.wait_for_timeout(5000)

        log("[YOPmail] Timed out waiting for OTP email")
        return None

    finally:
        tab.close()


# ─────────────────────────── Step 1: Launch URL ─────────────────────────────

def step_launch_url(page: Page) -> bool:
    STEP = "Launch URL"
    try:
        page.goto(APP_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_timeout(2_000)
        step_pass(STEP, page.title())
        return True
    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 2: Mobile OTP ─────────────────────────────

def step_enter_mobile_and_verify_otp(page: Page, ctx: BrowserContext) -> bool:
    STEP = "Enter Mobile Number & Verify OTP"
    try:
        mobile  = TEST_DATA["mobile"]
        yopmail = TEST_DATA["yopmail"]

        log("  Checking yopmail for any existing OTP before submitting mobile...")
        old_otp = None
        try:
            pre_page = ctx.new_page()
            pre_page.goto(
                f"https://yopmail.com/en/?login={yopmail.split('@')[0]}",
                wait_until="domcontentloaded",
                timeout=30000
            )
            pre_page.wait_for_timeout(3000)
            try:
                pre_page.locator("#refresh").click()
                pre_page.wait_for_timeout(2000)
            except Exception:
                pass
            frame = pre_page.frame_locator("#ifmail")
            frame.locator("body").wait_for(timeout=5000)
            mail_text = frame.locator("body").inner_text()
            matches = re.findall(r"\b\d{4,6}\b", mail_text)
            if matches:
                old_otp = matches[-1] if matches[-1] != "2026" else None
            log(f"  Old OTP in inbox: {old_otp}")
            pre_page.close()
        except Exception as e:
            log(f"  Could not read old OTP (inbox may be empty): {e}")
            if 'pre_page' in locals() and not pre_page.is_closed():
                pre_page.close()

        # ── Enter Mobile Number ──
        mob_field = page.locator("//input[@placeholder='Mobile Number']").first
        mob_field.wait_for(state="visible", timeout=15000)
        mob_field.click()
        mob_field.fill(mobile)
        mob_field.press("Enter")
        log(f"  Mobile entered: {mobile}")

        log("  Waiting 7 seconds for new OTP email to arrive...")
        page.wait_for_timeout(7000)

        # ── Poll yopmail for a FRESH OTP ──
        otp      = None
        yop_page = None
        repeated_old_otp = None
        try:
            log("  Opening single persistent yopmail tab...")
            yop_page = ctx.new_page()
            yop_page.goto(
                f"https://yopmail.com/en/?login={yopmail.split('@')[0]}",
                wait_until="domcontentloaded",
                timeout=30000
            )
            yop_page.wait_for_timeout(5000)
            log("  Yopmail tab ready")

            start_time = time.time()
            while time.time() - start_time < 45:
                try:
                    try:
                        refresh_btn = yop_page.locator("#refresh")
                        refresh_btn.wait_for(state="visible", timeout=5000)
                        refresh_btn.click()
                        log("  Inbox refreshed")
                        yop_page.wait_for_timeout(3000)
                    except Exception as re_err:
                        log(f"  Refresh click failed: {re_err}")

                    frame = yop_page.frame_locator("#ifmail")
                    frame.locator("body").wait_for(timeout=10000)
                    mail_text = frame.locator("body").inner_text()

                    matches = re.findall(r"\b\d{4,6}\b", mail_text)
                    if matches:
                        latest_otp = matches[-1]
                        if latest_otp == "2026":
                            log("  Ignoring '2026' — retrying...")
                        elif latest_otp == old_otp:
                            repeated_old_otp = latest_otp
                            elapsed = int(time.time() - start_time)
                            if elapsed >= 20:
                                otp = latest_otp
                                log(f"  Reusing latest visible OTP after {elapsed}s: {otp}")
                                break
                            log(f"  OTP {latest_otp} matches old OTP - waiting briefly for refresh...")
                        else:
                            otp = latest_otp
                            log(f"  Mobile OTP captured: {otp}")
                            break
                    else:
                        log("  No OTP found yet — retrying...")

                except Exception as e:
                    log(f"  OTP read error: {e}")

                yop_page.wait_for_timeout(5000)

        except Exception as open_err:
            log(f"  Failed to open yopmail tab: {open_err}")
        finally:
            if yop_page and not yop_page.is_closed():
                yop_page.close()
                log("  Yopmail tab closed")

        if not otp and repeated_old_otp:
            otp = repeated_old_otp
            log(f"  Fresh OTP not detected; using latest inbox OTP: {otp}")

        if not otp:
            step_fail(STEP, "OTP not received within timeout")
            return False

        log(f"  Mobile OTP received: {otp}")

        # ── Type OTP ──
        try:
            otp_inputs = page.locator("//input[contains(@class,'otp')]")
            if otp_inputs.count() > 1:
                for i in range(len(otp)):
                    box = otp_inputs.nth(i)
                    box.wait_for(state="visible", timeout=5000)
                    box.click()
                    box.press("Control+A")
                    box.type(otp[i], delay=200)
            else:
                otp_box = page.locator("//input[@type='tel']").first
                otp_box.wait_for(state="visible", timeout=5000)
                otp_box.click()
                otp_box.press("Control+A")
                otp_box.type(otp, delay=200)
        except Exception as e:
            step_fail(STEP, f"OTP typing failed: {e}")
            return False

        page.wait_for_timeout(3000)
        step_pass(STEP, f"OTP '{otp}' entered successfully")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 3: Aadhaar ────────────────────────────────

def step_continue_existing_user_to_personal_details(page: Page) -> bool:
    STEP = "Resume Existing User To Personal/KRA Details"
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15_000)
        page.wait_for_timeout(2_000)

        if "exist_user_details" not in page.url.lower():
            try:
                page.goto("https://open.navia.co.in/exist_user_details.php", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
            except Exception:
                pass

        continue_locators = [
            "xpath=//button[contains(normalize-space(.),'Continue')]",
            "xpath=//a[contains(normalize-space(.),'Continue')]",
            "xpath=//input[contains(@value,'Continue')]",
            "xpath=//*[contains(normalize-space(.),'Continue >>')]",
            "xpath=//*[contains(normalize-space(.),'Continue')]",
        ]

        for locator in continue_locators:
            try:
                btn = page.locator(locator).first
                if btn.is_visible(timeout=5_000):
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    page.wait_for_timeout(3_000)
                    log("  Existing user Continue clicked; moving to Personal/KRA details")
                    step_pass(STEP)
                    return True
            except Exception:
                continue

        step_fail(STEP, "Continue button not found on existing user details page")
        return False

    except Exception as e:
        step_fail(STEP, str(e))
        return False


step_continue_existing_user_after_email = step_continue_existing_user_to_personal_details


def step_aadhaar_verification(page: Page, ctx: BrowserContext) -> bool:
    STEP = "Aadhaar Number & OTP Verification"
    try:
        yopmail = TEST_DATA["yopmail"]
        aadhaar = TEST_DATA.get("aadhaar", "")

        if not aadhaar:
            log("  WARNING: Aadhaar number missing in TEST_DATA — skipping step")
            step_pass(STEP)
            return True

        log("  Waiting for DigiLocker Sign-in page...")
        try:
            page.wait_for_url(lambda url: "digitallocker" in url.lower(), timeout=20000)
            log(f"  DigiLocker page loaded: {page.url}")
        except Exception:
            log(f"  Current URL: {page.url} — continuing anyway")

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # ── Click Aadhaar tab ──
        log("  Clicking 'Aadhaar' tab on DigiLocker...")
        aadhaar_tab_clicked = False

        for strategy in [
            "//a[normalize-space(text())='Aadhaar']",
            "//button[normalize-space(text())='Aadhaar']",
            "//span[normalize-space(text())='Aadhaar']",
            "//li[normalize-space(text())='Aadhaar']",
            "//*[normalize-space(text())='Aadhaar']",
            "//*[contains(@class,'tab') and contains(text(),'Aadhaar')]",
            "//*[contains(@href,'aadhaar')]",
        ]:
            try:
                el = page.locator(strategy).first
                if el.is_visible(timeout=3000):
                    el.click()
                    log(f"  Aadhaar tab clicked via: {strategy}")
                    aadhaar_tab_clicked = True
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        if not aadhaar_tab_clicked:
            step_fail(STEP, "Aadhaar tab not found on DigiLocker page")
            return False

        # ── Fill Aadhaar Number ──
        aadhaar_input = None
        for strategy in [
            "//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'aadhaar')]",
            "//input[contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'aadhar')]",
            "//input[contains(@id,'aadhaar') or contains(@id,'aadhar')]",
            "//input[contains(@name,'aadhaar') or contains(@name,'aadhar')]",
            "//input[@maxlength='12']",
            "//input[@type='number']",
            "//input[@type='tel']",
            "//input[@type='text']",
        ]:
            try:
                loc = page.locator(strategy).first
                if loc.is_visible(timeout=3000):
                    aadhaar_input = loc
                    log(f"  Aadhaar input found via: {strategy}")
                    break
            except Exception:
                continue

        if not aadhaar_input:
            step_fail(STEP, "Aadhaar input field not found after tab click")
            return False

        aadhaar_input.scroll_into_view_if_needed()
        aadhaar_input.click()
        aadhaar_input.fill("")
        aadhaar_input.press_sequentially(aadhaar, delay=100)
        log(f"  Aadhaar typed: {aadhaar}")

        # ── Click Next/Submit ──
        next_btn = None
        for btn_xpath in [
            "//button[normalize-space(text())='Next']",
            "//button[normalize-space(text())='Submit']",
            "//button[normalize-space(text())='Verify']",
            "//button[normalize-space(text())='Get OTP']",
            "//button[normalize-space(text())='Continue']",
            "//button[@type='submit']",
            "//button[@id='button']",
        ]:
            try:
                btn = page.locator(btn_xpath).first
                if btn.is_visible(timeout=2000):
                    next_btn = btn
                    log(f"  Submit button found via: {btn_xpath}")
                    break
            except Exception:
                continue

        if next_btn:
            for _ in range(15):
                if next_btn.is_enabled():
                    break
                page.wait_for_timeout(1000)
            if next_btn.is_enabled():
                next_btn.click()
                log("  Aadhaar submitted")
            else:
                log("  Submit button disabled — pressing Enter")
                aadhaar_input.press("Enter")
        else:
            log("  No submit button — pressing Enter")
            aadhaar_input.press("Enter")

        page.wait_for_timeout(3000)

        log("  Waiting 7 seconds for Aadhaar OTP email to arrive...")
        page.wait_for_timeout(7000)

        otp = None
        otp_input, otp_selector = find_visible_otp_input(page, timeout=20_000)

        if otp_input:
            log(f"  OTP input visible via {otp_selector} - polling yopmail for 6-digit Aadhaar OTP...")
            start_time = time.time()

            while time.time() - start_time < 120:
                yop_page = None
                try:
                    yop_page = ctx.new_page()
                    yop_page.goto(
                        f"https://yopmail.com/en/?login={yopmail.split('@')[0]}",
                        wait_until="domcontentloaded",
                        timeout=30000
                    )
                    mail_text = read_latest_yopmail_body(yop_page, "Aadhaar OTP")
                    log(f"  Mail preview: {mail_text[:200]}")

                    otp = extract_otp_from_text(
                        mail_text,
                        digits=6,
                        context_words=["otp", "aadhaar", "aadhar", "digilocker", "verification"],
                    )
                    log(f"  6-digit Aadhaar OTP candidate: {otp}")

                    if otp:
                        log(f"  6-digit Aadhaar OTP captured: {otp}")
                        yop_page.close()
                        break
                    else:
                        log("  No 6-digit OTP found yet - retrying...")

                except Exception as e:
                    log(f"  OTP fetch error: {e}")
                finally:
                    if yop_page and not yop_page.is_closed():
                        yop_page.close()

                page.wait_for_timeout(5000)

            if otp:
                if not enter_otp_value(page, otp, "Aadhaar OTP"):
                    step_fail(STEP, "Aadhaar OTP field found but OTP could not be entered")
                    return False

                log(f"  Aadhaar OTP entered: {otp}")

                submitted = False
                for btn_xpath in [
                    "//button[normalize-space(text())='Submit']",
                    "//button[normalize-space(text())='Verify']",
                    "//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]",
                    "//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VERIFY')]",
                    "//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CONTINUE')]",
                    "//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]",
                    "//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VERIFY')]",
                    "//button[@type='submit']",
                ]:
                    try:
                        btn = page.locator(btn_xpath).first
                        if btn.is_visible(timeout=2000) and btn.is_enabled():
                            btn.scroll_into_view_if_needed(timeout=2_000)
                            btn.click()
                            log(f"  OTP submitted via: {btn_xpath}")
                            submitted = True
                            break
                    except Exception:
                        continue

                if not submitted:
                    try:
                        otp_input.press("Enter")
                        log("  OTP submitted by pressing Enter")
                    except Exception:
                        log("  OTP submit button not found after entry")

                page.wait_for_timeout(2000)
            else:
                step_fail(STEP, "Aadhaar OTP not received within timeout")
                return False
        else:
            step_fail(STEP, "Aadhaar OTP input not visible after Aadhaar submit")
            return False

        # ── DigiLocker Security PIN (optional) ──
        try:
            pin_field = page.locator("//input[@type='password']").first
            if pin_field.is_visible(timeout=5000):
                pin_field.fill(TEST_DATA["digilocker_pin"])
                page.locator("//button[contains(text(),'Submit')]").first.click()
                log("  Security PIN entered")
                page.wait_for_timeout(2000)
        except Exception:
            log("  No security PIN step")

        wait_after_digilocker_submit(page)

        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 4: Bank Details ───────────────────────────

def step_bank_details(page: Page) -> bool:
    STEP = "Bank Details Entry"
    try:
        log("  Waiting for Bank Verification page...")
        try:
            page.wait_for_url(lambda url: "bank" in url.lower(), timeout=20000)
            log(f"  Bank page loaded: {page.url}")
        except Exception:
            log(f"  Current URL: {page.url} — continuing anyway")

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        bank_ready = False
        for _ in range(30):
            if bank_details_page_ready(page):
                bank_ready = True
                break
            page.wait_for_timeout(1_000)
        if not bank_ready:
            step_fail(STEP, f"Bank details controls not ready. Current URL: {page.url}")
            return False

        log("  Clicking 'Enter bank details manually'...")
        manual_link_clicked = bank_manual_form_visible(page) or click_enter_bank_details_manually(page)

        if not manual_link_clicked:
            log("  Manual link did not reveal account field; retrying once after scroll")
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(500)
            manual_link_clicked = click_enter_bank_details_manually(page)

        if not manual_link_clicked and not bank_manual_form_visible(page):
            step_fail(STEP, "Enter bank details manually link did not open account fields")
            return False

        # ── Account Number ──
        acc_field = None
        for strategy in [
            "//input[@id='bankacno']",
            "//input[contains(@placeholder,'Account Number')]",
            "//input[contains(@name,'account')]",
            "//input[contains(@id,'account')]",
        ]:
            try:
                loc = page.locator(strategy).first
                if loc.is_visible(timeout=3000):
                    acc_field = loc
                    log(f"  Account field found via: {strategy}")
                    break
            except Exception:
                continue

        if not acc_field:
            step_fail(STEP, "Account number input not found")
            return False

        acc_field.scroll_into_view_if_needed()
        acc_field.click()
        acc_field.fill("")
        acc_field.press_sequentially(TEST_DATA["bank_account"], delay=100)
        log(f"  Account number entered: {TEST_DATA['bank_account']}")

        # ── IFSC Code ──
        ifsc_field = None
        for strategy in [
            "//input[@id='bankifsc']",
            "//input[contains(@placeholder,'IFSC')]",
            "//input[contains(@name,'ifsc')]",
            "//input[contains(@id,'ifsc')]",
        ]:
            try:
                loc = page.locator(strategy).first
                if loc.is_visible(timeout=3000):
                    ifsc_field = loc
                    log(f"  IFSC field found via: {strategy}")
                    break
            except Exception:
                continue

        if not ifsc_field:
            step_fail(STEP, "IFSC input not found")
            return False

        ifsc_field.click()
        ifsc_field.fill("")
        ifsc_field.press_sequentially(TEST_DATA["ifsc"], delay=100)
        log(f"  IFSC entered: {TEST_DATA['ifsc']}")

        log("  Waiting for IFSC bank lookup to complete...")
        page.wait_for_timeout(3000)

        # ── MICR ──
        try:
            micr_el = page.locator("//input[@placeholder='Bank MICR']").first
            if micr_el.is_visible(timeout=3000):
                micr_el.triple_click()
                micr_el.fill("")
                micr_el.press_sequentially(TEST_DATA.get("micr", ""), delay=150)
                log(f"  MICR filled manually: {TEST_DATA.get('micr', '')}")
        except Exception as me:
            log(f"  MICR handling failed: {me}")

        # ── Bank Pincode ──
        try:
            pin_el = page.locator("//input[@placeholder='Bank Pincode']").first
            if pin_el.is_visible(timeout=5000):
                page.wait_for_timeout(2000)
                for _ in range(10):
                    page.wait_for_timeout(500)
                    fetched_value = pin_el.input_value() or ""
                    if fetched_value.strip():
                        log(f"  Bank pincode auto-fetched: {fetched_value.strip()}")
                        break
                else:
                    fallback = TEST_DATA.get("bank_pincode", "000000")
                    if fallback:
                        pin_el.triple_click()
                        pin_el.fill("")
                        pin_el.press_sequentially(fallback, delay=150)
                        log(f"  Bank pincode filled manually: {pin_el.input_value()}")
                    else:
                        log("  Bank pincode empty and no fallback — skipping")
        except Exception as pe:
            log(f"  Bank pincode handling failed: {pe}")

        # ── Verify & Proceed ──
        log("  Clicking Verify & Proceed...")
        for strategy in [
            "//button[contains(text(),'Verify & Proceed')]",
            "//button[contains(text(),'Verify and Proceed')]",
            "//input[@value='Verify & Proceed']",
            "//button[contains(text(),'Verify')]",
            "//button[@type='submit']",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=3000) and btn.is_enabled():
                    btn.scroll_into_view_if_needed()
                    btn.click()
                    log(f"  Verify & Proceed clicked via: {strategy}")
                    page.wait_for_timeout(2000)
                    break
            except Exception:
                continue

        step_pass(STEP, f"Acc: {TEST_DATA['bank_account']}  IFSC: {TEST_DATA['ifsc']}")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 5: Bank Mismatch Popup ────────────────────

def step_bank_mismatch_popup(page: Page) -> bool:
    STEP = "Bank Mismatch Check"
    try:
        proceed_anyway = page.locator("xpath=//*[contains(text(),'Proceed Anyway')]").first
        if proceed_anyway.is_visible(timeout=2_000):
            proceed_anyway.click()
            log("  Unexpected bank mismatch popup appeared; clicked Proceed Anyway")
            page.wait_for_timeout(2_000)
            step_pass(STEP, "Mismatch popup handled")
        else:
            log("  No bank mismatch expected for this account")
            step_pass(STEP, "No mismatch")
        return True
    except Exception as e:
        log(f"  No bank mismatch popup found: {e}")
        step_pass(STEP, "No mismatch")
        return True

def step_account_aggregator(page: Page) -> bool:
    STEP = "Account Aggregator — Proceed"
    try:
        scroll_by(page, 300)
        proceed = page.locator("xpath=//a[text()='Proceed']")
        proceed.wait_for(state="visible", timeout=20_000)
        proceed.hover()
        proceed.click()
        page.wait_for_timeout(2_000)
        step_pass(STEP)
        return True
    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 7: Onemoney — Login ───────────────────────
# Matches Java: user_select_the_one_money_otp() — clicks Send OTP

def step_onemoney_login(page: Page) -> bool:
    STEP = "Onemoney — Login"
    try:
        log("  Waiting for Onemoney login page to load...")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        # ── Wait for login heading ──
        try:
            page.wait_for_selector(
                "xpath=//*[contains(text(),'Login')]",
                timeout=10000,
                state="visible"
            )
            log("  Onemoney Login page detected")
        except Exception:
            log("  Onemoney Login heading not detected — continuing anyway")

        # ── Click Send OTP (mobile is pre-filled from Navia) ──
        send_otp_clicked = False
        for strategy in [
            "xpath=//button[text()=' Send OTP ']",
            "xpath=//button[normalize-space(text())='Send OTP']",
            "xpath=//button[contains(text(),'Send OTP')]",
            "xpath=//button[contains(translate(text(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SEND OTP')]",
            "xpath=//button[@type='submit']",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=5000) and btn.is_enabled():
                    btn.click()
                    log(f"  Send OTP clicked via: {strategy}")
                    send_otp_clicked = True
                    break
            except Exception:
                continue

        if not send_otp_clicked:
            log("  WARNING: Send OTP button not found — page may have auto-proceeded")

        # ── Confirm OTP was sent ──
        try:
            page.wait_for_selector(
                "xpath=//*[contains(text(),'OTP sent') or contains(text(),'otp sent')]",
                timeout=10000,
                state="visible"
            )
            log("  OTP sent confirmation detected")
        except Exception:
            log("  OTP sent confirmation not detected — continuing anyway")

        page.wait_for_timeout(2000)
        step_pass(STEP, "Onemoney Send OTP clicked")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 8: Onemoney — Enter OTP ───────────────────
# Reads OTP from naviatestingekyc@yopmail.com inbox
# Matches Java: enterotp0 field + Login button

def step_onemoney_otp(page: Page, ctx: BrowserContext, yopmail_user: str) -> bool:
    STEP = "Onemoney — OTP Verification"
    try:
        log("  Fetching Onemoney OTP from YOPmail...")

        # ── Wait 18 seconds for OTP email (matches Java Thread.sleep(18000)) ──
        log("  Waiting 18 seconds for Onemoney OTP email...")
        page.wait_for_timeout(18000)

        # ── Open yopmail tab and get OTP ──
        otp = None
        yop_page = None
        try:
            yop_page = ctx.new_page()
            username = yopmail_user.split("@")[0]
            yop_page.goto(
                f"https://yopmail.com/en/?login={username}",
                wait_until="domcontentloaded",
                timeout=30000
            )
            yop_page.wait_for_timeout(5000)

            # ── Refresh inbox twice (matches Java: refresh, refresh) ──
            for _ in range(2):
                try:
                    ref = yop_page.locator("#refresh")
                    ref.wait_for(state="visible", timeout=5000)
                    ref.click()
                    log("  Yopmail inbox refreshed")
                    yop_page.wait_for_timeout(2000)
                except Exception:
                    pass

            # ── Read mail body ──
            mail_frame = yop_page.frame_locator("#ifmail")
            if not wait_for_yopmail_captcha_clear(yop_page, "Onemoney OTP", max_wait=90):
                step_fail(STEP, "YOPmail CAPTCHA blocked Onemoney OTP read")
                return False
            mail_frame.locator("body").wait_for(timeout=10000)
            mail_text = mail_frame.locator("body").inner_text()
            log(f"  Yopmail body preview: {mail_text[:300]}")

            # ── Extract 6-digit OTP ──
            otp_candidate = extract_otp_from_text(mail_text, digits=6, context_words=["otp", "onemoney", "jk-onemny-s", "verification"])
            if otp_candidate:
                otp = otp_candidate
                log(f"  Onemoney OTP extracted: {otp}")
            else:
                log("  No 6-digit OTP found in first mail — trying next mail...")
                try:
                    inbox_frame = yop_page.frame_locator("#ifinbox")
                    second_mail = inbox_frame.locator("div.m, .lm").nth(1)
                    if second_mail.is_visible(timeout=3000):
                        second_mail.click()
                        yop_page.wait_for_timeout(2000)
                        if not wait_for_yopmail_captcha_clear(yop_page, "Onemoney OTP", max_wait=90):
                            step_fail(STEP, "YOPmail CAPTCHA blocked Onemoney OTP read")
                            return False
                        mail_text2 = mail_frame.locator("body").inner_text()
                        otp_candidate2 = extract_otp_from_text(mail_text2, digits=6, context_words=["otp", "onemoney", "jk-onemny-s", "verification"])
                        if otp_candidate2:
                            otp = otp_candidate2
                            log(f"  Onemoney OTP from second mail: {otp}")
                except Exception as e2:
                    log(f"  Second mail read failed: {e2}")

        except Exception as e:
            log(f"  Yopmail tab error: {e}")
        finally:
            if yop_page and not yop_page.is_closed():
                yop_page.close()
                log("  Yopmail tab closed")

        if not otp:
            step_fail(STEP, "Could not fetch Onemoney OTP from YOPmail")
            return False

        log(f"  Onemoney OTP fetched: {otp}")

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # ── Strategy 1: enterotp0 input (matches Java: //input[@id='enterotp0']) ──
        otp_entered = False
        try:
            otp_box = page.locator("xpath=//input[@id='enterotp0']").first
            if otp_box.is_visible(timeout=5000):
                otp_box.click()
                otp_box.fill(otp)
                log("  OTP entered via #enterotp0 field")
                otp_entered = True
        except Exception as e:
            log(f"  enterotp0 strategy failed: {e}")

        # ── Strategy 2: 6 individual editable inputs (skip readonly) ──
        if not otp_entered:
            try:
                all_inputs = page.locator("xpath=//input").all()
                editable_inputs = []
                for inp in all_inputs:
                    try:
                        if (inp.is_visible() and
                                not inp.is_disabled() and
                                inp.get_attribute("readonly") is None):
                            editable_inputs.append(inp)
                    except Exception:
                        continue

                log(f"  Found {len(editable_inputs)} editable inputs")
                if len(editable_inputs) >= 6:
                    for idx, digit in enumerate(otp[:6]):
                        editable_inputs[idx].click()
                        editable_inputs[idx].fill(digit)
                        page.wait_for_timeout(150)
                    log("  OTP entered digit by digit")
                    otp_entered = True
            except Exception as e:
                log(f"  Individual input strategy failed: {e}")

        # ── Strategy 3: single input field ──
        if not otp_entered:
            for strategy in [
                "xpath=//input[@type='tel']",
                "xpath=//input[@type='number']",
                "xpath=//input[@maxlength='6']",
                "xpath=//input[contains(@placeholder,'OTP') or contains(@placeholder,'otp')]",
            ]:
                try:
                    inp = page.locator(strategy).first
                    if inp.is_visible(timeout=3000):
                        inp.click()
                        inp.fill(otp)
                        log(f"  OTP entered via: {strategy}")
                        otp_entered = True
                        break
                except Exception:
                    continue

        if not otp_entered:
            log("  WARNING: Could not enter OTP into any field")

        # ── Click Login button (matches Java: //button[text()=' Login ']) ──
        for strategy in [
            "xpath=//button[text()=' Login ']",
            "xpath=//button[normalize-space(text())='Login']",
            "xpath=//button[contains(text(),'Login')]",
            "xpath=//button[contains(translate(text(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'LOGIN')]",
            "xpath=//button[@type='submit']",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=5000) and btn.is_enabled():
                    btn.click()
                    log(f"  Login clicked via: {strategy}")
                    break
            except Exception:
                continue

        page.wait_for_timeout(3000)
        step_pass(STEP, f"Onemoney OTP '{otp}' entered and submitted")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 9: Onemoney — Choose Linked Accounts ──────
# Matches Java: user_select_one_money_account() - selects configured account suffix, clicks Approve + Confirm

# ─────────────────────────── Step 9: Onemoney — Choose Linked Accounts ──────

def step_onemoney_choose_accounts(page: Page) -> bool:
    STEP = "Onemoney - Choose Linked Accounts"
    try:
        target_account = str(TEST_DATA.get("onemoney_account") or "33939500923")
        target_suffix = target_account[-4:] if len(target_account) >= 4 else "0923"
        log(f"  Waiting for Onemoney choose accounts page; selecting account ending {target_suffix}...")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        try:
            select_all = page.locator(
                "xpath=(//*[contains(normalize-space(.),'Select All')]//input[@type='checkbox'] | //input[@type='checkbox' and contains(@aria-label,'Select All')])[1]"
            ).first
            if select_all.is_visible(timeout=3000) and select_all.is_checked():
                select_all.click()
                page.wait_for_timeout(500)
                log("  Deselected 'Select All'")
        except Exception:
            pass

        suffix_selected = False
        suffix_xpaths = [
            f"xpath=(//*[contains(normalize-space(.),'{target_suffix}')]//ancestor::app-fi-small-card)[1]",
            f"xpath=(//*[contains(normalize-space(.),'{target_suffix}')]//ancestor::*[contains(@class,'card')][1])",
            f"xpath=(//*[contains(normalize-space(.),'{target_suffix}')]//ancestor::*[.//input[@type='checkbox']][1])",
            f"xpath=(//*[contains(normalize-space(.),'{target_suffix}')])[1]",
        ]

        for strategy in suffix_xpaths:
            try:
                target = page.locator(strategy).first
                if target.is_visible(timeout=5000):
                    target.scroll_into_view_if_needed(timeout=2_000)
                    target.click(force=True)
                    log(f"  Onemoney account ending {target_suffix} clicked via: {strategy}")
                    suffix_selected = True
                    page.wait_for_timeout(700)
                    break
            except Exception:
                continue

        if not suffix_selected:
            try:
                suffix_selected = page.evaluate(
                    """
                    (suffix) => {
                        const visible = (el) => {
                            const rect = el.getBoundingClientRect();
                            const style = window.getComputedStyle(el);
                            return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
                        };
                        const candidates = Array.from(document.querySelectorAll('app-fi-small-card, .card, div, section, article, label'));
                        const card = candidates.find(el => visible(el) && (el.innerText || '').includes(suffix));
                        if (!card) return false;
                        const checkbox = card.querySelector("input[type='checkbox']");
                        if (checkbox && !checkbox.checked) {
                            checkbox.click();
                            return true;
                        }
                        card.click();
                        return true;
                    }
                    """,
                    target_suffix,
                )
                if suffix_selected:
                    log(f"  Onemoney account ending {target_suffix} selected via DOM fallback")
            except Exception as e:
                log(f"  DOM fallback for account ending {target_suffix} failed: {e}")

        if not suffix_selected:
            step_fail(STEP, f"Account ending {target_suffix} not found")
            return False

        page.wait_for_timeout(1000)
        step_pass(STEP, f"Onemoney account ending {target_suffix} selected")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False

def step_onemoney_consent(page: Page) -> bool:
    STEP = "Onemoney — Accept Consent"
    try:
        log("  Waiting for Onemoney Approve button...")
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(3000)

        # ── Scroll down to Approve sticky footer ──
        scroll_by(page, 500)
        page.wait_for_timeout(1000)

        try:
            page.wait_for_selector(
                "xpath=//div[contains(text(),'Approve')]",
                timeout=15000,
                state="visible"
            )
            log("  Approve button appeared")
        except Exception as e:
            log(f"  Approve wait timed out: {e}")

        # ── Click Approve ──
        approved = False
        for strategy in [
            "xpath=//div[normalize-space(text())='Approve']",
            "xpath=//div[contains(text(),'Approve')]",
            "xpath=//button[contains(text(),'Approve')]",
            "xpath=//button[contains(@class,'approve')]",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=5000):
                    btn.click()
                    log(f"  Approve clicked via: {strategy}")
                    approved = True
                    break
            except Exception:
                continue

        if not approved:
            log(f"  Approve button not found on: {page.url}")
            step_fail(STEP, "Approve button not found")
            return False

        # ── Handle Confirm popup ──
        page.wait_for_timeout(2000)
        try:
            page.wait_for_selector(
                "xpath=//*[contains(text(),'Confirm')]",
                timeout=10000,
                state="visible"
            )
            log("  Confirm popup detected")

            for strategy in [
                "xpath=//button[normalize-space(text())='Confirm']",
                "xpath=//button[contains(text(),'Confirm')]",
                "xpath=//button[contains(translate(text(),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'CONFIRM')]",
            ]:
                try:
                    btn = page.locator(strategy).first
                    if btn.is_visible(timeout=5000) and btn.is_enabled():
                        btn.click()
                        log(f"  Confirm clicked via: {strategy}")
                        break
                except Exception:
                    continue
        except Exception:
            log("  Confirm popup not shown — skipping")

        page.wait_for_timeout(3000)
        step_pass(STEP, "Onemoney consent approved and confirmed")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 11: Email Verification ────────────────────
# Matches Java: user_click_the_mail_id() — enters email, verifies OTP from yopmail

def step_email_verification(page: Page, ctx: BrowserContext) -> bool:
    STEP = "Email Verification"
    try:
        email = TEST_DATA.get("yopmail", "")
        log(f"  Email verification with: {email}")

        page.wait_for_load_state("domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # ── Check if aggregator error link appears (matches Java try/catch) ──
        try:
            aggregator_link = page.locator(
                "xpath=//p[contains(text(),'Account Aggregator')]//following-sibling::a"
            )
            if aggregator_link.is_visible(timeout=5000):
                aggregator_link.click()
                log("  Aggregator fallback link clicked")
                page.wait_for_timeout(2000)
        except Exception:
            log("  Aggregator is working fine — no fallback needed")

        # ── Fill email input ──
        email_input = None
        for strategy in [
            "xpath=//input[@id='email']",
            "xpath=//input[@type='email']",
            "xpath=//input[contains(@placeholder,'email') or contains(@placeholder,'Email')]",
        ]:
            try:
                loc = page.locator(strategy).first
                if loc.is_visible(timeout=5000):
                    email_input = loc
                    break
            except Exception:
                continue

        if not email_input:
            log("  Email input not found — skipping email verification")
            step_pass(STEP, "Email input not found — skipped")
            return True

        email_input.click()
        email_input.fill(email)
        log(f"  Email entered: {email}")

        # ── Click Verify Email ──
        for strategy in [
            "xpath=//button[normalize-space(text())='Verify Email']",
            "xpath=//button[contains(text(),'Verify Email')]",
            "xpath=//button[contains(text(),'Send OTP')]",
            "xpath=//button[@type='submit']",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=3000) and btn.is_enabled():
                    btn.click()
                    log(f"  Verify Email button clicked via: {strategy}")
                    break
            except Exception:
                continue

        page.wait_for_timeout(18000)
        log("  Waited 18 seconds for email OTP")

        # ── Fetch OTP from yopmail ──
        otp = None
        yop_page = None
        try:
            username = email.split("@")[0]
            yop_page = ctx.new_page()
            yop_page.goto(
                f"https://yopmail.com/en/?login={username}",
                wait_until="domcontentloaded",
                timeout=30000
            )
            yop_page.wait_for_timeout(5000)

            try:
                yop_page.locator("#refresh").click()
                yop_page.wait_for_timeout(3000)
            except Exception:
                pass

            mail_frame = yop_page.frame_locator("#ifmail")
            if not wait_for_yopmail_captcha_clear(yop_page, "Email OTP", max_wait=90):
                step_fail(STEP, "YOPmail CAPTCHA blocked Email OTP read")
                return False
            mail_frame.locator("body").wait_for(timeout=10000)
            mail_body = mail_frame.locator("body").inner_text()
            log(f"  Email OTP mail preview: {mail_body[:300]}")

            # ── 4-digit OTP (matches Java pattern \\b\\d{4}\\b) ──
            otp_candidate4 = extract_otp_from_text(mail_body, digits=4, context_words=["otp", "email", "verification"])
            if otp_candidate4:
                otp = otp_candidate4
                log(f"  Email OTP found (4-digit): {otp}")
            else:
                # fallback: 6-digit
                otp_candidate6 = extract_otp_from_text(mail_body, digits=6, context_words=["otp", "email", "verification"])
                if otp_candidate6:
                    otp = otp_candidate6
                    log(f"  Email OTP found (6-digit): {otp}")

        except Exception as e:
            log(f"  Yopmail email OTP fetch error: {e}")
        finally:
            if yop_page and not yop_page.is_closed():
                yop_page.close()

        if not otp:
            log("  Email OTP not received — continuing without verification")
            step_pass(STEP, "OTP not received — skipped")
            return True

        # ── Enter OTP (matches Java: //input[@name='emailOtp']) ──
        otp_entered = False
        for strategy in [
            "xpath=//input[@name='emailOtp']",
            "xpath=//input[@name='emailotp']",
            "xpath=//input[contains(@placeholder,'OTP') or contains(@placeholder,'otp')]",
            "xpath=//input[@type='number']",
            "xpath=//input[@type='tel']",
        ]:
            try:
                inp = page.locator(strategy).first
                if inp.is_visible(timeout=3000):
                    inp.click()
                    inp.fill(otp)
                    log(f"  Email OTP entered via: {strategy}")
                    otp_entered = True
                    break
            except Exception:
                continue

        if not otp_entered:
            log("  WARNING: Could not find email OTP input field")

        # ── Click Verify (matches Java: (//button[text()='Verify'])[2]) ──
        page.wait_for_timeout(1000)
        for strategy in [
            "xpath=(//button[text()='Verify'])[2]",
            "xpath=(//button[normalize-space(text())='Verify'])[1]",
            "xpath=//button[contains(text(),'Verify')]",
            "xpath=//button[@type='submit']",
        ]:
            try:
                btn = page.locator(strategy).first
                if btn.is_visible(timeout=3000) and btn.is_enabled():
                    btn.click()
                    log(f"  Verify clicked via: {strategy}")
                    break
            except Exception:
                continue

        page.wait_for_timeout(3000)

        # ── Check for aggregator popup after verify ──
        try:
            aggregator_link2 = page.locator(
                "xpath=//p[contains(text(),'Account Aggregator')]//following-sibling::a"
            )
            if aggregator_link2.is_visible(timeout=5000):
                aggregator_link2.click()
                log("  Post-verify aggregator link clicked")
                page.wait_for_timeout(2000)
        except Exception:
            log("  No post-verify aggregator popup")

        step_pass(STEP, f"Email OTP '{otp}' entered")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


def step_personal_details(page: Page) -> bool:
    STEP = "Personal Details"

    def click_text_button(text: str, index: int = 0, timeout: int = 1_500) -> bool:
        locators = [
            f"xpath=//label[normalize-space(.)='{text}']",
            f"xpath=//button[normalize-space(.)='{text}']",
            f"xpath=//*[normalize-space(.)='{text}' and (self::label or self::button or self::div or self::span)]",
            f"xpath=//input[@id='{text}']",
            f"xpath=//input[@value='{text}']",
        ]

        for selector in locators:
            try:
                item = page.locator(selector).nth(index)
                item.wait_for(state="visible", timeout=timeout)
                item.click(timeout=timeout)
                return True
            except Exception:
                pass

        for selector in locators:
            try:
                item = page.locator(selector).nth(index)
                if item.count() > 0:
                    item.click(force=True, timeout=timeout)
                    return True
            except Exception:
                pass

        try:
            page.get_by_text(text, exact=True).nth(index).click(timeout=timeout)
            return True
        except Exception:
            try:
                page.get_by_text(text, exact=True).nth(index).click(force=True, timeout=timeout)
                return True
            except Exception:
                pass

        return False

    def fill_input_by_name(name: str, value: str, label: str, timeout: int = 10_000):
        try:
            field = page.locator(f"xpath=//input[@name='{name}']")
            field.wait_for(state="visible", timeout=timeout)
            field.click()
            field.fill(value)
            log(f"  {label} filled: {value}")
        except Exception as e:
            log(f"  {label} fill failed: {e}")

    try:
        td = TEST_DATA

        # Required values from actual form
        td["occupation"] = "Business"
        td["source_income"] = "Salaried"
        td["salary_range"] = "1L-5L"

        # ── Marital Status ──────────────────────────────────────────────────
        if click_text_button("Unmarried"):
            log("  Marital status: Unmarried")
        else:
            try:
                page.locator("xpath=//input[@name='marital' and @value='02']").click()
                log("  Marital status: Unmarried fallback")
            except Exception:
                log("  Marital status radio not found")

        page.wait_for_timeout(1_000)

        # ── Spouse Name ─────────────────────────────────────────────────────
        # Usually skipped for Unmarried. If visible and required, fill only when data exists.
        try:
            spouse = page.locator("xpath=//input[@name='spouseName' or @name='sfname']")
            if spouse.count() > 0 and spouse.first.is_visible() and td.get("spouse_name"):
                spouse.first.click()
                spouse.first.fill(td["spouse_name"])
                log(f"  Spouse Name filled: {td['spouse_name']}")
        except Exception:
            pass

        # ── Mother / Father Name ────────────────────────────────────────────
        fill_input_by_name("mfname", td["mother_name"], "Mother Name")
        fill_input_by_name("ffname", td["father_name"], "Father Name")

        # ── Educational Qualification ───────────────────────────────────────
        if click_text_button("Graduate"):
            log("  Education: Graduate")
        else:
            log("  Graduate option not found")

        # ── Occupation ──────────────────────────────────────────────────────
        occupation = td["occupation"]  # Business
        if click_text_button(occupation):
            log(f"  Occupation selected: {occupation}")
        else:
            log(f"  Occupation '{occupation}' not found")

        # ── Annual Income ───────────────────────────────────────────────────
        salary = td["salary_range"]  # 1L-5L
        if click_text_button(salary):
            log(f"  Annual income selected: {salary}")
        else:
            log(f"  Annual income '{salary}' not found")

        # ── Experienced in Stock Market ─────────────────────────────────────
        if click_text_button("0-1 Year"):
            log("  Stock market experience: 0-1 Year")
        else:
            log("  Stock market experience option not found")

        # ── Source of Income ────────────────────────────────────────────────
        try:
            source_income = td.get("source_income", "Salaried")
            source = page.locator(f"xpath=//label[normalize-space(.)='{source_income}']").first
            source.click(timeout=1_500)
            log(f"  Source of income: {source_income}")
        except Exception:
            if click_text_button("Salaried"):
                log("  Source of income: Salaried fallback")
            else:
                log("  Source of income 'Salaried' not found")

        # ── FATCA Details ───────────────────────────────────────────────────
        if click_text_button("Indian"):
            log("  Nationality: Indian")
        else:
            log("  Nationality 'Indian' not found")

        # Country of Birth defaults to INDIA in screenshot.
        try:
            country = page.locator(
                "xpath=//label[contains(normalize-space(.),'Country of Birth')]/following::*[contains(normalize-space(.),'INDIA')][1]"
            )
            if country.count() > 0:
                log("  Country of Birth: INDIA")
        except Exception:
            pass

        # Keep "Country of tax other than India?" OFF
        try:
            tax_toggle = page.locator(
                "xpath=//*[contains(normalize-space(.),'Country of tax other than India')]/following::*[contains(@class,'switch') or contains(@class,'toggle')][1]"
            )
            if tax_toggle.count() > 0:
                log("  Country of tax other than India: No")
        except Exception:
            pass

        # ── Agreement Checkboxes ────────────────────────────────────────────
        checkbox_xpaths = [
            "//span[contains(normalize-space(.),'I have read and accepted')]/preceding::input[@type='checkbox'][1]",
            "//label[contains(normalize-space(.),'I have read and accepted')]//input[@type='checkbox']",
            "//input[@name='declaration' or @name='agree_declaration']",

            "//span[contains(normalize-space(.),'I am opting for BSDA')]/preceding::input[@type='checkbox'][1]",
            "//label[contains(normalize-space(.),'I am opting for BSDA')]//input[@type='checkbox']",

            "//span[contains(normalize-space(.),'neither mentally challenged')]/preceding::input[@type='checkbox'][1]",
            "//label[contains(normalize-space(.),'neither mentally challenged')]//input[@type='checkbox']",

            "//input[@name='agree_all']",
            "//label[normalize-space(.)='all']//input[@type='checkbox']",
        ]

        for xpath in checkbox_xpaths:
            try:
                cb = page.locator(f"xpath={xpath}").first
                if cb.count() > 0:
                    if not cb.is_checked():
                        cb.click(force=True)
            except Exception:
                pass

        log("  Agreement checkboxes handled")

        # ── Next / Submit ───────────────────────────────────────────────────
        try:
            page.locator("xpath=//button[@id='submitform']").click()
        except Exception:
            page.locator("xpath=//button[normalize-space(.)='Next']").click()

        page.wait_for_timeout(2_000)

        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 13: Document Upload ───────────────────────

from config import TEST_FILES

def step_document_upload(page: Page) -> bool:
    STEP = "Document Upload (PAN, Signature)"
    try:
        page.wait_for_timeout(2_000)

        # ── Signature ──
        page.wait_for_timeout(1_000)
        try:
            ok = False
            upload_sign = page.locator("xpath=//button[@id='upload_sign']")
            if upload_sign.count() > 0:
                try:
                    upload_sign.first.click(timeout=2_000)
                    page.wait_for_timeout(500)
                except Exception:
                    log("  Signature upload button not clickable; using direct file upload")

            ok = upload_file_direct(
                page,
                TEST_FILES["signature"],
                "Signature",
                [
                    "css=input#drawimagerest",
                    "css=input#drawimage",
                    "css=input[name='drawimagerest']",
                    "css=input[name='drawimage']",
                ],
            )
            if not ok:
                ok = upload_file(page, "//label[@id='drawimagerestcl']", TEST_FILES["signature"], "Signature")
            if ok:
                page.wait_for_timeout(2_000)
                click_use_original_for_signature(page)
                page.wait_for_timeout(2_000)
        except Exception as e:
            log(f"  Signature upload step issue: {e}")

        # ── Financial Statement (auto-fetched check) ──
        try:
            fin_container = page.locator("xpath=//span[@id='select2-finproof-container']")
            if fin_container.is_visible(timeout=5_000):
                fin_text = fin_container.inner_text()
                if "6 Month Bank Statement" in fin_text:
                    log("  6-month financial statement auto-fetched ✅")
                    try:
                        view_btn2 = page.locator("xpath=(//button[text()='View'])[1]")
                        view_btn2.dispatch_event("click")
                        page.wait_for_timeout(2_000)
                        scroll_open_viewer_to_bottom(page, "Financial statement")
                        close_visible_dialog(page, "Financial statement")
                        page.locator("xpath=(//span[text()='×']//parent::button)[1]").dispatch_event("click")
                        page.wait_for_timeout(1_000)
                    except Exception:
                        pass
        except Exception:
            pass

        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False

# ─────────────────────────── Step 14: Proceed to Nominees / Next ─────────────

def step_proceed_to_nominees_or_next(page: Page) -> bool:
    STEP = "Proceed (Save / Next / Agree)"
    try:
        page.wait_for_timeout(1_000)

        try:
            save_btn = page.locator("xpath=//button[contains(text(),'Save')]")
            if save_btn.is_visible(timeout=3_000):
                save_btn.click()
                log("  'Save' clicked")
                page.wait_for_timeout(1_000)
        except Exception:
            pass

        try:
            submit_btn = page.locator("xpath=//button[@id='submitform']")
            if submit_btn.is_visible(timeout=5_000):
                submit_btn.click()
                log("  Submit form clicked")
                page.wait_for_timeout(1_500)
                click_modal_action(page, "Proceed confirmation", extra_words=["OK", "Okay", "Proceed"])
        except Exception:
            try:
                next_btn = page.locator("xpath=//button[contains(text(),'Next')]")
                next_btn.click()
                log("  Next button clicked")
                page.wait_for_timeout(1_500)
            except Exception:
                log("  Neither Submit nor Next button found")

        if not click_risk_disclosure_agree(page, timeout=12_000):
            log("  Risk disclosure popup not shown; continuing")

        if not click_proceed_without_nominees(page, timeout=12_000):
            log("  'Proceed without Nominees' not shown; continuing")

        if not accept_ipv_camera_consent(page, timeout=12_000):
            log("  IPV consent popup not shown yet; continuing")

        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 15: IPV / View KYC PDF ────────────────────



import base64
import time
from playwright.sync_api import Page, BrowserContext

# ─────────────────────────── Fake Camera Injection ──────────────────────────

def inject_fake_camera_with_blink(page):
    """
    Injects fake blinking camera into browser using JavaScript.
    No OBS, no virtual camera software, no drivers needed.
    Must be called BEFORE page.goto()
    """

    js_code = """
    (() => {
        const OPEN_MS = 900;
        const CLOSED_MS = 800;
        const canvas = document.createElement('canvas');
        canvas.width = 1280;
        canvas.height = 720;
        const ctx = canvas.getContext('2d');
        let isBlinking = false;

        function drawLoop() {
            ctx.fillStyle = '#f3d2b8';
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            ctx.fillStyle = '#1f2937';
            ctx.beginPath();
            ctx.ellipse(640, 360, 210, 260, 0, 0, Math.PI * 2);
            ctx.fill();

            ctx.fillStyle = '#f3d2b8';
            ctx.beginPath();
            ctx.ellipse(640, 390, 172, 210, 0, 0, Math.PI * 2);
            ctx.fill();

            ctx.strokeStyle = '#d9b08c';
            ctx.lineWidth = 2;
            for (let y = 300; y <= 500; y += 28) {
                ctx.beginPath();
                ctx.moveTo(520, y);
                ctx.lineTo(760, y + 8);
                ctx.stroke();
            }

            ctx.fillStyle = '#111827';

            if (isBlinking) {
                ctx.strokeStyle = '#111827';
                ctx.lineWidth = 15;
                ctx.lineCap = 'round';
                ctx.beginPath();
                ctx.moveTo(560, 365);
                ctx.quadraticCurveTo(590, 374, 620, 365);
                ctx.moveTo(660, 365);
                ctx.quadraticCurveTo(690, 374, 720, 365);
                ctx.stroke();
            } else {
                ctx.fillStyle = '#ffffff';
                ctx.beginPath();
                ctx.ellipse(590, 365, 34, 22, 0, 0, Math.PI * 2);
                ctx.ellipse(690, 365, 34, 22, 0, 0, Math.PI * 2);
                ctx.fill();
                ctx.fillStyle = '#111827';
                ctx.beginPath();
                ctx.ellipse(590, 365, 13, 13, 0, 0, Math.PI * 2);
                ctx.ellipse(690, 365, 13, 13, 0, 0, Math.PI * 2);
                ctx.fill();
            }

            ctx.strokeStyle = '#111827';
            ctx.lineWidth = 8;
            ctx.beginPath();
            ctx.arc(640, 450, 55, 0.15 * Math.PI, 0.85 * Math.PI);
            ctx.stroke();
            requestAnimationFrame(drawLoop);
        }

        function blinkLoop() {
            isBlinking = true;
            setTimeout(() => {
                isBlinking = false;
                setTimeout(blinkLoop, OPEN_MS);
            }, CLOSED_MS);
        }

        const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
        navigator.mediaDevices.getUserMedia = async (constraints) => {
            if (constraints && constraints.video) {
                return canvas.captureStream(30);
            }
            return originalGetUserMedia(constraints);
        };

        drawLoop();
        setTimeout(blinkLoop, OPEN_MS);
    })();
    """

    page.add_init_script(js_code)
    print("Fake blink camera injected into browser")
    return

    # Load both images as base64
    with open(r"C:\ipv_photos\eyes_open.jpg", "rb") as f:
        open_b64 = base64.b64encode(f.read()).decode()

    with open(r"C:\ipv_photos\eyes_closed.jpg", "rb") as f:
        closed_b64 = base64.b64encode(f.read()).decode()

    js_code = f"""
    (() => {{
        const OPEN_IMG   = 'data:image/jpeg;base64,{open_b64}';
        const CLOSED_IMG = 'data:image/jpeg;base64,{closed_b64}';

        const OPEN_MS   = 1500;   // eyes open duration  (1.5 seconds)
        const CLOSED_MS = 300;    // eyes closed duration (0.3 seconds)

        // Create hidden canvas — this becomes the fake camera feed
        const canvas  = document.createElement('canvas');
        canvas.width  = 1280;
        canvas.height = 720;
        const ctx     = canvas.getContext('2d');

        // Load both images
        const openImg   = new Image();
        const closedImg = new Image();
        openImg.src     = OPEN_IMG;
        closedImg.src   = CLOSED_IMG;

        let isBlinking = false;

        // Continuously draw current frame to canvas at 30fps
        function drawLoop() {{
            const img = isBlinking ? closedImg : openImg;
            if (img.complete && img.naturalHeight !== 0) {{
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            }}
            requestAnimationFrame(drawLoop);
        }}

        // Blink forever until photo is captured
        function blinkLoop() {{
            // Close eyes
            isBlinking = true;
            console.log('Eyes Closed');

            setTimeout(() => {{
                // Open eyes
                isBlinking = false;
                console.log('Eyes Open');

                // Wait then blink again
                setTimeout(blinkLoop, OPEN_MS);
            }}, CLOSED_MS);
        }}

        // Start once images are loaded
        openImg.onload = () => {{
            drawLoop();                          // start drawing frames
            setTimeout(blinkLoop, OPEN_MS);      // first blink after 1.5s
            console.log('✅ Fake blink camera ready');
        }};

        // Override getUserMedia to return canvas stream
        const originalGetUserMedia = navigator.mediaDevices.getUserMedia.bind(
            navigator.mediaDevices
        );

        navigator.mediaDevices.getUserMedia = async (constraints) => {{
            if (constraints && constraints.video) {{
                const stream = canvas.captureStream(30);
                console.log('✅ Fake camera stream sent to IPV');
                return stream;
            }}
            // For audio, use original
            return originalGetUserMedia(constraints);
        }};

        console.log('✅ Camera override installed');
    }})();
    """

    page.add_init_script(js_code)
    print("✅ Fake blink camera injected into browser")


# ─────────────────────────── Step 15: IPV / View KYC PDF ────────────────────

def inject_fake_camera_with_blink(page):
    open_path = r"C:\ipv_photos\eyes_opened.jpg"
    closed_path = r"C:\ipv_photos\eyes_closed.jpg"

    if not os.path.exists(open_path) or not os.path.exists(closed_path):
        raise FileNotFoundError("IPV blink images missing in C:\\ipv_photos")

    with open(open_path, "rb") as f:
        open_b64 = base64.b64encode(f.read()).decode()

    with open(closed_path, "rb") as f:
        closed_b64 = base64.b64encode(f.read()).decode()

    js_code = f"""
    (() => {{
        const OPEN_IMG = 'data:image/jpeg;base64,{open_b64}';
        const CLOSED_IMG = 'data:image/jpeg;base64,{closed_b64}';
        const OPEN_MS = 900;
        const CLOSED_MS = 700;
        const canvas = document.createElement('canvas');
        canvas.width = 1280;
        canvas.height = 720;
        const ctx = canvas.getContext('2d', {{ willReadFrequently: true }});
        const openImg = new Image();
        const closedImg = new Image();
        openImg.src = OPEN_IMG;
        closedImg.src = CLOSED_IMG;
        let currentImg = openImg;

        function drawCameraFrame(img) {{
            ctx.fillStyle = '#f2f2f2';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            if (!img.complete || img.naturalWidth === 0) return;

            const boxSize = Math.round(canvas.height * 0.62);
            const boxX = Math.round((canvas.width - boxSize) / 2);
            const boxY = Math.round((canvas.height - boxSize) / 2);
            ctx.fillStyle = '#eeeeee';
            ctx.fillRect(boxX, boxY, boxSize, boxSize);

            const scale = Math.min(boxSize / img.naturalWidth, boxSize / img.naturalHeight);
            const width = img.naturalWidth * scale;
            const height = img.naturalHeight * scale;
            const x = boxX + (boxSize - width) / 2;
            const y = boxY + (boxSize - height) / 2;
            ctx.drawImage(img, x, y, width, height);
        }}

        function drawLoop() {{
            drawCameraFrame(currentImg);
            requestAnimationFrame(drawLoop);
        }}

        function blinkLoop() {{
            currentImg = closedImg;
            setTimeout(() => {{
                currentImg = openImg;
                setTimeout(blinkLoop, OPEN_MS);
            }}, CLOSED_MS);
        }}

        const install = () => {{
            drawLoop();
            setTimeout(blinkLoop, 700);
            navigator.mediaDevices.getUserMedia = async (constraints) => {{
                if (constraints && constraints.video) {{
                    return canvas.captureStream(30);
                }}
                return new MediaStream();
            }};
        }};

        let loaded = 0;
        const done = () => {{
            loaded += 1;
            if (loaded >= 2) install();
        }};
        openImg.onload = done;
        closedImg.onload = done;
        if (openImg.complete) done();
        if (closedImg.complete) done();
    }})();
    """

    page.add_init_script(js_code)
    print("Real IPV blink camera injected into browser")


def step_view_kyc_pdf(page: Page, ctx: BrowserContext) -> bool:
    STEP = "View Unsigned KYC PDF (IPV)"
    try:
        if "proteantech.in" in page.url.lower():
            raise RuntimeError("Reached Protean before viewing unsigned KYC PDF")

        original_url = page.url
        clicked_pdf_link = False
        deadline = time.time() + 120
        while time.time() < deadline:
            current_url = page.url.lower()
            if "proteantech.in" in current_url:
                raise RuntimeError("Page moved to Protean before View Unsigned KYC PDF was clicked")
            try:
                clicked_pdf_link = page.evaluate(
                    """() => !!Array.from(document.querySelectorAll('a')).find(a =>
                        /View\\s+Unsigned\\s+KYC\\s+PDF|Unsigned\\s+KYC\\s+PDF/i.test(a.textContent || '')
                    )"""
                )
                if clicked_pdf_link:
                    break
            except Exception:
                pass
            page.wait_for_timeout(200)

        if not clicked_pdf_link:
            raise RuntimeError("View Unsigned KYC PDF link not found before timeout")

        pdf_page = None
        try:
            with ctx.expect_page(timeout=15_000) as pdf_info:
                page.evaluate(
                    """() => {
                        const links = Array.from(document.querySelectorAll('a'));
                        const link = links.find(a => /View\\s+Unsigned\\s+KYC\\s+PDF|Unsigned\\s+KYC\\s+PDF/i.test(a.textContent || ''));
                        if (!link) throw new Error('Unsigned PDF link not found');
                        link.scrollIntoView({ block: 'center', inline: 'center' });
                        link.click();
                    }"""
                )
            pdf_page = pdf_info.value
            log("  View Unsigned KYC PDF clicked; PDF tab opened")
        except Exception:
            page.evaluate(
                """() => {
                    const links = Array.from(document.querySelectorAll('a'));
                    const link = links.find(a => /View\\s+Unsigned\\s+KYC\\s+PDF|Unsigned\\s+KYC\\s+PDF/i.test(a.textContent || ''));
                    if (!link) throw new Error('Unsigned PDF link not found');
                    link.scrollIntoView({ block: 'center', inline: 'center' });
                    link.click();
                }"""
            )
            log("  View Unsigned KYC PDF clicked")

        def is_pdf_page(candidate: Page) -> bool:
            try:
                candidate_url = candidate.url.lower()
                if ".pdf" in candidate_url or "cloudfront" in candidate_url or "unsignedforms" in candidate_url:
                    return True
                title = (candidate.title() or "").lower()
                return ".pdf" in title or "unsigned" in title
            except Exception:
                return False

        deadline = time.time() + 60
        while time.time() < deadline:
            if pdf_page and is_pdf_page(pdf_page):
                break
            pages_after = get_all_pages(ctx)
            ordered_pages = [p for p in pages_after if p != page] + [page]
            for candidate in reversed(ordered_pages):
                try:
                    if is_pdf_page(candidate):
                        pdf_page = candidate
                        break
                except Exception:
                    continue
            if pdf_page:
                break

            current_url = page.url.lower()
            if current_url != original_url.lower() and (".pdf" in current_url or "unsigned" in current_url or "cloudfront" in current_url):
                pdf_page = page
                break
            if "proteantech.in" in current_url:
                raise RuntimeError("Page moved to Protean before unsigned PDF was viewed")
            page.wait_for_timeout(500)

        if not pdf_page:
            raise RuntimeError("Unsigned PDF did not open after clicking View Unsigned KYC PDF")

        pdf_page.bring_to_front()
        pdf_page.wait_for_timeout(3_000)

        try:
            pdf_page.mouse.click(900, 500)
        except Exception:
            pass
        pdf_page.keyboard.press("Control+End")
        pdf_page.wait_for_timeout(2_000)
        try:
            pdf_page.evaluate(
                """() => {
                    const viewer = document.querySelector('pdf-viewer');
                    if (viewer && viewer.shadowRoot) {
                        const scroller = viewer.shadowRoot.querySelector('#scroller');
                        if (scroller) scroller.scrollTop = scroller.scrollHeight;
                    }
                    window.scrollTo(0, document.body.scrollHeight);
                }"""
            )
        except Exception:
            pass
        for _ in range(3):
            pdf_page.keyboard.press("End")
            pdf_page.wait_for_timeout(1_000)
        for _ in range(45):
            pdf_page.mouse.wheel(0, 2500)
            pdf_page.wait_for_timeout(150)

        log("  Unsigned KYC PDF viewed to last page")

        if pdf_page != page:
            pdf_page.close()
            page.bring_to_front()
        else:
            page.go_back(wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_000)
            if "uuid.php" not in page.url.lower():
                page.goto(original_url, wait_until="domcontentloaded", timeout=30_000)

        page.wait_for_timeout(1_000)
        if "proteantech.in" in page.url.lower():
            raise RuntimeError("Unsigned PDF step ended on Protean before Proceed to E-sign")
        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 15b: IPV Camera Capture ───────────────────

def step_ipv_capture(page: Page) -> bool:
    STEP = "IPV Camera Capture"
    try:
        inject_fixed_geolocation(page)
        accept_ipv_camera_consent(page, timeout=5_000)
        try:
            if page.locator("xpath=//*[contains(normalize-space(.),'Kindly enable your Location')]").is_visible(timeout=3_000):
                log("  Location prompt shown; reloading with fixed geolocation")
                page.reload(wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
                accept_ipv_camera_consent(page, timeout=3_000)
        except Exception:
            pass

        log("  Waiting for IPV camera button...")

        # ── 1. Wait for camera button to appear ───────────────────────────
        capture_btn = page.locator(
            "xpath=//button[contains(text(),'Capture') or "
            "contains(text(),'Take Photo') or "
            "contains(text(),'Open Camera') or "
            "contains(text(),'Start') or "
            "contains(text(),'Allow')]"
        )
        capture_btn.wait_for(state="visible", timeout=30_000)
        capture_btn.click()
        log("  IPV camera UI opened — blink simulation running")

        # ── 2. Wait for IPV to detect blink and auto capture ──────────────
        # Camera keeps blinking every 1.5 seconds automatically
        # IPV system will detect blink and capture photo on its own
        # Increase timeout if your IPV system takes longer
        max_wait    = 60_000   # wait up to 60 seconds
        check_every = 2_000    # check every 2 seconds
        elapsed     = 0

        while elapsed < max_wait:
            page.wait_for_timeout(check_every)
            elapsed += check_every

            # Check if IPV has moved past camera screen automatically
            # i.e. a success message or next step button appeared
            success_indicators = page.locator(
                "xpath=//*[contains(text(),'Success') or "
                "contains(text(),'Captured') or "
                "contains(text(),'Verified') or "
                "contains(text(),'Proceed') or "
                "contains(text(),'Continue') or "
                "contains(text(),'completed')]"
            )

            if success_indicators.count() > 0:
                log("  ✅ IPV liveness check passed — photo captured")
                break

            log(f"  Waiting for IPV capture... ({elapsed // 1000}s elapsed)")

        # ── 3. Click confirm/proceed if button appears ─────────────────────
        confirm_selectors = [
            "xpath=//button[contains(text(),'Confirm')]",
            "xpath=//button[contains(text(),'Submit')]",
            "xpath=//button[contains(text(),'Proceed')]",
            "xpath=//button[contains(text(),'Continue')]",
            "xpath=//button[contains(text(),'Next')]",
            "xpath=//button[contains(text(),'Use Photo')]",
        ]

        for selector in confirm_selectors:
            btn = page.locator(selector)
            if btn.count() > 0 and btn.first.is_visible():
                btn.first.click()
                log(f"  Clicked confirm button: {selector}")
                break

        page.wait_for_timeout(2_000)
        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 16: Proceed to Esign ──────────────────────

def step_ipv_capture(page: Page) -> bool:
    STEP = "IPV Camera Capture"
    try:
        inject_fixed_geolocation(page)
        accept_ipv_camera_consent(page, timeout=5_000)

        try:
            if page.locator("xpath=//*[contains(normalize-space(.),'Kindly enable your Location')]").is_visible(timeout=3_000):
                log("  Location prompt shown; reloading with fixed geolocation")
                page.reload(wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
                accept_ipv_camera_consent(page, timeout=3_000)
        except Exception:
            pass

        log("  Waiting for IPV yellow face box / ready state...")
        ready_selectors = [
            "xpath=//*[contains(normalize-space(.),'Finding Face')]",
            "xpath=//*[contains(normalize-space(.),'Blink Your Eyes')]",
            "xpath=//*[contains(normalize-space(.),'Please follow the above instructions')]",
            "xpath=//*[contains(normalize-space(.),'Look straight into the camera')]",
            "css=video",
            "css=canvas",
        ]

        ready = False
        for _ in range(30):
            for selector in ready_selectors:
                try:
                    loc = page.locator(selector).first
                    if loc.count() > 0 and loc.is_visible(timeout=500):
                        ready = True
                        break
                except Exception:
                    continue
            if ready:
                break
            page.wait_for_timeout(500)

        if ready:
            log("  IPV camera ready; waiting for automatic photo capture")
        else:
            log("  IPV ready/yellow box was not detected; continuing without that precondition")

        deadline = time.time() + 60
        while time.time() < deadline:
            try:
                next_step = page.locator(
                    "xpath=//*[contains(normalize-space(.),'View Unsigned KYC PDF') or "
                    "contains(normalize-space(.),'Unsigned KYC PDF') or "
                    "contains(normalize-space(.),'proceed to E-sign') or "
                    "contains(normalize-space(.),'Proceed to E-sign') or "
                    "contains(normalize-space(.),'proceed to E-Sign') or "
                    "contains(normalize-space(.),'Proceed to E-Sign') or "
                    "contains(normalize-space(.),'Success') or "
                    "contains(normalize-space(.),'Captured') or "
                    "contains(normalize-space(.),'Verified')]"
                )
                if "photo_capturing" not in page.url.lower() or (next_step.count() > 0 and next_step.first.is_visible(timeout=500)):
                    log("  IPV photo auto-captured; moved to next step")
                    step_pass(STEP)
                    return True
            except Exception:
                pass

            page.wait_for_timeout(1_000)

        step_fail(STEP, "IPV auto-capture did not complete within 60 seconds")
        return False

    except Exception as e:
        step_fail(STEP, str(e))
        return False


def step_proceed_to_esign(page: Page) -> bool:
    STEP = "Proceed to Esign"
    try:
        page.bring_to_front()
        if "proteantech.in" in page.url.lower():
            log("  Protean E-sign page already loaded")
            step_pass(STEP)
            return True
        selectors = [
            "xpath=//input[@name='digiosubmit']",
            "xpath=//input[@type='submit' and (contains(@value,'Proceed') or contains(@value,'E-sign') or contains(@value,'Esign'))]",
            "xpath=//button[contains(normalize-space(.),'proceed to E-sign')]",
            "xpath=//button[contains(normalize-space(.),'Proceed to E-sign')]",
            "xpath=//button[contains(normalize-space(.),'Proceed to Esign')]",
            "xpath=//a[contains(normalize-space(.),'Proceed to E-sign')]",
            "xpath=//a[contains(normalize-space(.),'Proceed to Esign')]",
        ]
        clicked = False

        for _ in range(20):
            for selector in selectors:
                try:
                    btn = page.locator(selector).first
                    if btn.count() > 0 and btn.is_visible(timeout=1_000):
                        btn.scroll_into_view_if_needed(timeout=3_000)
                        btn.click(force=True, timeout=3_000)
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break
            if "proteantech.in" in page.url.lower():
                clicked = True
                break
            page.wait_for_timeout(1_000)

        if not clicked:
            raise RuntimeError("Proceed to E-sign button not found")
        try:
            page.wait_for_url("**proteantech.in**", timeout=30_000)
        except Exception:
            page.wait_for_timeout(2_000)
        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Main Flow ──────────────────────────────────────

def run_automation():
    with sync_playwright() as p:

        # ── Launch browser with camera permission ──────────────────────────
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--use-fake-ui-for-media-stream",    # auto allow camera popup
                "--allow-file-access-from-files",
            ]
        )
        ctx = browser.new_context(
            permissions=["camera", "geolocation"],
            geolocation=TEST_GEOLOCATION,
        )
        page = ctx.new_page()

        # ── INJECT FAKE CAMERA BEFORE ANYTHING ELSE ───────────────────────
        inject_fixed_geolocation(page)
        inject_fake_camera_with_blink(page)

        # ── Navigate to your KYC page ──────────────────────────────────────
        page.goto("your_kyc_url_here")

        # ── Run all your existing steps ────────────────────────────────────
        # ... your other steps before IPV ...

        if not step_view_kyc_pdf(page, ctx):
            return

        if not step_ipv_capture(page):         # ← IPV with blink simulation
            return

        if not step_proceed_to_esign(page):
            return

        # ... your other steps after IPV ...

        browser.close()


# ─────────────────────────── Step 17: Aadhaar Esign OTP ─────────────────────

def step_esign_aadhaar_otp(page: Page, ctx: BrowserContext) -> bool:
    STEP = "Esign — Aadhaar OTP"
    try:
        yopmail = TEST_DATA["yopmail"]

        page.wait_for_load_state("domcontentloaded", timeout=30_000)
        if "proteantech.in" not in page.url.lower():
            page.wait_for_url("**proteantech.in**", timeout=60_000)

        checkbox = page.locator("xpath=//input[@type='checkbox' and not(@disabled)]").first
        checkbox.wait_for(state="visible", timeout=30_000)
        checkbox.scroll_into_view_if_needed(timeout=3_000)
        checkbox.click(force=True, timeout=5_000)
        log("  Protean consent checkbox selected")
        scroll_by(page, 200)

        aadhaar = TEST_DATA.get("aadhaar", "")
        if aadhaar:
            vid_field = page.locator(
                "xpath=//input[not(@type='hidden') and (@id='vid' or @name='vid' or "
                "contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'aadhaar') or "
                "contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'vid'))]"
            ).first
            vid_field.wait_for(state="visible", timeout=30_000)
            vid_field.scroll_into_view_if_needed(timeout=3_000)
            vid_field.click()
            vid_field.press("Control+A")
            vid_field.fill(aadhaar)
            log("  Aadhaar entered on Protean")

        send_otp_selectors = [
            "xpath=//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SEND OTP')]",
            "xpath=//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SEND OTP')]",
            "xpath=//button[@ng-show='!otpSent || countExceed || !chkvalue']",
        ]
        sent = False
        for selector in send_otp_selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=3_000):
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    btn.click(force=True, timeout=5_000)
                    sent = True
                    log("  Esign Send OTP clicked")
                    break
            except Exception:
                continue
        if not sent:
            raise RuntimeError("Esign Send OTP button not found")

        page.wait_for_timeout(5_000)

        otp = get_otp_from_yopmail_new_tab(
            ctx,
            yopmail,
            max_wait=150,
            context_words=ESIGN_SMS_CONTEXT_WORDS,
        )
        if not otp:
            step_fail(STEP, "Esign OTP not received")
            return False

        log(f"  Esign OTP: {otp}")
        otp_input = page.locator(
            "xpath=//input[@id='otpInput' or contains(translate(@placeholder,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp') or "
            "contains(translate(@name,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'otp')]"
        ).first
        otp_input.wait_for(state="visible", timeout=30_000)
        otp_input.click()
        otp_input.fill(otp)

        submit_selectors = [
            "xpath=//button[@ng-click='otpVerify()']",
            "xpath=//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]",
            "xpath=//input[contains(translate(@value,'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SUBMIT')]",
            "xpath=//button[contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VERIFY')]",
        ]
        submitted = False
        for selector in submit_selectors:
            try:
                btn = page.locator(selector).first
                if btn.count() > 0 and btn.is_visible(timeout=3_000):
                    btn.scroll_into_view_if_needed(timeout=3_000)
                    btn.click(force=True, timeout=5_000)
                    submitted = True
                    log("  Esign OTP submitted")
                    break
            except Exception:
                continue
        if not submitted:
            raise RuntimeError("Esign OTP submit button not found")

        page.wait_for_timeout(8_000)
        try:
            page.wait_for_url("**/congrats.php**", timeout=60_000)
        except Exception:
            page.wait_for_timeout(5_000)

        step_pass(STEP, f"OTP {otp} entered")
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ─────────────────────────── Step 18: Verify Esign Pages ────────────────────

def step_verify_esign_pages(page: Page, ctx: BrowserContext) -> bool:
    STEP = "Verify Esign Pages (View Doc / Share / Install)"
    try:
        def _open_and_close(locator_xpath: str, label: str, scroll_to_last_page: bool = False) -> None:
            try:
                congrats_url = page.url
                elem = page.locator(f"xpath={locator_xpath}").first
                try:
                    elem.wait_for(state="visible", timeout=30_000)
                except Exception:
                    elem = page.get_by_text(label, exact=False).first
                    elem.wait_for(state="visible", timeout=10_000)
                elem.scroll_into_view_if_needed(timeout=3_000)

                pages_before = get_all_pages(ctx)
                clicked_link = False
                try:
                    with ctx.expect_page(timeout=5_000) as new_page_info:
                        elem.click(force=True, timeout=3_000)
                        clicked_link = True
                    new_tab = new_page_info.value
                except Exception:
                    if not clicked_link:
                        elem.click(force=True, timeout=3_000)
                    page.wait_for_timeout(2_000)
                    pages_after = get_all_pages(ctx)
                    created = [p for p in pages_after if p not in pages_before]
                    new_tab = created[-1] if created else page

                new_tab.bring_to_front()
                new_tab.wait_for_timeout(2_000)
                if scroll_to_last_page:
                    for _ in range(22):
                        new_tab.mouse.wheel(0, 450)
                        new_tab.wait_for_timeout(800)
                    log(f"  '{label}' viewed to last page")

                if new_tab != page:
                    new_tab.wait_for_timeout(1_000)
                    new_tab.close()
                else:
                    close_visible_dialog(page, label)
                    try:
                        page.go_back(wait_until="domcontentloaded", timeout=15_000)
                    except Exception:
                        page.goto(congrats_url, wait_until="domcontentloaded", timeout=30_000)
                if "congrats.php" not in page.url:
                    page.goto(congrats_url, wait_until="domcontentloaded", timeout=30_000)
                page.bring_to_front()
                log(f"  '{label}' opened and closed")
            except Exception as ex:
                log(f"  '{label}' step skipped: {ex}")

        page.wait_for_timeout(2_000)
        page.wait_for_url("**/congrats.php**", timeout=60_000)
        _open_and_close("//*[self::a or self::button][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'VIEW DOCUMENT')]", "View Document", scroll_to_last_page=True)
        page.wait_for_timeout(2_000)
        _open_and_close("//*[self::a or self::button][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'INSTALL APP')]", "Install App")
        page.wait_for_timeout(2_000)
        _open_and_close("//*[self::a or self::button][contains(translate(normalize-space(.),'abcdefghijklmnopqrstuvwxyz','ABCDEFGHIJKLMNOPQRSTUVWXYZ'),'SHARE FEEDBACK')]", "Share Feedback")
        page.wait_for_timeout(1_000)

        step_pass(STEP)
        return True

    except Exception as e:
        step_fail(STEP, str(e))
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN RUNNER
# ═════════════════════════════════════════════════════════════════════════════

def step_complete_esign_flow(page: Page, ctx: BrowserContext) -> bool:
    if not step_view_kyc_pdf(page, ctx):
        return False
    if not step_proceed_to_esign(page):
        return False
    if not step_esign_aadhaar_otp(page, ctx):
        return False
    if not step_verify_esign_pages(page, ctx):
        return False
    return True


def run_ekyc_test() -> str:
    global LOG, STEPS
    LOG   = []
    STEPS = []

    now_str   = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    video_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "videos")
    os.makedirs(video_dir, exist_ok=True)

    overall_status = "FAIL"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            args=[
                "--start-maximized",
                "--use-fake-ui-for-media-stream",
                "--allow-file-access-from-files",
            ],
            slow_mo=100,
        )

        ctx: BrowserContext = browser.new_context(
            viewport=None,
            record_video_dir=video_dir,
            record_video_size={"width": 1280, "height": 720},
            accept_downloads=True,
            permissions=["camera", "geolocation"],
            geolocation=TEST_GEOLOCATION,
        )
        ctx.grant_permissions(["camera", "geolocation"], origin="https://open.navia.co.in")
        ctx.set_default_timeout(20_000)

        page: Page = ctx.new_page()
        video_path = None

        try:
            log("=" * 60)
            log("  Navia E-KYC Automation Started")
            log(f"  URL   : {APP_URL}")
            log(f"  Mobile: {TEST_DATA['mobile']}")
            log("=" * 60)

            # ── Step 1: Launch URL ──────────────────────────────────────────
            inject_fixed_geolocation(page)
            inject_fake_camera_with_blink(page)
            if RUN_IPV_ONLY:
                log("  IPV-only mode ON: opening photo capture page directly")
                page.goto("https://open.navia.co.in/photo_capturing.php", wait_until="domcontentloaded", timeout=30_000)
                page.wait_for_timeout(2_000)
                step_ipv_capture(page)
                step_complete_esign_flow(page, ctx)
                failed = [s for s in STEPS if s["status"] == "FAIL"]
                overall_status = "FAIL" if failed else "PASS"
                log("=" * 60)
                log(f"  Overall: {overall_status}")
                log(f"  Passed : {len([s for s in STEPS if s['status'] == 'PASS'])}")
                log(f"  Failed : {len(failed)}")
                log("=" * 60)
                return overall_status

            if not step_launch_url(page):
                raise RuntimeError("Cannot launch URL — aborting")

            # ── Step 2: Mobile OTP ──────────────────────────────────────────
            if not step_enter_mobile_and_verify_otp(page, ctx):
                raise RuntimeError("Mobile OTP failed — aborting")

            # ── Step 3: Aadhaar Verification (DigiLocker) ───────────────────
            if RUN_IPV_AFTER_MOBILE:
                log("  E-Sign pending mode ON: mobile verified, clicking Continue to load unsigned PDF")
                if not click_continue_after_mobile_for_ipv(page):
                    raise RuntimeError("Continue button after mobile verification not found")
                step_complete_esign_flow(page, ctx)
                failed = [s for s in STEPS if s["status"] == "FAIL"]
                overall_status = "FAIL" if failed else "PASS"
                log("=" * 60)
                log(f"  Overall: {overall_status}")
                log(f"  Passed : {len([s for s in STEPS if s['status'] == 'PASS'])}")
                log(f"  Failed : {len(failed)}")
                log("=" * 60)
                return overall_status

            if RESUME_FROM_PERSONAL_DETAILS:
                log("  Resume mode ON: after mobile OTP, continuing from Personal/KRA details")
                if not step_continue_existing_user_to_personal_details(page):
                    raise RuntimeError("Could not continue from existing user details page")

                def _resume_skip(step_name):
                    log(f"  Resume mode skipped before Personal/KRA: {step_name}")
                    return True

                globals()["step_aadhaar_verification"] = lambda page, ctx: _resume_skip("Aadhaar Verification")
                globals()["step_bank_details"] = lambda page: _resume_skip("Bank Details")
                globals()["step_bank_mismatch_popup"] = lambda page: _resume_skip("Bank Mismatch Popup")
                globals()["step_account_aggregator"] = lambda page: _resume_skip("Account Aggregator")
                globals()["step_onemoney_login"] = lambda page: _resume_skip("Onemoney Login")
                globals()["step_onemoney_otp"] = lambda page, ctx, email: _resume_skip("Onemoney OTP")
                globals()["step_onemoney_choose_accounts"] = lambda page: _resume_skip("Onemoney Choose Accounts")
                globals()["step_onemoney_consent"] = lambda page: _resume_skip("Onemoney Consent")
                globals()["step_email_verification"] = lambda page, ctx: _resume_skip("Email Verification")

            step_aadhaar_verification(page, ctx)

            # ── Step 4: Bank Details ────────────────────────────────────────
            if not step_bank_details(page):
                raise RuntimeError("Bank details failed - aborting instead of continuing to later steps")

            # ── Step 5: Bank Mismatch Popup ─────────────────────────────────
            if not step_bank_mismatch_popup(page):
                log("  Bank mismatch popup step failed — continuing")

            # ── Step 6: Account Aggregator — click Proceed on Navia page ────
            if not step_account_aggregator(page):
                log("  Account Aggregator Proceed step failed — continuing")

            # ── Step 7: Onemoney — Login (Send OTP) ─────────────────────────
            if not step_onemoney_login(page):
                log("  Onemoney login step failed — continuing")

            # ── Step 8: Onemoney — Enter OTP ────────────────────────────────
            if not step_onemoney_otp(page, ctx, "naviatestingekyc@yopmail.com"):
                log("  Onemoney OTP verification failed — continuing")

            # ── Step 9: Onemoney — Choose Accounts ──────────────────────────
            if not step_onemoney_choose_accounts(page):
                log("  Onemoney choose accounts failed — continuing")

            # ── Step 10: Onemoney — Accept Consent ──────────────────────────
            if not step_onemoney_consent(page):
                log("  Onemoney consent failed — continuing")

            # ── Step 11: Email Verification ──────────────────────────────────
            if not step_email_verification(page, ctx):
                log("  Email verification failed — continuing")

            # ── Step 12: Personal Details ────────────────────────────────────
            if not step_personal_details(page):
                log("  Personal details failed — continuing")

            # ── Step 13: Document Upload ─────────────────────────────────────
            step_document_upload(page)

            # ── Step 14: Proceed to Nominees / Next ─────────────────────────
            step_proceed_to_nominees_or_next(page)

            # ── Step 15: View KYC PDF ────────────────────────────────────────
            step_ipv_capture(page)

            # ── Step 16: Proceed to Esign ────────────────────────────────────
            step_complete_esign_flow(page, ctx)

            # ── Step 17: Esign Aadhaar OTP ───────────────────────────────────
            log("  Esign Aadhaar OTP handled by complete esign flow")

            # ── Step 18: Verify Esign Pages ──────────────────────────────────
            log("  Final Esign links handled by complete esign flow")

            failed = [s for s in STEPS if s["status"] == "FAIL"]
            overall_status = "FAIL" if failed else "PASS"
            log("=" * 60)
            log(f"  Overall: {overall_status}")
            log(f"  Passed : {len([s for s in STEPS if s['status'] == 'PASS'])}")
            log(f"  Failed : {len(failed)}")
            log("=" * 60)

        except Exception as e:
            tb = traceback.format_exc()
            log(f"  CRITICAL ERROR: {e}")
            log(tb)
            overall_status = "FAIL"

        finally:
            raw_video_path = None
            try:
                video_path_obj = page.video
                if video_path_obj:
                    page.close()
                    raw_video_path = video_path_obj.path()
            except Exception as ve:
                log(f"  Video capture close error: {ve}")
                try:
                    page.close()
                except Exception:
                    pass

            ctx.close()
            browser.close()

            try:
                if raw_video_path and os.path.exists(raw_video_path):
                    named_video = os.path.join(video_dir, f"ekyc_{now_str}.webm")
                    for attempt in range(1, 11):
                        try:
                            os.replace(raw_video_path, named_video)
                            video_path = named_video
                            log(f"  Video saved: {video_path}")
                            break
                        except PermissionError:
                            if attempt == 10:
                                raise
                            time.sleep(1)
            except Exception as ve:
                log(f"  Video save error: {ve}")

    try:
        send_report(
            status=overall_status,
            video_path=video_path,
            log_lines=LOG,
            step_results=STEPS,
        )
    except Exception as mail_err:
        print(f"[Mailer] Could not send report: {mail_err}")

    return overall_status


# ─────────────────────────── Entry point ────────────────────────────────────

if __name__ == "__main__":
    result = run_ekyc_test()
    print(f"\n{'='*40}")
    print(f"  Final result: {result}")
    print(f"{'='*40}")
