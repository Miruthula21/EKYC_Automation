@echo off
cd /d "%~dp0"
set RESUME_FROM_PROOF_UPLOAD=1
python -u test_ekyc.py
pause
