import os
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ROS Portal URL
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

def check_pbn_status(driver, pbn_id):
    """Queries ROS portal for a specific PBN and returns the channel status text."""
    driver.get(ROS_URL)
    
    # Locate and submit PBN input field
    input_box = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "pbn"))
    )
    input_box.clear()
    input_box.send_keys(pbn_id)
    
    submit_btn = driver.find_element(By.ID, "submitPbn")
    submit_btn.click()
    
    # Wait for status response
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.CLASS_NAME, "status-box"))
    )
    
    # Extract channel text (e.g. "Exit the Port" or "Call to Customs")
    status_element = driver.find_element(By.CLASS_NAME, "status-box")
    return status_element.text.strip()

def main():
    webhook_url = get_google_chat_webhook()
    
    # Load watchlist file
    if not os.path.exists("watchlist.json"):
        print("watchlist.json not found. Exiting.")
        return

    with open("watchlist.json", "r") as f:
        watchlist = json.load(f)

    if not watchlist:
        print("Watchlist is empty. Nothing to check.")
        return

    # Configure headless Chrome
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.binary_location = "/usr/bin/chromium-browser"

    driver = None
    remaining_watchlist = []

    try:
        driver = webdriver.Chrome(options=options)
        
        # Prevent Chrome from hanging indefinitely on network stalls
        driver.set_page_load_timeout(30)
        driver.implicitly_wait(10)

        for item in watchlist:
            pbn = item.get("pbn")
            trailer = item.get("trailer", "Unknown")

            try:
                print(f"Checking status for Trailer: {trailer} | PBN: {pbn}...")
                status = check_pbn_status(driver, pbn)
                print(f"Result for {pbn}: {status}")

                # Check if cleared
                if "Exit the Port" in status:
                    if webhook_url:
                        send_google_chat_notification(webhook_url, trailer, pbn, status)
                    else:
                        print("Cleared! (Google Chat Webhook secret missing, alert skipped).")
                else:
                    # Keep on watchlist if still pending/called
                    remaining_watchlist.append(item)

            except Exception as item_err:
                print(f"Error checking PBN {pbn}: {item_err}")
                # Retain item on list if lookup failed due to network error
                remaining_watchlist.append(item)

    except Exception as driver_err:
        print(f"Fatal driver or ROS connection error: {driver_err}")
        # Keep original watchlist intact if whole run crashes
        remaining_watchlist = watchlist

    finally:
        if driver:
            driver.quit()

    # Save updated watchlist (cleared items removed)
    with open("watchlist.json", "w") as f:
        json.dump(remaining_watchlist, f, indent=2)

if __name__ == "__main__":
    main()
