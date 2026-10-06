import os
import json
import requests

# ROS PBN status endpoint
ROS_URL = "https://www.ros.ie/tis/pbn-status-web/pbnStatus"

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
    """Queries ROS PBN status page using form POST."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    })
    
    # First request to get session cookies
    session.get(ROS_URL, timeout=10)
    
    # Form submission
    payload = {"pbn": pbn_id}
    response = session.post(f"{ROS_URL}/checkPbn", data=payload, timeout=15)
    response.raise_for_status()
    
    return response.text

def main():
    webhook_url = get_google_chat_webhook()
    if not webhook_url:
        print("WARNING: GOOGLE_CHAT_WEBHOOK environment variable is not set!")
    
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
            raw_response = check_pbn_status(pbn)
            
            # Print response preview for debugging
            print(f"Response length: {len(raw_response)} chars")

            # Check if clearance text appears in response
            response_upper = raw_response.upper()
            
            if "EXIT THE PORT" in response_upper or "EXIT_THE_PORT" in response_upper or "EXIT" in response_upper:
                print(f"✅ CLEARANCE DETECTED for {trailer} ({pbn})!")
                if webhook_url:
                    send_google_chat_notification(webhook_url, trailer, pbn, "Exit the Port")
                else:
                    print("Cleared status detected, but webhook URL is missing.")
            else:
                print(f"⏳ Still pending/called for {trailer} ({pbn}).")
                remaining_watchlist.append(item)

        except Exception as err:
            print(f"❌ Error checking PBN {pbn}: {err}")
            # Keep on list if temporary network error
            remaining_watchlist.append(item)

    # Save updated watchlist (cleared items removed)
    with open("watchlist.json", "w") as f:
        json.dump(remaining_watchlist, f, indent=2)

if __name__ == "__main__":
    main()
