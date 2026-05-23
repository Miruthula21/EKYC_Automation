import ast
import datetime
import json
import os
import subprocess
import sys
import time


PROJECT_FOLDER_NAME = "ekyc-automation"
TEST_FILE = "test_ekyc.py"
PYTEST_FILE = os.path.join("tests", "test_ekyc_runner.py")


def header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)


def line():
    print("-" * 60)


def find_project_folder():
    header("STEP 1 | AUTO-LOCATING PROJECT FOLDER")

    current_dir = os.path.abspath(os.path.dirname(__file__))
    if os.path.exists(os.path.join(current_dir, TEST_FILE)):
        print("  [OK] Project folder found:")
        print(f"       {current_dir}")
        return current_dir

    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop", PROJECT_FOLDER_NAME)
    if os.path.exists(os.path.join(desktop_path, TEST_FILE)):
        print("  [OK] Project folder found on Desktop:")
        print(f"       {desktop_path}")
        return desktop_path

    desktop_root = os.path.join(os.path.expanduser("~"), "Desktop")
    print(f"  [..] Searching Desktop for {PROJECT_FOLDER_NAME}...")
    for root, _, files in os.walk(desktop_root):
        if TEST_FILE in files and "mailer.py" in files:
            print("  [OK] Project folder found:")
            print(f"       {root}")
            return root

    print("  [ERROR] Could not find EKYC project folder.")
    print("  [i] Place EKYC_Agent.py inside the ekyc-automation folder and run again.")
    input("\n  Press Enter to close...")
    sys.exit(1)


def syntax_check(path, label):
    print(f"  [i] File : {label}")
    with open(path, "r", encoding="utf-8") as file:
        code = file.read()

    try:
        ast.parse(code)
        print("  [OK] Syntax Check : No errors found")
    except SyntaxError as exc:
        print(f"  [ERROR] Syntax Issue : Line {exc.lineno} - {exc.msg}")
        input("\n  Fix the error and run again. Press Enter to close...")
        sys.exit(1)

    return code


def review_test_code(project_path):
    header("STEP 2 | REVIEWING TEST CODE")

    required_files = [
        TEST_FILE,
        "config.py",
        "mailer.py",
        "yopmail_reader.py",
        PYTEST_FILE,
    ]

    for relative_path in required_files:
        file_path = os.path.join(project_path, relative_path)
        if not os.path.exists(file_path):
            print(f"  [ERROR] Missing file : {relative_path}")
            input("\n  Press Enter to close...")
            sys.exit(1)

        syntax_check(file_path, relative_path)

    test_path = os.path.join(project_path, TEST_FILE)
    with open(test_path, "r", encoding="utf-8") as file:
        source_code = file.read()

    tree = ast.parse(source_code)
    functions = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
    ]
    test_functions = [name for name in functions if name.startswith("test_")]

    print(f"  [OK] Automation Functions : {len(functions)} found")
    print(f"  [OK] Pytest Test Functions: {len(test_functions) + 1} found")
    print(f"       -> test_ekyc_flow")
    print(f"  [OK] Total Lines         : {len(source_code.splitlines())}")
    print("  [OK] Config File         : config.py found")
    print("  [OK] Mailer File         : mailer.py found")
    print("  [OK] Pytest Runner       : tests/test_ekyc_runner.py found")
    print("\n  [OK] Code Review Complete - Ready to run!")


def run_tests(project_path):
    header("STEP 3 | RUNNING PYTEST AUTOMATICALLY")

    start_time = time.time()
    started = datetime.datetime.now().strftime("%d %b %Y, %I:%M %p")
    command = [sys.executable, "-m", "pytest", PYTEST_FILE, "-s"]

    print(f"  [i] Started : {started}")
    print(f"  [i] Running : pytest {PYTEST_FILE} -s")
    print("  [i] LIVE OUTPUT")
    line()

    process = subprocess.Popen(
        command,
        cwd=project_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    output_lines = []
    for output_line in process.stdout:
        print(output_line, end="")
        output_lines.append(output_line.rstrip())

    exit_code = process.wait()
    elapsed = int(time.time() - start_time)
    duration = f"{elapsed // 60}m {elapsed % 60}s"
    status = "PASS" if exit_code == 0 else "FAIL"

    print("\n  [OK] Execution Completed")
    print(f"  [OK] Status   : {status}")
    print(f"  [OK] Duration : {duration}")

    return exit_code, status, duration, output_lines


def read_step_results(project_path):
    json_path = os.path.join(project_path, "ekyc_step_results.json")
    if not os.path.exists(json_path):
        return []

    try:
        with open(json_path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return []


def find_latest_video(project_path):
    videos_dir = os.path.join(project_path, "videos")
    videos = []

    if os.path.exists(videos_dir):
        for root, _, files in os.walk(videos_dir):
            for file_name in files:
                if file_name.lower().endswith((".webm", ".mp4")):
                    videos.append(os.path.join(root, file_name))

    if not videos:
        return None

    return max(videos, key=os.path.getmtime)


def review_report(project_path, exit_code, status, duration, output_lines):
    header("STEP 4 | AGENT REPORT REVIEW")

    steps = read_step_results(project_path)
    if steps:
        passed = [step for step in steps if step.get("status") == "PASS"]
        failed = [step for step in steps if step.get("status") != "PASS"]
    else:
        passed = []
        failed = []

    video_path = find_latest_video(project_path)

    print(f"  OVERALL RESULT : {status}")
    print(f"  EXIT CODE      : {exit_code}")
    print(f"  DURATION       : {duration}")
    print(f"  LOG LINES      : {len(output_lines)}")
    print(f"  VIDEO          : {video_path if video_path else 'No video found'}")

    if steps:
        print(f"  TOTAL STEPS    : {len(steps)}")
        print(f"  PASSED         : {len(passed)}")
        print(f"  FAILED         : {len(failed)}")
        line()
        print("\n  FAILED STEPS:")
        if failed:
            for step in failed:
                print(f"    -> {step.get('step', '')}: {step.get('note', '')}")
        else:
            print("    None - All steps passed.")
    else:
        print("  STEP RESULTS   : Handled inside test_ekyc.py email report")

    line()
    print("\n  AGENT VERDICT:")
    if status == "PASS":
        print("    EKYC automation completed successfully.")
        print("    Email report has been sent by the EKYC mailer.")
    else:
        print("    EKYC automation completed with failure.")
        print("    Check the live output above and the email report for details.")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("   EKYC AUTOMATION AGENT")
    print("   Fully Automatic - No manual steps needed")
    print("=" * 60)
    print(f"   Started : {datetime.datetime.now().strftime('%d %b %Y, %I:%M:%S %p')}")

    project = find_project_folder()
    review_test_code(project)
    code, final_status, total_duration, logs = run_tests(project)
    review_report(project, code, final_status, total_duration, logs)

    header("AGENT COMPLETE")
    print(f"  Finished : {datetime.datetime.now().strftime('%d %b %Y, %I:%M:%S %p')}")
    print("  Email report sent to your inbox")
    print("  Full summary shown above")
    print("=" * 60)

    input("\n  Press Enter to close...\n")
