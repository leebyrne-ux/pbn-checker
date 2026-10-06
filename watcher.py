import os
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

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
    """Queries ROS portal using Selenium and returns body text."""
    driver.get(ROS_URL)
    
    # Wait for input field
    input_box = WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.ID, "pbn"))
    )
    input_box.clear()
    input_box.send_keys(pbn_id)
    
    submit_btn = driver.find_element(By.ID, "submitPbn")
    submit_btn.click()
    
    # Wait for status response container
    WebDriverWait(driver, 15).until(
        EC.presence_of_element_located((By.TAG_NAME, "body"))
    )
    time.sleep(2) # Brief delay for Angular rendering
    
    return driver.find_element(By.TAG_NAME, "body").text

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

    # Configure Headless Chrome with explicit binary location
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    # Point directly to the chromium binary installed by apt/snap
    options.binary_location = "/usr/bin/chromium-browser"

    driver = None
    remaining_watchlist = []

    try:
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(20)
        driver.implicitly_wait(10)

        for item in watchlist:
            pbn = item.get("pbn")
            trailer = item.get("trailer", "Unknown")

            try:
                print(f"Checking status for Trailer: {trailer} | PBN: {pbn}...")
                page_text = check_pbn_status(driver, pbn)
                text_upper = page_text.upper()

                if "EXIT THE PORT" in text_upper or "EXIT PORT" in text_upper or "EXIT" in text_upper:
                    print(f"✅ CLEARANCE DETECTED for {trailer} ({pbn})!")
                    if webhook_url:
                        send_google_chat_notification(webhook_url, trailer, pbn, "Exit the Port")
                    else:
                        print("Cleared status detected, but webhook URL is missing.")
                else:
                    print(f"⏳ Still pending or called for {trailer} ({pbn}).")
                    remaining_watchlist.append(item)

            except Exception as err:
                print(f"❌ Error checking PBN {pbn}: {err}")
                remaining_watchlist.append(item)

    except Exception as fatal_err:
        print(f"Fatal Chrome error: {fatal_err}")
        remaining_watchlist = watchlist

    finally:
        if driver:
            driver.quit()

    # Save updated watchlist
    with open("watchlist.json", "w") as f:
        json.dump(remaining_watchlist, f, indent=2)

if __name__ == "__main__":
    main()
