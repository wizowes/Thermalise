"""
setup_startup.py - register Thermalise with Windows Task Scheduler.

Prefers the built EXE (dist/Thermalise.exe) if present, otherwise falls
back to launching the Python script directly.

Run once (no admin needed — registers for the current user only):
    python setup_startup.py        (or Thermalise.exe setup_startup.py)

To remove:
    python setup_startup.py --remove
"""
import subprocess
import sys
from pathlib import Path

TASK_NAME = "Thermalise"
HERE = Path(__file__).parent
EXE = HERE / "dist" / "Thermalise.exe"
SCRIPT = HERE / "vinted4x6_tray.py"
PYTHON = sys.executable


def _command():
    if EXE.exists():
        return f'"{EXE}"'
    return f'"{PYTHON}" "{SCRIPT}"'


def register():
    cmd = [
        "schtasks", "/Create", "/F",
        "/TN", TASK_NAME,
        "/TR", _command(),
        "/SC", "ONLOGON",
        "/DELAY", "0001:00",   # 1 minute after login
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        print(f"Registered '{TASK_NAME}' — starts 1 min after login.")
        print(f"Command: {_command()}")
    else:
        print("Failed:")
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
