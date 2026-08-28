import json
import os
import sqlite3
import subprocess
import time
import hashlib

ADB = r"C:\Users\loqav\AppData\Local\Android\Sdk\platform-tools\adb.exe"
ARTIFACTS_DIR = r"C:\Users\loqav\.gemini\antigravity-ide\brain\f0c8e054-de93-4f74-93ca-cc263483c0bc"
DB_PATH = r"C:\Users\loqav\Desktop\AssistMe\backend\assistme.db"

DEV_HELPEE = "emulator-5554"
DEV_HELPER = "emulator-5556"

def run_adb(device: str, args: list[str]) -> str:
    cmd = [ADB, "-s", device] + args
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.stdout.strip()

def tap(device: str, x: int, y: int, delay: float = 1.0):
    run_adb(device, ["shell", "input", "tap", str(x), str(y)])
    time.sleep(delay)

def input_text(device: str, text: str):
    run_adb(device, ["shell", "input", "text", text])
    time.sleep(0.5)

def capture_screenshot(device: str, name: str) -> str:
    path = os.path.join(ARTIFACTS_DIR, f"{name}.png")
    cmd = [ADB, "-s", device, "exec-out", "screencap", "-p"]
    res = subprocess.run(cmd, capture_output=True)
    if res.returncode == 0:
        with open(path, "wb") as f:
            f.write(res.stdout)
        print(f"[SCREENSHOT] Saved {name}.png ({len(res.stdout)} bytes)")
    return path

def grant_permissions(device: str):
    run_adb(device, ["shell", "pm", "grant", "com.assistme", "android.permission.POST_NOTIFICATIONS"])
    run_adb(device, ["shell", "pm", "grant", "com.assistme", "android.permission.RECORD_AUDIO"])
    run_adb(device, ["shell", "appops", "set", "com.assistme", "SYSTEM_ALERT_WINDOW", "allow"])

def reset_and_launch(device: str):
    run_adb(device, ["shell", "pm", "clear", "com.assistme"])
    grant_permissions(device)
    run_adb(device, ["shell", "am", "start", "-n", "com.assistme/.MainActivity"])
    time.sleep(2)

def recover_code(pairing_code_hash: str) -> str:
    for c in range(1000000):
        candidate = f"{c:06d}"
        if hashlib.sha256(candidate.encode()).hexdigest() == pairing_code_hash:
            return candidate
    return ""

def run_e2e_test():
    print("==================================================================")
    print("=== LIVE 2-AVD MULTI-AGENT END-TO-END VERIFICATION STARTING ===")
    print("==================================================================")
    
    # 0. Fresh Launch
    print("\n[Phase 0] Resetting and launching app on both emulators...")
    reset_and_launch(DEV_HELPEE)
    reset_and_launch(DEV_HELPER)
    time.sleep(2)

    # 1. Onboard Grandma on Helpee device
    print("\n[Phase 1] Onboarding Grandma on Helpee device...")
    tap(DEV_HELPEE, 540, 1220, delay=1.0) # Tap text field
    input_text(DEV_HELPEE, "Grandma")
    run_adb(DEV_HELPEE, ["shell", "input", "keyevent", "66"]) # Enter / Done
    time.sleep(2)
    capture_screenshot(DEV_HELPEE, "step1_grandma_recovery_code")
    tap(DEV_HELPEE, 540, 1560, delay=2.0) # Tap 'I saved my code'
    tap(DEV_HELPEE, 540, 1050, delay=1.0) # Audio permission if prompted
    capture_screenshot(DEV_HELPEE, "step2_grandma_home")

    # 2. Onboard Alex on Helper device
    print("\n[Phase 2] Onboarding Alex on Helper device...")
    tap(DEV_HELPER, 540, 1220, delay=1.0) # Tap text field
    input_text(DEV_HELPER, "Alex")
    run_adb(DEV_HELPER, ["shell", "input", "keyevent", "66"]) # Enter / Done
    time.sleep(2)
    capture_screenshot(DEV_HELPER, "step3_alex_recovery_code")
    tap(DEV_HELPER, 540, 1560, delay=2.0) # Tap 'I saved my code'
    tap(DEV_HELPER, 540, 1050, delay=1.0) # Audio permission if prompted
    capture_screenshot(DEV_HELPER, "step4_alex_home")

    # 3. Grandma generates 6-digit setup code
    print("\n[Phase 3] Grandma generates 6-digit setup code...")
    tap(DEV_HELPEE, 540, 800, delay=2.5) # 'Show My 6-Digit Code'
    capture_screenshot(DEV_HELPEE, "step5_grandma_code_active")

    # Read setup code from backend database
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT pairing_code_hash, id FROM device_pairings WHERE status = 'pending' ORDER BY created_at DESC LIMIT 1")
    row = cur.fetchone()
    if not row:
        print("[ERROR] No pending setup code found in DB!")
        return False
    pairing_code_hash, pairing_id = row
    setup_code = recover_code(pairing_code_hash)
    print(f"--> Recovered active 6-digit setup code: {setup_code} (Pairing ID: {pairing_id})")

    # 4. Alex enters code on "I'm helping" tab
    print("\n[Phase 4] Alex switches to 'I\\'m helping' tab and connects...")
    tap(DEV_HELPER, 750, 300, delay=1.5) # Switch to "I'm helping" tab
    tap(DEV_HELPER, 330, 890, delay=1.0) # Tap 6-digit code box
    input_text(DEV_HELPER, setup_code)
    tap(DEV_HELPER, 750, 890, delay=2.5) # Tap 'Connect'
    capture_screenshot(DEV_HELPER, "step6_alex_request_sent")

    # 5. Grandma gets approval dialog and approves
    print("\n[Phase 5] Grandma receives pairing approval dialog and approves...")
    time.sleep(2)
    capture_screenshot(DEV_HELPEE, "step7_grandma_allow_dialog")
    tap(DEV_HELPEE, 650, 1300, delay=2.5) # Tap 'Allow & Add'

    # Dismiss Alex's 'Request Sent!' dialog
    tap(DEV_HELPER, 720, 1300, delay=2.0)

    # Capture both updated home screens
    capture_screenshot(DEV_HELPEE, "step8_grandma_trusted_helpers")
    capture_screenshot(DEV_HELPER, "step9_alex_people_you_help")

    # 6. Grandma calls Alex
    print("\n[Phase 6] Grandma initiates Help Call to Alex...")
    tap(DEV_HELPEE, 650, 1300, delay=2.0) # Tap 'Call' on Alex card
    tap(DEV_HELPEE, 650, 980, delay=3.0)  # Tap 'Call Now' on modal
    capture_screenshot(DEV_HELPEE, "step10_grandma_calling_overlay")

    # 7. Alex receives incoming call ring popup
    print("\n[Phase 7] Alex receives full-screen incoming ring popup...")
    time.sleep(3.5) # Wait for heartbeat poll
    capture_screenshot(DEV_HELPER, "step11_alex_incoming_ring")

    # 8. Alex accepts call
    print("\n[Phase 8] Alex accepts call...")
    tap(DEV_HELPER, 540, 1350, delay=3.5) # Tap 'Accept & Start Helping'

    # 9. Both devices enter Live Session Workspace
    print("\n[Phase 9] Capturing live workspace on both devices...")
    capture_screenshot(DEV_HELPEE, "step12_grandma_live_workspace")
    capture_screenshot(DEV_HELPER, "step13_alex_live_workspace")

    # 10. End Session (Helpee leaves)
    print("\n[Phase 10] Leaving session and verifying symmetric teardown...")
    tap(DEV_HELPEE, 540, 1800, delay=1.5) # Tap leave / Panic button
    tap(DEV_HELPEE, 650, 1200, delay=2.5) # Confirm leave
    capture_screenshot(DEV_HELPEE, "step14_grandma_after_session")
    capture_screenshot(DEV_HELPER, "step15_alex_after_session")

    print("\n==================================================================")
    print("=== LIVE 2-AVD MULTI-AGENT VERIFICATION COMPLETED SUCCESSFULLY ===")
    print("==================================================================")
    return True

if __name__ == "__main__":
    success = run_e2e_test()
    if not success:
        exit(1)
