import os
import json
import streamlit as st
from datetime import datetime
from github import Github

# Page Configuration
st.set_page_config(
    page_title="Customs PBN Batch Checker",
    page_icon="🚛",
    layout="centered"
)

LOCAL_FILE = "watchlist.json"

# --- GITHUB SYNC FUNCTIONS ---

def get_github_repo():
    """Returns the PyGithub Repository instance if credentials exist in st.secrets."""
    token = st.secrets.get("GITHUB_TOKEN")
    repo_name = st.secrets.get("REPO_NAME")
    if token and repo_name:
        try:
            g = Github(token)
            return g.get_repo(repo_name)
        except Exception as e:
            st.error(f"GitHub Connection Error: {e}")
    return None

def load_watchlist():
    """Loads watchlist from GitHub if available, otherwise falls back to local watchlist.json."""
    repo = get_github_repo()
    if repo:
        try:
            contents = repo.get_contents("watchlist.json", ref="main")
            data = json.loads(contents.decoded_content.decode("utf-8"))
            with open(LOCAL_FILE, "w") as f:
                json.dump(data, f, indent=2)
            return data
        except Exception as e:
            st.warning(f"Could not fetch watchlist from GitHub ({e}). Reading local file.")
    
    if os.path.exists(LOCAL_FILE):
        try:
            with open(LOCAL_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_watchlist_and_commit(watchlist_data):
    """Saves watchlist locally and commits updated json directly to GitHub main branch."""
    with open(LOCAL_FILE, "w") as f:
        json.dump(watchlist_data, f, indent=2)

    repo = get_github_repo()
    if repo:
        try:
            contents = repo.get_contents("watchlist.json", ref="main")
            json_str = json.dumps(watchlist_data, indent=2)
            
            repo.update_file(
                path="watchlist.json",
                message="Streamlit: Update active watchlist",
                content=json_str,
                sha=contents.sha,
                branch="main"
            )
            st.toast("Saved and committed to GitHub!", icon="🚀")
        except Exception as e:
            st.error(f"Failed to commit to GitHub: {e}")
    else:
        st.warning("GITHUB_TOKEN or REPO_NAME missing in secrets. Saved locally only.")

# --- APP UI LOGIC ---

st.title("Customs PBN Batch Checker")
st.caption(f"Current Local Time: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

current_list = load_watchlist()

st.subheader("Add PBNs to Watchlist")

with st.form("add_pbn_form", clear_on_submit=True):
    raw_pasted_text = st.text_area(
        "Paste PBNs and Trailer Regs Here",
        placeholder="Format options:\nRX23VN92\nGTC415 RX23VN92\nGTC372, ER47AF49",
        height=120
    )
    submit_button = st.form_submit_button("Add to Watchlist")

if submit_button and raw_pasted_text.strip():
    new_items = []
    lines = raw_pasted_text.strip().split("\n")
    now_str = datetime.now().strftime("%H:%M:%S")

    for line in lines:
        parts = line.replace(",", " ").split()
        if len(parts) == 1:
            new_items.append({
                "pbn": parts[0].strip().upper(),
                "trailer": "Unknown",
                "added_at": now_str
            })
        elif len(parts) >= 2:
            new_items.append({
                "trailer": parts[0].strip().upper(),
                "pbn": parts[1].strip().upper(),
                "added_at": now_str
            })

    if new_items:
        existing_pbns = {item.get("pbn") for item in current_list}
        added_count = 0
        
        for item in new_items:
            if item["pbn"] not in existing_pbns:
                current_list.append(item)
                added_count += 1
        
        if added_count > 0:
            save_watchlist_and_commit(current_list)
            st.rerun()
        else:
            st.info("All entered PBNs are already on the watchlist.")

st.divider()

st.subheader("Active Watchlist (Auto-checking every 15 min)")

if not current_list:
    st.info("Watchlist is currently empty. Add PBNs above to start automated monitoring.")
else:
    for idx, item in enumerate(current_list):
        trailer =
