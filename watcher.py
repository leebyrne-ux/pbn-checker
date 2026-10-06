import os
import json
import time
import requests
from selenium import webdriver
from selenium.webdriver.common.by import By

ROS_URL = "https://www.ros.ie/tis/pbn-status-web/pbnStatus"

def get_google_chat_webhook():
    return os.getenv("GOOGLE_CHAT_WEBHOOK")

def main():
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.binary_location = "/usr/bin/chromium-browser"

    driver = webdriver.Chrome(options=options)

    try:
        print("Navigating to ROS PBN page...")
        driver.get(ROS_URL)
        time.sleep(6) # Allow full SPA load

        print("--- PAGE TITLE ---")
        print(driver.title)

        print("--- ALL INPUT ELEMENTS ON PAGE ---")
        inputs = driver.find_elements(By.TAG_NAME, "input")
        for inp in inputs:
            print(f"INPUT -> id: '{inp.get_attribute('id')}', name: '{inp.get_attribute('name')}', placeholder: '{inp.get_attribute('placeholder')}', class: '{inp.get_attribute('class')}'")

        print("--- ALL BUTTON ELEMENTS ON PAGE ---")
        buttons = driver.find_elements(By.TAG_NAME, "button")
        for btn in buttons:
            print(f"BUTTON -> id: '{btn.get_attribute('id')}', text: '{btn.text}', type: '{btn.get_attribute('type')}'")

        print("--- IFRAMES PRESENT ---")
        iframes = driver.find_elements(By.TAG_NAME, "iframe")
        print(f"Total iframes: {len(iframes)}")

    except Exception as e:
        print(f"Error during inspection: {e}")
    finally:
        driver.quit()

if __name__ == "__main__":
    main()
