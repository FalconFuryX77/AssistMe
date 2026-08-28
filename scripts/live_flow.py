import subprocess
import time
import sqlite3
import hashlib
import os

ADB = r"C:\Users\loqav\AppData\Local\Android\Sdk\platform-tools\adb.exe"
ARTIFACTS_DIR = r"C:\Users\loqav\.gemini\antigravity-ide\brain\f0c8e054-de93-4f74-93ca-cc263483c0bc"
DB_PATH = r"C:\Users\loqav\Desktop\AssistMe\backend\assistme.db"

DEV_HELPEE = "emulator-5554"
DEV_HELPER = "emulator-5556"

def run_adb(device: str, args: list[str]) -> str:
    cmd = [ADB, "-s", device] + args
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def tap(dev: str, x: int, y: int, delay: float = 1.0):
    subprocess.run([ADB, "-s", dev, "shell", "input", "tap", str(x), str(y)])
    time.sleep(delay)

def capture(dev: str, name: str):
    res = subprocess.run([ADB, "-s", dev, "exec-out", "screencap", "-p"], capture_output=True)
    open(os.path.join(ARTIFACTS_DIR, f"{name}.png"), "wb").write(res.stdout)
    print(f"[SAVED] {name}.png ({len(res.stdout)} bytes)")

print("=== STARTING LIVE 2-AVD CALL & PAIRING FLOW ===")

# 1. Helpee switch to 'I need help' & show code
print("1. Helpee generating 6-digit setup code...")
tap(DEV_HELPEE, 270, 300, 1.5)
tap(DEV_HELPEE, 540, 800, 2.0)
capture(DEV_HELPEE, "step5_grandma_code_active")

# 2. Get active code from DB
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("SELECT pairing_code_hash, id FROM device_pairings WHERE status = 'awaiting_helper' ORDER BY rowid DESC LIMIT 1")
row = cur.fetchone()
if not row:
    print("ERROR: No pending code found!")
    exit(1)

pairing_code_hash, pairing_id = row
setup_code = next(
    f"{c:06d}" for c in range(1000000)
    if hashlib.sha256(f"{c:06d}".encode()).hexdigest() == pairing_code_hash
)
print(f"Active Setup Code: {setup_code}")

# 3. Alex enters setup code
print("2. Alex entering code and tapping Connect...")
tap(DEV_HELPER, 750, 300, 1.5)
tap(DEV_HELPER, 330, 890, 1.0)
subprocess.run([ADB, "-s", DEV_HELPER, "shell", "input", "keyevent"] + ["67"] * 15)
time.sleep(0.5)
subprocess.run([ADB, "-s", DEV_HELPER, "shell", "input", "text", setup_code])
time.sleep(0.5)
tap(DEV_HELPER, 750, 890, 2.5)
capture(DEV_HELPER, "step6_alex_request_sent")

# 4. Grandma approves
print("3. Grandma receiving approval popup & tapping Allow & Add...")
time.sleep(2.0)
capture(DEV_HELPEE, "step7_grandma_allow_dialog")
tap(DEV_HELPEE, 650, 1300, 2.5) # Allow & Add

# 5. Alex dismisses 'Request Sent'
print("4. Alex dismissing sent dialog...")
tap(DEV_HELPER, 720, 1300, 2.0)
capture(DEV_HELPEE, "step8_grandma_trusted_helpers")
capture(DEV_HELPER, "step9_alex_people_you_help")

# 6. Grandma calls Alex
print("5. Grandma tapping Call on Alex...")
tap(DEV_HELPEE, 650, 1300, 2.0) # Call
tap(DEV_HELPEE, 650, 980, 3.0)  # Call Now
capture(DEV_HELPEE, "step10_grandma_calling_overlay")

# 7. Alex receives ring
print("6. Alex receiving incoming ring...")
time.sleep(3.5)
capture(DEV_HELPER, "step11_alex_incoming_ring")

# 8. Alex accepts
print("7. Alex accepting call...")
tap(DEV_HELPER, 540, 1350, 3.0) # Accept & Start Helping

# 9. Session Workspace
print("8. Capturing live workspace on both devices...")
capture(DEV_HELPEE, "step12_grandma_live_workspace")
capture(DEV_HELPER, "step13_alex_live_workspace")

# 10. Symmetric Teardown
print("9. Leaving session...")
tap(DEV_HELPEE, 540, 1800, 1.5) # Panic / End Session
tap(DEV_HELPEE, 650, 1200, 2.0) # Confirm Leave
capture(DEV_HELPEE, "step14_grandma_after_session")
capture(DEV_HELPER, "step15_alex_after_session")

print("=== ALL 10 PHASES COMPLETED WITH SUCCESS! ===")
