import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# config.py
# C:\Users\Miruthula\Desktop\ekyc-automation\config.py

APP_URL = "https://open.navia.co.in/"   # paste the actual KYC app URL here

# When True, after mobile OTP verification the script opens the existing
# application and continues from Personal/KRA details, then Document Upload.
RESUME_FROM_PERSONAL_DETAILS = False
RUN_IPV_ONLY = False
RUN_IPV_AFTER_MOBILE = False

# Kept only for old code compatibility. Use RESUME_FROM_PERSONAL_DETAILS.
RESUME_AFTER_EMAIL_VERIFICATION = RESUME_FROM_PERSONAL_DETAILS

TEST_DATA = {
    "mobile":           "9360100734",        # 10-digit mobile number
    "yopmail":          "naviatestingekyc@yopmail.com",
    "aadhaar":          "490112030760",      # 12-digit Aadhaar
    "digilocker_pin":   "220504",            # DigiLocker security PIN
    "pan":              "PTVPS6088B",        # PAN number
    "bank_account":     "5247140373",        # Default/Protean bank account number
    "ifsc":             "KKBK0000469",       # Default/Protean IFSC
    "protean_account":  "5247140373",        # Protean bank account number
    "protean_ifsc":     "KKBK0000469",       # Protean IFSC
    "onemoney_account": "33939500923",       # Onemoney account number
    "onemoney_ifsc":    "SBIN0002254",       # Onemoney IFSC
    "micr":             "XXXXXXXXX",         # 9-digit MICR (optional)
    "bank_pincode":     "XXXXXX",            # Bank branch pincode
    "mother_name":      "Geetha",
    "father_name":      "Ramesh",
    "occupation":       "Business",
    "source_income":    "Salaried",
    "salary_range":     "1L-5L",             # must match radio button id exactly
}

TEST_FILES = {
    "pan_card":  os.path.join(BASE_DIR, "test_files", "pan_card.pdf"),
    "signature": os.path.join(BASE_DIR, "test_files", "signature.png"),
}

EMAIL_REPORT = {
    "sender"      : "miruthulak21@gmail.com",       # Gmail you are sending FROM
    "password"    : "jbor rqbh eniq pkpw",      # Gmail App Password (not normal password)
    "receiver"    : ["miruthulak21@gmail.com", "elamukil@navia.co.in"],   # Email to receive the report
    "smtp_server" : "smtp.gmail.com",
    "smtp_port"   : 465
}