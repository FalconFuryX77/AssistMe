import subprocess
import sys

ADB = r"C:\Users\loqav\AppData\Local\Android\Sdk\platform-tools\adb.exe"

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
    capture("emulator-5554", r"C:\Users\loqav\.gemini\antigravity-ide\brain\f0c8e054-de93-4f74-93ca-cc263483c0bc\helpee_screen.png")
    capture("emulator-5556", r"C:\Users\loqav\.gemini\antigravity-ide\brain\f0c8e054-de93-4f74-93ca-cc263483c0bc\helper_screen.png")
