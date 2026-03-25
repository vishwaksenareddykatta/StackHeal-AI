# CLIENT VERSION 3.0 (MacBook Device Client)
import os
import time
import requests
import threading
from STT import recognize_and_verify, SpeechRecognition
from testttss import TextToSpeech as speak

# ==========================================================
# CONFIG
# ==========================================================
SERVER = "https://marvin.nexvarkindustries.com"
CHAT_URL = f"{SERVER}/chat"
LOGIN_URL = f"{SERVER}/device/login"
HEARTBEAT_URL = f"{SERVER}/device/heartbeat"
ANNOUNCE_URL = f"{SERVER}/device/announcements"


USERNAME = "mac_user"
PASSWORD = "MACBOOK_Marvin@123$"
WAKE_WORD = "marvin"

# These will be filled after login
DEVICE_ID = None
TOKEN = None



def disable_touchpad():
    # Disable internal trackpad
    os.system("sudo defaults write /Library/Preferences/com.apple.AppleMultitouchTrackpad TrackpadThreeFingerDrag -bool false")
# ==========================================================
# DEVICE LOGIN
# ==========================================================
def device_login():
    global DEVICE_ID, TOKEN

    print("🔐 Logging into Marvin device system...")

    try:
        r = requests.post(LOGIN_URL, json={
            "username": USERNAME,
            "password": PASSWORD
        })
        data = r.json()

        if "error" in data:
            print("❌ Login failed:", data["error"])
            return False

        DEVICE_ID = data["device_id"]
        TOKEN = data["token"]

        print(f"✅ Device logged in as {DEVICE_ID}")
        return True

    except Exception as e:
        print("❌ Login exception:", e)
        return False


# ==========================================================
# HEARTBEAT THREAD
# ==========================================================
def heartbeat_loop():
    global DEVICE_ID, TOKEN
    print("❤️ Heartbeat started.")

    while True:
        try:
            requests.post(HEARTBEAT_URL, json={
                "device_id": DEVICE_ID,
                "token": TOKEN
            })
        except:
            pass

        time.sleep(5)


# ==========================================================
# SEND TEXT TO SERVER
# ==========================================================
def send_to_server(command: str):
    global TOKEN
    """Send full sentence containing 'marvin' and speak response."""
    try:
        response = requests.post(
            CHAT_URL,
            json={"message": command},
            headers={"Authorization": f"Bearer {TOKEN}"},   # <-- FIXED
            timeout=10
        )
        response.raise_for_status()
        reply = response.json().get("reply", "No reply from server.")
    except Exception as e:
        reply = f"Server Error: {e}"

    print(f"Marvin: {reply}")
    speak(reply)


# ==========================================================
# Poll Announcements
# ==========================================================

def poll_announcements():
    global TOKEN
    while True:
        if TOKEN:
            try:
                r = requests.get(ANNOUNCE_URL, headers={"Authorization": f"Bearer {TOKEN}"}, timeout=5)
                data = r.json()
                for msg in data.get("announcements", []):
                    print(f"📢 Announcement: {msg}")
                    # Speak announcement
                    speak(msg)
            except:
                pass
        time.sleep(10)  # poll every 10 seconds (adjust as needed)


# ==========================================================
# MAIN LOOP
# ==========================================================
def main():
    print("\n🔊 Marvin Mac Client Online.\n")

    # Step 1: Login device
    if not device_login():
        print("⚠ Cannot continue without device login")
        return

    # Step 2: Start heartbeat in background
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    # Step 3: Choose input mode
    while True:
        mode = input("Choose input mode: v for voice, t for text: ").strip().lower()
        if mode in ['v', 't']:
            break
        print("Invalid choice. Please enter 'v' or 't'.")

    input_mode = 'voice' if mode == 'v' else 'text'

    # Step 4: Input loop
    while True:
        if input_mode == 'voice':
            audio = recognize_and_verify()
            if not audio:
                continue

            text = SpeechRecognition(audio)
            if not text:
                continue

            if WAKE_WORD.lower() in text.lower():
                print(f"Mr.Katta: {text}")
                send_to_server(text)
        else:  # text mode
            text = input("Mr. Katta: ").strip()
            if not text:
                continue

            print(f"Mr.Katta: {text}")
            send_to_server(text)


# ==========================================================
# Entry point
# ==========================================================
if __name__ == "__main__":
    # Start polling in background
    import threading
    threading.Thread(target=poll_announcements, daemon=True).start()
    main()
    disable_touchpad()


def stop_client():
    print("Stopping marvin client...")

    exit(0)