import os
import json
import streamlit as st
from datetime import datetime
from github import Github

# Page Configuration
st.set_page_config(
    page_title="Customs PBN Batch Checker",
    page_icon="🚚",
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
            # Save local copy in container
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
    # 1. Save local copy in Streamlit memory
    with open(LOCAL_FILE, "w") as f:
        json.dump(watchlist_data, f, indent=2)

    # 2. Push commit to GitHub
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
            st.toast("✅ Saved & committed to GitHub!", icon="🚀")
        except Exception as e:
            st.error(f"Failed to commit to GitHub: {e}")
    else:
        st.warning("GITHUB_TOKEN or REPO_NAME missing in secrets. Saved locally only.")

# --- APP UI & LOGIC ---

st.title("🚚 Customs PBN Batch Checker")
st.caption(f"🕒 Current Local Time: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")

# Load current active list
current_list = load_watchlist()

# Section 1: Add new PBNs
st.subheader("Add PBNs to Watchlist")

with st.form("add_pbn_form", clear_
