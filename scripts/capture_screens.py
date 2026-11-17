import subprocess
import sys
import os
from pathlib import Path

ADB = os.environ.get("ADB", "adb")
ARTIFACTS_DIR = Path(os.environ.get("ASSISTME_ARTIFACTS_DIR", Path(__file__).resolve().parents[1] / "test-artifacts"))

def capture(device_id: str, output_path: str):
    res = subprocess.run([ADB, "-s", device_id, "exec-out", "screencap", "-p"], capture_output=True)
    if res.returncode == 0:
        # Convert any \r\n to \n if needed on Windows
        data = res.stdout.replace(b"\r\n", b"\n") if b"\r\n" in res.stdout[:16] else res.stdout
        with open(output_path, "wb") as f:
            f.write(res.stdout)
        print(f"Captured {device_id} -> {output_path} ({len(res.stdout)} bytes)")
    else:
        print(f"Failed to capture {device_id}: {res.stderr.decode()}")

if __name__ == "__main__":
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    capture("emulator-5554", str(ARTIFACTS_DIR / "helpee_screen.png"))
    capture("emulator-5556", str(ARTIFACTS_DIR / "helper_screen.png"))
