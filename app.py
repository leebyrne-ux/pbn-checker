import streamlit as st
import time
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

WATCHLIST_FILE = "watchlist.json"

st.set_page_config(page_title="Team PBN Checker", layout="centered")
st.title("🚛 Customs PBN Batch Checker")

dublin_tz = ZoneInfo("Europe/Dublin")
current_time = datetime.now(dublin_tz).strftime("%d/%m/%Y %H:%M:%S")
st.caption(f"🕒 Current Local Time: **{current_time}**")

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, "r") as f:
            return json.load(f)
    return []

def add_to_watchlist(pbn, trailer):
    watchlist = load_watchlist()
    if not any(item['pbn'] == pbn for item in watchlist):
        watchlist.append({"pbn": pbn, "trailer": trailer, "added_at": datetime.now(dublin_tz).strftime("%H:%M:%S")})
        with open(WATCHLIST_FILE, "w") as f:
            json.dump(watchlist, f, indent=2)
        st.toast(f"📌 Added {trailer} ({pbn}) to Google Chat Watchlist!", icon="✅")

raw_pbns = st.text_area("Paste PBNs Here", height=150, placeholder="FK44CM93\nAV99EC76").strip()

if st.button("Check PBNs", type="primary"):
    pbn_list = [p.strip() for p in raw_pbns.split("\n") if p.strip()]
    if not pbn_list:
        st.warning("Please paste at least one PBN.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()

        options = webdriver.ChromeOptions()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        try:
            driver = webdriver.Chrome(options=options)
            url = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"

            for idx, pbn in enumerate(pbn_list):
                status_text.text(f"Checking {idx + 1} of {len(pbn_list)}: {pbn}")
                try:
                    driver.get(url)
                    time.sleep(2)
                    inputs = driver.find_elements(By.TAG_NAME, "input")
                    if inputs:
                        inputs[0].clear()
                        inputs[0].send_keys(pbn)
                        inputs[0].send_keys(Keys.ENTER)
                        time.sleep(2)

                        page_text = driver.find_element(By.TAG_NAME, "body").text
                        page_text_upper = page_text.upper()
                        check_timestamp = datetime.now(dublin_tz).strftime("%H:%M:%S")

                        trailer_number = "Unknown"
                        if "TRAILER NUMBER" in page_text_upper:
                            lines = page_text.split('\n')
                            for i, line in enumerate(lines):
                                if "Vehicle Registration" in line or "Trailer Number" in line:
                                    if ":" in line:
                                        trailer_number = line.split(":")[-1].strip()
                                    elif i + 1 < len(lines):
                                        trailer_number = lines[i+1].strip()
                                    break

                        if "INVALID PBN" in page_text_upper:
                            status = "❌ INVALID PBN"
                        elif "NOT READY" in page_text_upper:
                            status = "⏳ Channel Not Ready"
                        elif "EXIT THE PORT" in page_text_upper or "EXIT" in page_text_upper:
                            status = "✅ Exit the Port"
                        elif "CALL TO CUSTOMS" in page_text_upper or "ORANGE" in page_text_upper:
                            status = "🛑 CALL TO CUSTOMS"
                        else:
                            status = "❓ Check Manually"
                    else:
                        status = "Error finding input box"
                        trailer_number = "N/A"
                        check_timestamp = datetime.now(dublin_tz).strftime("%H:%M:%S")

                except Exception as e:
                    status = f"Failed: {str(e)[:20]}"
                    trailer_number = "N/A"
                    check_timestamp = datetime.now(dublin_tz).strftime("%H:%M:%S")

                results.append({
                    "PBN ID": pbn,
                    "Trailer": trailer_number,
                    "Status": status,
                    "Checked At": check_timestamp
                })
                progress_bar.progress((idx + 1) / len(pbn_list))

            driver.quit()
            status_text.empty()
            progress_bar.empty()
            st.session_state["last_results"] = results
            st.success("All checks complete!")

        except Exception as global_e:
            st.error(f"Failed to start automated browser engine: {str(global_e)}")

# Display results table with Watchlist buttons
if "last_results" in st.session_state:
    st.write("---")
    st.subheader("Results")
    for res in st.session_state["last_results"]:
        col1, col2, col3, col4 = st.columns([2, 2, 3, 2])
        col1.write(f"**{res['PBN ID']}**")
        col2.write(res["Trailer"])
        col3.write(res["Status"])
        
        # Display "Watch" button for non-cleared units
        if "CALL TO CUSTOMS" in res["Status"] or "Not Ready" in res["Status"]:
            if col4.button("📌 Watch", key=res["PBN ID"]):
                add_to_watchlist(res["PBN ID"], res["Trailer"])

# Active Watchlist Section
watchlist = load_watchlist()
if watchlist:
    st.write("---")
    st.subheader("👁️ Active Watchlist (Auto-checking every 10 min)")
    for w in watchlist:
        st.info(f"🚚 **Trailer:** {w['trailer']} | **PBN:** {w['pbn']} | Added at {w.get('added_at', 'N/A')}")
