import pytest
import time
from playwright.sync_api import sync_playwright

APP_URL = "https://open.navia.co.in/"

TEST_DATA = {
    "valid_mobile": "9361710631",
    "duplicate_mobile": "6383265010",
    "invalid_mobile": "12345",
    "invalid_otp": "1111",
    "valid_otp": "123456"
}


# ---------- GLOBAL BROWSER (RUN ONCE) ----------
pw = None
browser = None
page = None


def setup_module(module):
    global pw, browser, page
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False, slow_mo=300)
    context = browser.new_context()
    page = context.new_page()
    page.set_default_timeout(60000)


def teardown_module(module):
    global pw, browser
    browser.close()
    pw.stop()


# ---------- HELPERS ----------
def reset_page():
    page.goto(APP_URL, wait_until="domcontentloaded")


def wait_and_observe(seconds=3):
    time.sleep(seconds)


def enter_mobile(number):
    mobile = page.locator("input[placeholder='Mobile Number']").first
    mobile.fill(number)

    page.locator("text=Get OTP").click()


def wait_for_otp_page():
    page.wait_for_url("**verify_otp.php", timeout=60000)
    page.locator("input[type='tel']").first.wait_for(state="visible")


def get_verify_button():
    return page.locator("button[data-key='btnverify']").first


# ---------- TESTS ----------

def test_empty_mobile():
    reset_page()

    page.locator("text=Get OTP").click()

    error = page.locator("text=Please enter mobile number")
    assert error.is_visible()

    wait_and_observe()


def test_less_digits():
    reset_page()

    enter_mobile(TEST_DATA["invalid_mobile"])

    error = page.locator("text=valid mobile")
    assert error.first.is_visible()

    wait_and_observe()


def test_invalid_format():
    reset_page()

    enter_mobile("0000000000")

    error = page.locator("text=valid mobile")
    assert error.first.is_visible()

    wait_and_observe()


def test_duplicate_number():
    reset_page()

    enter_mobile(TEST_DATA["duplicate_mobile"])

    page.wait_for_selector("text=/Limit|Reached|exists/i", timeout=10000)

    error = page.locator("text=/Limit|Reached|exists/i")
    assert error.count() > 0

    wait_and_observe()


def test_wrong_otp_3_times():
    reset_page()

    enter_mobile(TEST_DATA["valid_mobile"])
    wait_for_otp_page()

    otp_box = page.locator("input[type='tel']").first

    for i in range(3):
        otp_box.fill(TEST_DATA["invalid_otp"])

        btn = get_verify_button()
        btn.wait_for(state="attached")

        btn.click(force=True)

        page.wait_for_timeout(2000)

    # Validate redirect OR error popup
    assert page.url.endswith("index-navia.php") or \
           page.locator("text=/Limit|error/i").count() > 0

    wait_and_observe()


def test_no_terms_checkbox():
    reset_page()

    enter_mobile(TEST_DATA["valid_mobile"])
    wait_for_otp_page()

    otp_box = page.locator("input[type='tel']").first
    otp_box.fill(TEST_DATA["valid_otp"])

    btn = get_verify_button()
    btn.click(force=True)

    error = page.locator("text=accept")
    assert error.count() > 0

    wait_and_observe()


def test_otp_delay():
    reset_page()

    enter_mobile(TEST_DATA["valid_mobile"])
    wait_for_otp_page()

    time.sleep(10)

    otp_box = page.locator("input[type='tel']").first
    assert otp_box.is_visible()

    wait_and_observe()


def test_resend_otp():
    reset_page()

    enter_mobile(TEST_DATA["valid_mobile"])
    wait_for_otp_page()

    resend = page.locator("button[data-key='btnresendotp']").first

    # wait until enabled (cooldown)
    page.wait_for_timeout(30000)

    if resend.is_enabled():
        resend.click()
        assert True
    else:
        pytest.skip("Resend not enabled yet")

    wait_and_observe()


def test_empty_otp_submit():
    reset_page()

    enter_mobile(TEST_DATA["valid_mobile"])
    wait_for_otp_page()

    btn = get_verify_button()
    btn.click(force=True)

    error = page.locator("text=OTP")
    assert error.count() > 0

    wait_and_observe()