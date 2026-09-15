"""
build.py - build Thermalise.exe and copy it to the network share.

    python build.py

Steps:
  1. Run PyInstaller with Thermalise.spec
  2. Copy dist/Thermalise.exe to the network share for testing
"""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
EXE_SRC = HERE / "dist" / "Thermalise.exe"

# Network share — update this if the share path changes
SHARE = Path(r"\\192.168.17.21\Share")
SHARE_DEST = SHARE / "Thermalise.exe"


def build():
    print("=== Building Thermalise.exe ===")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "Thermalise.spec"],
        cwd=HERE,
    )
    if result.returncode != 0:
        print("\nBuild failed — not copying to share.")
        sys.exit(1)
    print(f"\nBuild OK: {EXE_SRC}")


def copy_to_share():
    if not SHARE.exists():
        print(f"Share not reachable ({SHARE}) — skipping copy.")
        return
    print(f"Copying to share: {SHARE_DEST}")
    shutil.copy2(EXE_SRC, SHARE_DEST)
    print("Done — available for testing.")


if __name__ == "__main__":
    build()
    copy_to_share()
