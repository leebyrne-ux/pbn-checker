import streamlit as st
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

st.set_page_config(page_title="Team PBN Checker", layout="centered")
st.title("🚛 Customs PBN Batch Checker")
st.write("Paste your list of PBNs below (one per line) and click Run.")

# Multi-line text box for pasting columns from Excel
raw_pbns = st.text_area("Paste PBNs Here", height=200, placeholder="FK44CM93\nAV99EC76\nCU23AW49").strip()

if st.button("Check PBNs", type="primary"):
    # Split text area lines into a cleaned list
    pbn_list = [p.strip() for p in raw_pbns.split("\n") if p.strip()]
    
    if not pbn_list:
        st.warning("Please paste at least one PBN.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Configure headless browser options for cloud execution
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        try:
            driver = webdriver.Chrome(options=options)
            url = "https://www.ros.ie/customs-roro-control-web/ros/freight/lookup"
            
            for idx, pbn in enumerate(pbn_list):
                status_text.text(f"Checking PBN {idx + 1} of {len(pbn_list)}: {pbn}")
                
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
                        
                        # Extract Trailer Number
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
                        
                        # Status Logic
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
                        
                except Exception as e:
                    status = f"Failed: {str(e)[:20]}"
                    trailer_number = "N/A"
                
                results.append({"PBN ID": pbn, "Trailer": trailer_number, "Status": status})
                progress_bar.progress((idx + 1) / len(pbn_list))
                
            driver.quit()
            
            # Clear progress indicators and display final result table
            status_text.empty()
            progress_bar.empty()
            st.success("All checks complete!")
            st.dataframe(results, use_container_width=True)
            
        except Exception as global_e:
            st.error(f"Failed to start automated browser engine: {str(global_e)}")