import os
import json
import time
import shutil
import traceback

import streamlit as st
from datetime import datetime
from github import Github

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="PBN Checker",
    page_icon="🚚",
    layout="centered"
)


# ============================================================
# CONFIGURATION
# ============================================================

FILE = "watchlist.json"

ROS_URL = (
    "https://www.ros.ie/"
    "customs-roro-control-web/"
    "ros/pbn/status"
)

PAGE_LOAD_TIMEOUT = 45
RESULT_WAIT_TIMEOUT = 30


# ============================================================
# GITHUB
# ============================================================

def get_repo():
    tok = st.secrets.get("GITHUB_TOKEN")
    name = st.secrets.get("REPO_NAME")

    if tok and name:
        try:
            return Github(tok).get_repo(name)
        except Exception as e:
            st.error(f"GitHub Error: {e}")

    return None


def load_data():
    """
    Load watchlist from GitHub first.
    Fall back to local watchlist.json if GitHub is unavailable.
    """

    repo = get_repo()

    if repo:
        try:
            res = repo.get_contents(FILE, ref="main")

            raw = res.decoded_content.decode("utf-8")
            data = json.loads(raw)

            # Keep local copy in sync.
            with open(FILE, "w", encoding="utf-8") as f:
                json.dump(
                    data,
                    f,
                    indent=2,
                    ensure_ascii=False
                )

            return data

        except Exception:
            pass

    if os.path.exists(FILE):
        try:
            with open(FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    return []


def save_data(data):
    """
    Save watchlist locally and synchronise it to GitHub.
    """

    with open(FILE, "w", encoding="utf-8") as f:
        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )

    repo = get_repo()

    if repo:
        try:
            res = repo.get_contents(FILE, ref="main")

            body = json.dumps(
                data,
                indent=2,
                ensure_ascii=False
            )

            repo.update_file(
                path=FILE,
                message="Update watchlist",
                content=body,
                sha=res.sha,
                branch="main"
            )

            st.toast(
                "Saved to GitHub!",
                icon="🚀"
            )

        except Exception as e:
            st.error(f"Sync error: {e}")


# ============================================================
# BROWSER
# ============================================================

def find_browser():
    """
    Find Chrome/Chromium in Streamlit's environment.
    """

    possible_paths = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/snap/bin/chromium",
    ]

    for path in possible_paths:
        if path and os.path.exists(path):
            return path

    return None


def create_driver():
    """
    Create a headless Chrome/Chromium Selenium driver.
    """

    options = webdriver.ChromeOptions()

    browser_path = find_browser()

    if browser_path:
        options.binary_location = browser_path

    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")

    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--disable-default-apps")
    options.add_argument("--disable-sync")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    options.add_argument(
        "--user-agent="
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/155.0.0.0 Safari/537.36"
    )

    driver = webdriver.Chrome(options=options)

    driver.set_page_load_timeout(
        PAGE_LOAD_TIMEOUT
    )

    return driver


# ============================================================
# REVENUE PAGE HELPERS
# ============================================================

def find_pbn_input(driver):
    """
    Locate the visible PBN input on Revenue's PBN Status page.
    """

    selectors = [
        "input[name*='pbn' i]",
        "input[id*='pbn' i]",
        "input[placeholder*='PBN' i]",
    ]

    for selector in selectors:

        try:
            elements = driver.find_elements(
                By.CSS_SELECTOR,
                selector
            )

            for element in elements:

                if (
                    element.is_displayed()
                    and element.is_enabled()
                ):
                    return element

        except Exception:
            pass

    # Fallback to visible text input.
    try:

        elements = driver.find_elements(
            By.XPATH,
            "//input[not(@type='hidden')]"
        )

        for element in elements:

            if (
                element.is_displayed()
                and element.is_enabled()
            ):
                return element

    except Exception:
        pass

    return None


def find_check_button(driver):
    """
    Locate Revenue's 'Check Status' button.
    """

    xpath = (
        "//button[contains("
        "translate(normalize-space(.), "
        "'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
        "'abcdefghijklmnopqrstuvwxyz'), "
        "'check status'"
        ")]"
    )

    try:

        return WebDriverWait(
            driver,
            RESULT_WAIT_TIMEOUT
        ).until(
            EC.element_to_be_clickable(
                (By.XPATH, xpath)
            )
        )

    except Exception:
        return None


def normalise_text(text):
    return " ".join(
        text.upper().split()
    )


def get_status_from_page(text):
    """
    Interpret the Revenue PBN Status response.

    The important status for this app is CALL TO CUSTOMS.

    Other statuses are retained as informational results.
    """

    upper = normalise_text(text)

    # Most important first.
    if "CALL TO CUSTOMS" in upper:
        return "CALL TO CUSTOMS"

    if "CALLED TO CUSTOMS" in upper:
        return "CALL TO CUSTOMS"

    if "EXIT THE PORT" in upper:
        return "EXIT THE PORT"

    if "CHECKED IN" in upper:
        return "CHECKED IN"

    if "PROCEED" in upper:
        return "PROCEED"

    # Try to identify a generic status line.
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    for index, line in enumerate(lines):

        upper_line = line.upper()

        if upper_line == "PBN STATUS":

            if index + 1 < len(lines):
                return lines[index + 1]

    return "UNKNOWN"


# ============================================================
# CHECK ONE PBN
# ============================================================

def check_pbn(driver, pbn):
    """
    Check one PBN on Revenue.

    Returns:
        {
            "pbn": "...",
            "status": "...",
            "raw_text": "..."
        }
    """

    driver.get(ROS_URL)

    # Wait for page.
    WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    ).until(
        lambda d:
        d.execute_script(
            "return document.readyState"
        ) == "complete"
    )

    # Find PBN input.
    pbn_input = WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    ).until(
        lambda d: find_pbn_input(d)
    )

    if not pbn_input:
        raise RuntimeError(
            "Could not find PBN input."
        )

    pbn_input.click()
    pbn_input.clear()
    pbn_input.send_keys(pbn)

    # Find Check Status button.
    button = find_check_button(driver)

    if not button:
        raise RuntimeError(
            "Could not find 'Check Status' button."
        )

    # JavaScript click is slightly more robust with ROS.
    driver.execute_script(
        "arguments[0].click();",
        button
    )

    # --------------------------------------------------------
    # Wait for Revenue result
    # --------------------------------------------------------

    def result_loaded(d):

        try:
            text = d.find_element(
                By.TAG_NAME,
                "body"
            ).text

            upper = normalise_text(text)

            indicators = [
                "CALL TO CUSTOMS",
                "CALLED TO CUSTOMS",
                "EXIT THE PORT",
                "CHECKED IN",
                "PBN STATUS",
                "PBN ID",
            ]

            return any(
                indicator in upper
                for indicator in indicators
            )

        except Exception:
            return False

    WebDriverWait(
        driver,
        RESULT_WAIT_TIMEOUT
    ).until(result_loaded)

    # Give Revenue a moment to finish rendering.
    time.sleep(0.5)

    body_text = driver.find_element(
        By.TAG_NAME,
        "body"
    ).text.strip()

    status = get_status_from_page(
        body_text
    )

    return {
        "pbn": pbn,
        "status": status,
        "raw_text": body_text,
    }


# ============================================================
# PARSE INPUT
# ============================================================

def parse_pbn_input(txt):
    """
    Accept:

        RX23VN92

    or:

        GTC415 RX23VN92

    or:

        GTC415,RX23VN92

    Returns a list of:
        {
            "trailer": "...",
            "pbn": "..."
        }
    """

    results = []

    for line in txt.strip().splitlines():

        line = line.strip()

        if not line:
            continue

        parts = (
            line
            .replace(",", " ")
            .split()
        )

        if len(parts) == 1:

            pbn = parts[0].strip().upper()

            results.append({
                "trailer": "Unknown",
                "pbn": pbn,
            })

        else:

            trailer = parts[0].strip().upper()
            pbn = parts[1].strip().upper()

            results.append({
                "trailer": trailer,
                "pbn": pbn,
            })

    return results


# ============================================================
# SESSION STATE
# ============================================================

if "check_results" not in st.session_state:
    st.session_state.check_results = []

if "check_errors" not in st.session_state:
    st.session_state.check_errors = []


# ============================================================
# PAGE HEADER
# ============================================================

st.title("Customs PBN Batch Checker")

st.caption(
    f"Time: "
    f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
)


# ============================================================
# CHECK NEW PBNS
# ============================================================

st.subheader("Check New PBNs")

st.write(
    "Enter the PBNs you want to check. "
    "You can optionally include the trailer/reg."
)

with st.form(
    "check_form",
    clear_on_submit=False
):

    txt = st.text_area(
        "PBNs and Trailers",
        placeholder=(
            "RX23VN92\n"
            "GTC415 RX23VN92\n"
            "GTC372 ER47AF49"
        ),
        height=150,
    )

    check_btn = st.form_submit_button(
        "🔎 Check PBNs"
    )


# ============================================================
# RUN CHECKS
# ============================================================

if check_btn:

    if not txt.strip():

        st.warning(
            "Please enter at least one PBN."
        )

    else:

        entries = parse_pbn_input(txt)

        if not entries:

            st.warning(
                "No valid PBNs found."
            )

        else:

            results = []
            errors = []

            driver = None

            try:

                with st.spinner(
                    "Checking Revenue ROS..."
                ):

                    driver = create_driver()

                    for entry in entries:

                        pbn = entry["pbn"]
                        trailer = entry["trailer"]

                        try:

                            result = check_pbn(
                                driver,
                                pbn
                            )

                            result["trailer"] = trailer

                            results.append(
                                result
                            )

                        except Exception as e:

                            errors.append({
                                "pbn": pbn,
                                "trailer": trailer,
                                "error": str(e),
                            })

            except Exception as e:

                st.error(
                    "Could not start the Revenue checker."
                )

                st.code(
                    traceback.format_exc()
                )

            finally:

                if driver:

                    try:
                        driver.quit()
                    except Exception:
                        pass

            st.session_state.check_results = results
            st.session_state.check_errors = errors


# ============================================================
# DISPLAY CHECK RESULTS
# ============================================================

if st.session_state.check_results:

    st.divider()

    st.subheader("PBN Check Results")

    current_watchlist = load_data()

    watched_pbns = {
        str(item.get("pbn", "")).upper()
        for item in current_watchlist
    }

    for index, result in enumerate(
        st.session_state.check_results
    ):

        pbn = result["pbn"]
        trailer = result.get(
            "trailer",
            "Unknown"
        )
        status = result["status"]

        st.markdown(
            f"### 🚛 {trailer} — {pbn}"
        )

        if status == "CALL TO CUSTOMS":

            st.success(
                "🔴 CALL TO CUSTOMS"
            )

            st.write(
                "This PBN can now be added to "
                "the automatic watchlist."
            )

            if pbn in watched_pbns:

                st.info(
                    "✅ Already on the active watchlist."
                )

            else:

                if st.button(
                    "➕ Add to Watchlist",
                    key=f"add_watch_{index}_{pbn}"
                ):

                    # Reload immediately before saving.
                    # This prevents overwriting a newer
                    # watchlist entry created elsewhere.
                    items = load_data()

                    existing = {
                        str(
                            item.get("pbn", "")
                        ).upper()
                        for item in items
                    }

                    if pbn in existing:

                        st.info(
                            "This PBN is already on "
                            "the watchlist."
                        )

                    else:

                        timestamp = datetime.now().strftime(
                            "%H:%M:%S"
                        )

                        items.append({
                            "pbn": pbn,
                            "trailer": trailer,
                            "added_at": timestamp,
                        })

                        save_data(items)

                        st.success(
                            f"✅ {pbn} added to watchlist."
                        )

                        # Update local session result so
                        # the button becomes unavailable
                        # after rerun.
                        st.rerun()

        elif status == "EXIT THE PORT":

            st.success(
                "🟢 EXIT THE PORT"
            )

            st.write(
                "This PBN has already cleared."
            )

        elif status == "CHECKED IN":

            st.info(
                "🔵 CHECKED IN"
            )

            st.write(
                "Not currently showing "
                "Call to Customs."
            )

        else:

            st.warning(
                f"⚠️ Status: {status}"
            )

        # Expandable raw Revenue response.
        with st.expander(
            "Show Revenue response"
        ):

            st.text(
                result.get(
                    "raw_text",
                    ""
                )
            )

        st.divider()


# ============================================================
# DISPLAY ERRORS
# ============================================================

if st.session_state.check_errors:

    st.subheader("⚠️ Checks with errors")

    for error in st.session_state.check_errors:

        st.error(
            f"{error['trailer']} — "
            f"{error['pbn']}: "
            f"{error['error']}"
        )


# ============================================================
# ACTIVE WATCHLIST
# ============================================================

st.subheader("Active Watchlist")

items = load_data()

if not items:

    st.info(
        "Watchlist is empty."
    )

else:

    for idx, item in enumerate(items):

        tr = item.get(
            "trailer",
            "Unknown"
        )

        pb = item.get(
            "pbn",
            "N/A"
        )

        ts = item.get(
            "added_at",
            "N/A"
        )

        c1, c2 = st.columns(
            [5, 1]
        )

        with c1:

            st.info(
                f"Trailer: {tr} | "
                f"PBN: {pb} | "
                f"Added: {ts}"
            )

        with c2:

            if st.button(
                "Delete",
                key=f"del_{idx}_{pb}"
            ):

                items.pop(idx)

                save_data(items)

                st.rerun()


# ============================================================
# REFRESH
# ============================================================

if st.button(
    "🔄 Sync / Refresh"
):

    st.rerun()
