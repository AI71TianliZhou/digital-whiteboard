# /// script
# requires-python = ">=3.14"
# dependencies = [
#     "httpx",
#     "pynacl",
# ]
# ///

import html
import os
import sys
from base64 import b64encode

import httpx
from nacl import encoding, public

# Setup Variables
TOKEN = os.environ.get("DONETICK_TOKEN")
USERNAME = os.environ.get("DONETICK_USERNAME")
PASSWORD = os.environ.get("DONETICK_PASSWORD")
GH_PAT = os.environ.get("GH_PAT")
REPO = os.environ.get("GITHUB_REPOSITORY")  # Automatically injected by GitHub Actions

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Origin": "https://app.donetick.com",
    "Referer": "https://app.donetick.com/",
}


def fetch_tasks(token):
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return httpx.get(
        "https://api.donetick.com/api/v1/sync/changes?since=-1", headers=headers
    )


def update_github_secret(new_secret_value):
    print("Updating GitHub Secret DONETICK_TOKEN...")
    gh_headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1. Fetch the repository public key
    pub_key_url = f"https://api.github.com/repos/{REPO}/actions/secrets/public-key"
    pub_key_resp = httpx.get(pub_key_url, headers=gh_headers)
    pub_key_resp.raise_for_status()
    key_data = pub_key_resp.json()

    # 2. Encrypt the secret using PyNaCl
    public_key = public.PublicKey(
        key_data["key"].encode("utf-8"), encoding.Base64Encoder
    )
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(new_secret_value.encode("utf-8"))
    encrypted_b64 = b64encode(encrypted).decode("utf-8")

    # 3. Upload the encrypted secret
    put_url = f"https://api.github.com/repos/{REPO}/actions/secrets/DONETICK_TOKEN"
    put_data = {"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]}
    httpx.put(put_url, headers=gh_headers, json=put_data).raise_for_status()
    print("Successfully updated GitHub Secret.")


# --- Execution Logic ---

response = fetch_tasks(TOKEN) if TOKEN else None

# If there's no token, or if the current token has expired (401 Unauthorized)
if not response or response.status_code == 401:
    print("Token is missing or expired. Authenticating via username/password...")

    if not USERNAME or not PASSWORD:
        sys.exit("Error: DONETICK_USERNAME or DONETICK_PASSWORD missing.")

    login_resp = httpx.post(
        "https://api.donetick.com/api/v1/auth/login",
        json={"username": USERNAME, "password": PASSWORD},
        headers=BASE_HEADERS,
    )
    login_resp.raise_for_status()

    TOKEN = login_resp.json().get("access_token")
    if not TOKEN:
        sys.exit("Error: Could not extract access_token from login response.")

    # Update the secret in GitHub so future runs use the cached token
    if GH_PAT and REPO:
        update_github_secret(TOKEN)
    else:
        print("Warning: GH_PAT missing. Could not cache the new token in Secrets.")

    # Re-fetch tasks with the new token
    response = fetch_tasks(TOKEN)

# Ensure the fetch was successful
response.raise_for_status()
data = response.json()
chores = data.get("changes", {}).get("chores", [])


# --- Sorting Logic ---
def sort_chores(chore):
    is_active = chore.get("isActive", True)
    status = chore.get("status", 0)

    if not is_active:
        return 3  # Completed
    if status == 1:
        return 0  # Ongoing
    if status == 2:
        return 1  # Started but paused
    return 2  # Not started (status 0)


chores.sort(key=sort_chores)

# --- HTML Generation ---
html_content = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Josh's digital whiteboard</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">
</head>
<body>
    <main class="container">
        <h1>Task List</h1>
        <article>
            <ul style="list-style: none; padding: 0;">
"""
matrix_gif = "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7e/Digital_rain_animation_big_letters_clear.gif/250px-Digital_rain_animation_big_letters_clear.gif?utm_source=commons.wikimedia.org&utm_campaign=index&utm_content=thumbnail"
for chore in chores:
    title = html.escape(chore.get("name", "Untitled Task"))
    is_active = chore.get("isActive", True)
    status = chore.get("status", 0)

    if not is_active:
        html_content += f'<li style="margin-bottom: 0.5rem;">🚢 <del>{title}</del></li>\n'
    elif status == 1:
        html_content += f'<li style="margin-bottom: 0.5rem;"><img src="{matrix_gif}" alt="▶️" width="20"> {title}</li>\n'
    elif status == 2:
        html_content += f'<li style="margin-bottom: 0.5rem;">📚 {title}</li>\n'
    else:
        html_content += f'<li style="margin-bottom: 0.5rem;">✨ {title}</li>\n'

html_content += """
            </ul>
        </article>
    </main>
</body>
</html>
"""

os.makedirs("public", exist_ok=True)
with open("public/index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully generated public/index.html with {len(chores)} tasks.")
