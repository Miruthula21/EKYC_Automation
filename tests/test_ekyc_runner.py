import os
import sys


PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from test_ekyc import run_ekyc_test


def test_ekyc_flow():
    result = run_ekyc_test()
    assert result == "PASS"
