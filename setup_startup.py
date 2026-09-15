"""
setup_startup.py - register the Thermalise tray app with Windows Task Scheduler.

Run once (no admin needed — registers for the current user only):
    python setup_startup.py

To remove:
    python setup_startup.py --remove

The task starts 60 seconds after login to let the desktop settle.
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "Thermalise"
SCRIPT = Path(__file__).parent / "vinted4x6_tray.py"
PYTHON = sys.executable


def register():
    cmd = [
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/TR", f'"{PYTHON}" "{SCRIPT}"',
        "/SC", "ONLOGON",
        "/DELAY", "0001:00",   # 1 minute delay after login
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Registered '{TASK_NAME}' in Task Scheduler.")
        print("Thermalise tray app will start 1 minute after each login.")
    else:
        print("Failed to register task:")
        print(result.stderr.strip())


def remove():
    result = subprocess.run(
        ["schtasks", "/Delete", "/F", "/TN", TASK_NAME],
        capture_output=True, text=True,
    )
    print(result.stdout.strip() or result.stderr.strip())


if __name__ == "__main__":
    if "--remove" in sys.argv:
        remove()
    else:
        register()
