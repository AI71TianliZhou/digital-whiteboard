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
from time import time

import httpx
from nacl import encoding, public

# Setup Variables
TOKEN = os.environ.get("DONETICK_TOKEN")
USERNAME = os.environ.get("DONETICK_USERNAME")
PASSWORD = os.environ.get("DONETICK_PASSWORD")
GH_PAT = os.environ.get("GH_PAT")
REPO = os.environ.get("GITHUB_REPOSITORY")

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Origin": "https://app.donetick.com",
    "Referer": "https://app.donetick.com/",
}


def fetch_tasks(token):
    headers = BASE_HEADERS.copy()
    headers["Authorization"] = f"Bearer {token}"
    return httpx.get("https://api.donetick.com/api/v1/sync/changes?since=-1", headers=headers)


def update_github_secret(new_secret_value):
    print("Updating GitHub Secret DONETICK_TOKEN...")
    gh_headers = {
        "Authorization": f"Bearer {GH_PAT}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    pub_key_url = f"https://api.github.com/repos/{REPO}/actions/secrets/public-key"
    pub_key_resp = httpx.get(pub_key_url, headers=gh_headers)
    pub_key_resp.raise_for_status()
    key_data = pub_key_resp.json()

    public_key = public.PublicKey(key_data["key"].encode("utf-8"), encoding.Base64Encoder)
    sealed_box = public.SealedBox(public_key)
    encrypted = sealed_box.encrypt(new_secret_value.encode("utf-8"))
    encrypted_b64 = b64encode(encrypted).decode("utf-8")

    put_url = f"https://api.github.com/repos/{REPO}/actions/secrets/DONETICK_TOKEN"
    put_data = {"encrypted_value": encrypted_b64, "key_id": key_data["key_id"]}
    httpx.put(put_url, headers=gh_headers, json=put_data).raise_for_status()
    print("Successfully updated GitHub Secret.")


# --- Execution Logic ---

response = fetch_tasks(TOKEN) if TOKEN else None

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

    if GH_PAT and REPO:
        update_github_secret(TOKEN)
    else:
        print("Warning: GH_PAT missing. Could not cache the new token in Secrets.")

    response = fetch_tasks(TOKEN)

response.raise_for_status()
data = response.json()
chores = data.get("changes", {}).get("chores", [])


# --- Build structured chore objects ---
chore_objects = []
for chore in chores:
    chore_objects.append(
        {
            "name": chore.get("name", "Untitled Task"),
            "updatedAt": chore.get("updatedAt", ""),
            "status": chore.get("status", 0),
            "priority": chore.get("priority", 0) or 0,
            "isActive": chore.get("isActive", True),
        }
    )


def active_group(chore):
    """Primary sort: ongoing < paused < not-started < completed."""
    if not chore["isActive"]:
        return 99
    if chore["status"] == 1:
        return 0
    if chore["status"] == 2:
        return 1
    return 2


# Stable sort in reverse precedence: tertiary -> secondary -> primary
chore_objects.sort(key=lambda c: c["updatedAt"], reverse=True)
chore_objects.sort(key=lambda c: c["priority"] if c["priority"] > 0 else 99)
chore_objects.sort(key=active_group)

# --- HTML Generation ---

matrix_gif = "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7e/Digital_rain_animation_big_letters_clear.gif/250px-Digital_rain_animation_big_letters_clear.gif"

active_tasks = [c for c in chore_objects if c["isActive"]]
completed_tasks = [c for c in chore_objects if not c["isActive"]]

html_parts = [
    "<!DOCTYPE html>",
    '<html lang="en" data-theme="dark">',
    "<head>",
    '    <meta charset="UTF-8">',
    '    <meta name="viewport" content="width=device-width, initial-scale=1.0">',
    "    <title>Josh's digital whiteboard</title>",
    '    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@picocss/pico@2/css/pico.min.css">',
    '    <link rel="preconnect" href="https://fonts.googleapis.com">',
    '    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
    '    <link href="https://fonts.googleapis.com/css2?family=Caveat:wght@400;600;700&family=Mr+Dafoe&family=Rock+Salt&display=swap" rel="stylesheet">',
    "    <style>",
    "        :root {",
    "            --pico-background-color: #141e14;",
    "            --pico-color: #f4ebd9;",
    "            --pico-text-color: #f4ebd9;",
    "            --pico-card-background-color: #1f3025;",
    "            --pico-card-border-color: #2d4536;",
    "            --pico-primary: #a8d5a2;",
    "            --pico-primary-hover: #b8e5b2;",
    "            --pico-primary-background: #2a4a2a;",
    "            --pico-border-color: #2d4536;",
    "            --pico-del-color: #7a7a6e;",
    "            --pico-h1-color: #f4ebd9;",
    "            --pico-accordion-border-color: #2d4536;",
    '            --pico-font-family: "Caveat", cursive;',
    "            --pico-font-size: clamp(1.2rem, 2.5vw, 2rem);",
    "            --pico-line-height: 1.5;",
    "        }",
    "        *,",
    "        body,",
    "        h1,",
    "        h2,",
    "        h3,",
    "        button,",
    "        input {",
    "            text-shadow: 0 0 1px rgba(255, 255, 255, 0.3), 0 0 2px rgba(255, 255, 255, 0.2);",
    "        }",
    "        html, body {",
    "            min-height: 100vh;",
    "        }",
    "        article { background: #1f3025; }",
    "        hgroup { margin-bottom: var(--pico-spacing); }",
    '        h1 { font-family: "Mr Dafoe", cursive; font-size: clamp(2.5rem, 5vw, 4rem); }',
    "        #sync-status {",
    "            position: fixed;",
    "            top: calc(var(--pico-spacing));",
    "            right: calc(var(--pico-spacing));",
    "            z-index: 1000;",
    "            text-align: right;",
    "            background: #c8a03e;",
    "            color: #2a1e1a;",
    "            padding: 0.5rem 0.75rem;",
    "            border-radius: 2px;",
    "            box-shadow: 0 2px 8px rgba(0,0,0,0.4);",
    "            transform: rotate(1deg);",
    '            font-family: "Rock Salt", cursive;',
    "            font-size: clamp(0.7rem, 1.2vw, 1rem);",
    "            line-height: 1.6;",
    "        }",
    "        #sync-warning {",
    "            display: none;",
    "            color: #e8a07a;",
    "            font-weight: 700;",
    "            background: #2a1e1a;",
    "            padding: 0.15rem 0.4rem;",
    "            border-radius: var(--pico-border-radius);",
    "            margin-top: 0.25rem;",
    '            font-family: "Rock Salt", cursive;',
    "        }",
    "        ul { list-style: none; padding: 0; }",
    "        li { padding: 0.15rem 0 0.15rem 0.5rem; }",
    "        li[data-tooltip] {",
    "            cursor: default;",
    "        }",
    "        .icon-cell {",
    "            display: inline-flex;",
    "            align-items: center;",
    "            gap: 0.6rem;",
    "        }",
    "        .icon-cell img { vertical-align: middle; }",
    "        details[open] summary { margin-bottom: var(--pico-spacing); }",
    "        details.completed summary {",
    "            color: var(--pico-del-color);",
    "            font-style: italic;",
    "        }",
    "        del { color: var(--pico-del-color); }",
    "        ul { margin-bottom: 0; }",
    "    </style>",
    "</head>",
    "<body>",
    '    <main class="container">',
]

# Floating timer + warning container
html_parts.extend(
    [
        '        <div id="sync-status">',
        '            <div>Time since last sync: <span id="sync-counter">Calculating...</span></div>',
        '            <div id="sync-warning">',
        "                &#9888;&#65039; Out of sync — poke Josh to fix the proxy.",
        "            </div>",
        "        </div>",
    ]
)

html_parts.append("        <hgroup>")
html_parts.append("            <h1>&#128203; Josh's Task List</h1>")
html_parts.append("        </hgroup>")

# Active + completed in one article
html_parts.append("        <article>")

# Active tasks
html_parts.append("            <ul>")

for chore in active_tasks:
    title = html.escape(chore["name"])
    status = chore["status"]
    if status == 1:
        html_parts.append(
            f'                <li data-tooltip="Current focus" data-placement="left">'
            f'<span class="icon-cell">'
            f'<img src="{matrix_gif}" alt="" width="20">'
            f"<span>{title}</span>"
            f"</span></li>"
        )
    elif status == 2:
        html_parts.append(
            f'                <li data-tooltip="Paused" data-placement="left">'
            f'<span class="icon-cell">'
            f"<span>&#128218;</span>"
            f"<span>{title}</span>"
            f"</span></li>"
        )
    else:
        html_parts.append(
            f'                <li data-tooltip="New" data-placement="left">'
            f'<span class="icon-cell">'
            f"<span>&#10024;</span>"
            f"<span>{title}</span>"
            f"</span></li>"
        )

html_parts.append("            </ul>")

# Completed tasks accordion
if completed_tasks:
    html_parts.append('            <details class="completed" name="completed" style="padding-top: 0.5rem">')
    html_parts.append("                <summary>Completed tasks</summary>")
    html_parts.append("                <ul>")
    for chore in completed_tasks:
        title = html.escape(chore["name"])
        html_parts.append(
            f'                    <li data-tooltip="Completed" data-placement="left">'
            f'<span class="icon-cell">'
            f"<span>&#128674;</span>"
            f"<del>{title}</del>"
            f"</span></li>"
        )
    html_parts.append("                </ul>")
    html_parts.append("            </details>")

html_parts.append("        </article>")

# Script
html_parts.extend(
    [
        "        <script>",
        f"            const lastSyncEpoch = {int(time())};",
        "",
        "            function checkSyncStatus() {",
        "                const nowSeconds = Math.floor(Date.now() / 1000);",
        "                const diffSeconds = nowSeconds - lastSyncEpoch;",
        "                const minutes = Math.floor(diffSeconds / 60);",
        "                const seconds = diffSeconds % 60;",
        "",
        '                const counter = document.getElementById("sync-counter");',
        "                if (minutes >= 60) {",
        "                    const hours = Math.floor(minutes / 60);",
        "                    const remainingMins = minutes % 60;",
        "                    counter.innerText = `${hours}h ${remainingMins}m ${seconds}s ago`;",
        "                } else {",
        "                    counter.innerText = `${minutes}m ${seconds}s ago`;",
        "                }",
        "",
        '                const warning = document.getElementById("sync-warning");',
        "                if (diffSeconds >= 30 * 60) {",
        '                    warning.style.display = "block";',
        "                } else {",
        '                    warning.style.display = "none";',
        "                }",
        "            }",
        "",
        "            setInterval(checkSyncStatus, 1000);",
        "            checkSyncStatus();",
        "        </script>",
        "    </main>",
        "</body>",
        "</html>",
    ]
)

html_content = "\n".join(html_parts)

os.makedirs("public", exist_ok=True)
with open("public/index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully generated public/index.html with {len(chore_objects)} tasks.")
