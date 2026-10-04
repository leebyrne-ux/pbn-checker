import os
import json
import time
import requests
from zoneinfo import ZoneInfo
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

WATCHLIST_FILE = "watchlist.json"
WEBHOOK_URL = os.environ.get("GOOGLE_CHAT_WEBHOOK")

def send_chat_alert(pbn, trailer, status):
    if not WEBHOOK_URL:
        print("No Webhook URL found in environment variables.")
        return
        
    dublin_tz = ZoneInfo("Europe/Dublin")
    cleared_time = datetime.now(dublin_tz).strftime("%H:%M:%S")

    payload = {
        "text": f"🎉 *CUSTOMS CLEARANCE ALERT*\n\n"
                f"• *Trailer:* `{trailer}`\n"
                f"• *PBN ID:* `{pbn}`\n"
                f"• *Status:* ✅ {status}\n"
                f"• *Cleared At:* {cleared_time}\n\n"
                f"🚚 *This unit is clear to exit the port!*"
    }
    try:
        res = requests.post(WEBHOOK_URL, json=payload)
        print(f"Alert sent for {pbn}: {res.status_code}")
    except Exception as e:
        print(f"Failed to send webhook: {e}")

def run_watcher():
    if not os.path.exists(WATCHLIST_FILE):
        print("No watchlist file found. Nothing to check.")
        return

    with open(WATCHLIST_FILE, "r") as f:
        watchlist = json.load(f)

    if not watchlist:
        print("Watchlist is empty.")
        return

    print(f"Checking {len(watchlist)} PBNs on watchlist...")

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")

    driver = webdriver.Chrome(options=options)
    url = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"

    updated_watchlist = []
    
    for item in watchlist:
        pbn = item["pbn"]
        trailer = item.get("trailer", "Unknown")
        
        try:
            driver.get(url)
            time.sleep(2)
            inputs = driver.find_elements(By.TAG_NAME, "input")
            
            if inputs:
                inputs[0].clear()
                inputs[0].send_keys(pbn)
                inputs[0].send_keys(Keys.ENTER)
                time.sleep(2)

                page_text = driver.find_element(By.TAG_NAME, "body").text.upper()

                if "EXIT THE PORT" in page_text or "EXIT" in page_text:
                    print(f"PBN {pbn} (Trailer: {trailer}) HAS CLEARED!")
                    send_chat_alert(pbn, trailer, "Exit the Port")
                    # Do NOT add to updated_watchlist, so it gets removed!
                else:
                    print(f"PBN {pbn} still waiting...")
                    updated_watchlist.append(item)
            else:
                updated_watchlist.append(item)

        except Exception as e:
            print(f"Error checking {pbn}: {e}")
            updated_watchlist.append(item)

    driver.quit()

    # Save updated list (removes cleared units)
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(updated_watchlist, f, indent=2)

if __name__ == "__main__":
    run_watcher()