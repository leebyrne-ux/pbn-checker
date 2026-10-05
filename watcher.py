import os
import json
import requests

ROS_API_URL = "https://www.ros.ie/tis/pbn-status-web/pbnStatus/checkPbn"

def get_google_chat_webhook():
    return os.getenv("GOOGLE_CHAT_WEBHOOK")

def send_google_chat_notification(webhook_url, trailer, pbn, status_text):
    """Sends a formatted notification to Google Chat when a unit clears."""
    message = {
        "text": (
            f"🟢 *PBN CLEARANCE ALERT*\n\n"
            f"🚛 *Trailer / Reg:* {trailer}\n"
            f"📄 *PBN:* {pbn}\n"
            f"📍 *Status:* *{status_text}*\n\n"
            f"✅ Unit cleared and removed from active watchlist."
        )
    }
    try:
        res = requests.post(webhook_url, json=message, timeout=10)
        res.raise_for_status()
        print(f"Notification sent successfully for {trailer} ({pbn}).")
    except Exception as e:
        print(f"Failed to send Google Chat message: {e}")

def check_pbn_status(pbn_id):
    """Directly queries ROS PBN API endpoint using standard HTTP headers."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*"
    }
    
    payload = {"pbn": pbn_id}
    
    response = requests.post(ROS_API_URL, json=payload, headers=headers, timeout=15)
    response.raise_for_status()
    
    data = response.json()
    channel = data.get("channel") or data.get("status") or "Unknown"
    return str(channel).strip()

def main():
    webhook_url = get_google_chat_webhook()
    
    if not os.path.exists("watchlist.json"):
        print("watchlist.json not found. Exiting.")
        return

    with open("watchlist.json", "r") as f:
        watchlist = json.load(f)

    if not watchlist:
        print("Watchlist is empty. Nothing to check.")
        return

    remaining_watchlist = []

    for item in watchlist:
        pbn = item.get("pbn")
        trailer = item.get("trailer", "Unknown")

        try:
            print(f"Checking status for Trailer: {trailer} | PBN: {pbn}...")
            status = check_pbn_status(pbn)
            print(f"Result for {pbn}: {status}")

            if "Exit" in status or "EXIT" in status or "Exit the Port" in status:
                if webhook_url:
                    send_google_chat_notification(webhook_url, trailer, pbn, status)
                else:
                    print(f"Cleared! Status: {status} (Webhook URL missing).")
            else:
                remaining_watchlist.append(item)

        except Exception as err:
            print(f"Error checking PBN {pbn}: {err}")
            remaining_watchlist.append(item)

    with open("watchlist.json", "w") as f:
        json.dump(remaining_watchlist, f, indent=2)

if __name__ == "__main__":
    main()
