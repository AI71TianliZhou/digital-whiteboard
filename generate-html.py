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

PRIORITY_NAMES = {
    0: None,
    1: "Top priority",
    2: "High priority",
    3: "Medium priority",
    4: "Low priority",
}

# Label sort: within ongoing, no label > in review > outdated > blocked
LABEL_SORT_ORDER = {"in review": 1, "outdated": 2, "blocked": 3}


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


def format_date(iso_str):
    """Convert '2026-09-07T06:29:06.975338Z' to 'Sep 7, 06:29'."""
    if not iso_str or len(iso_str) < 16:
        return ""
    date_part = iso_str[:10]
    time_part = iso_str[11:16]
    parts = date_part.split("-")
    if len(parts) != 3:
        return ""
    months = [
        "",
        "Jan",
        "Feb",
        "Mar",
        "Apr",
        "May",
        "Jun",
        "Jul",
        "Aug",
        "Sep",
        "Oct",
        "Nov",
        "Dec",
    ]
    month = months[int(parts[1])] if 1 <= int(parts[1]) <= 12 else parts[1]
    day = int(parts[2])
    return f"{month} {day}, {time_part}"


def render_label_pills(labels_raw):
    """Render <span> badges for each label with its color."""
    parts = []
    for lbl in labels_raw:
        name = lbl.get("name", "")
        color = lbl.get("color", "")
        if not name:
            continue
        style = (
            f"background:{color};color:#fff;padding:0 0.3rem;border-radius:3px;margin-right:0.2rem"
        )
        parts.append(f'<span style="{style}">{html.escape(name)}</span>')
    return " ".join(parts)


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
    labels_raw = chore.get("labelsV2", []) or []
    label_names = [lbl["name"] for lbl in labels_raw if lbl.get("name")]
    # Precedence: use first label's color for text color
    text_color = ""
    for lbl in labels_raw:
        if lbl.get("name") and lbl.get("color"):
            # Skip if it's a known label name, use its color
            text_color = lbl["color"]
            break

    chore_objects.append(
        {
            "name": chore.get("name", "Untitled Task"),
            "updatedAt": chore.get("updatedAt", ""),
            "status": chore.get("status", 0),
            "priority": chore.get("priority", 0) or 0,
            "isActive": chore.get("isActive", True),
            "labels": label_names,
            "labels_raw": labels_raw,
            "text_color": text_color,
        }
    )


def label_sort_key(chore):
    """Label priority within ongoing tasks: no label < in review < outdated < blocked."""
    for name in ["blocked", "outdated", "in review"]:
        if name in chore["labels"]:
            return LABEL_SORT_ORDER[name]
    return 0


def active_group(chore):
    """Primary sort: ongoing (subsorted by label) < paused < not-started < completed."""
    if not chore["isActive"]:
        return 99
    if chore["status"] == 1:
        return label_sort_key(chore)
    if chore["status"] == 2:
        return 20
    return 30


# Stable sort in reverse precedence: tertiary -> secondary -> primary
chore_objects.sort(key=lambda c: c["updatedAt"], reverse=True)
chore_objects.sort(key=lambda c: c["priority"] if c["priority"] > 0 else 99)
chore_objects.sort(key=active_group)

# --- HTML Generation ---

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
template_path = os.path.join(SCRIPT_DIR, "index.html.template")
with open(template_path, encoding="utf-8") as f:
    template = f.read()

matrix_gif = "https://thumb.wikimedia.org/wikipedia/commons/thumb/7/7e/Digital_rain_animation_big_letters_clear.gif/250px-Digital_rain_animation_big_letters_clear.gif"

active_tasks = [c for c in chore_objects if c["isActive"]]
completed_tasks = [c for c in chore_objects if not c["isActive"]]

active_parts = []
for chore in active_tasks:
    title = html.escape(chore["name"])
    status = chore["status"]
    date_fmt = format_date(chore["updatedAt"])
    priority_name = PRIORITY_NAMES.get(chore["priority"], "")
    label_badges = render_label_pills(chore["labels_raw"])
    text_color = chore["text_color"]
    color_style = f' style="color:{text_color}"' if text_color else ""
    label_text = ", ".join(chore["labels"]) if chore["labels"] else ""

    if status == 1:
        tooltip = f"Current focus: {label_text}" if label_text else "Current focus"
        icon = f'<img src="{matrix_gif}" alt="" style="height: clamp(1rem, 2.5vw, 1.75rem);">'
    elif status == 2:
        tooltip = f"Paused: {label_text}" if label_text else "Paused"
        icon = "<span>&#128218;</span>"
    else:
        tooltip = f"New: {label_text}" if label_text else "New"
        icon = "<span>&#10024;</span>"

    grid_cells = []
    if date_fmt:
        grid_cells.append(f"<div><small>Updated: {date_fmt}</small></div>")
    if priority_name:
        grid_cells.append(f"<div><small>Priority: {priority_name}</small></div>")
    if label_badges:
        grid_cells.append(f"<div><small>{label_badges}</small></div>")

    grid_html = f'<div class="grid">{"".join(grid_cells)}</div>' if grid_cells else ""
    if not grid_html:
        grid_html = '<div class="grid"><div><small>&nbsp;</small></div></div>'

    active_parts.append(
        f"                <li>"
        f"<details>"
        f'<summary>'
        f'<span class="icon-cell" data-tooltip="{tooltip}" data-placement="right">'
        f"{icon}"
        f"<span{color_style}>{title}</span>"
        f"</span>"
        f"</summary>"
        f"{grid_html}"
        f"</details>"
        f"</li>"
    )

completed_parts = []
if completed_tasks:
    completed_parts.append(
        '            <details class="completed" name="completed" style="padding-top: 0.5rem">'
    )
    completed_parts.append("                <summary>Completed tasks</summary>")
    completed_parts.append("                <ul>")
    for chore in completed_tasks:
        title = html.escape(chore["name"])
        date_fmt = format_date(chore["updatedAt"])
        label_badges = render_label_pills(chore["labels_raw"])
        text_color = chore["text_color"]
        color_style = f' style="color:{text_color}"' if text_color else ""

        grid_cells = []
        if date_fmt:
            grid_cells.append(f"<div><small>Completed: {date_fmt}</small></div>")
        if label_badges:
            grid_cells.append(f"<div><small>{label_badges}</small></div>")

        grid_html = f'<div class="grid">{"".join(grid_cells)}</div>' if grid_cells else ""

        completed_parts.append(
            f'                    <li data-tooltip="Completed" data-placement="right">'
            f"<details>"
            f"<summary>"
            f'<span class="icon-cell">'
            f"<span>&#128674;</span>"
            f"<del{color_style}>{title}</del>"
            f"</span>"
            f"</summary>"
            f"{grid_html}"
            f"</details>"
            f"</li>"
        )
    completed_parts.append("                </ul>")
    completed_parts.append("            </details>")

html_content = (
    template.replace("{active_tasks_html}", "\n".join(active_parts))
    .replace("{completed_tasks_html}", "\n".join(completed_parts))
    .replace("{sync_epoch}", str(int(time())))
)

os.makedirs("public", exist_ok=True)
with open("public/index.html", "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"Successfully generated public/index.html with {len(chore_objects)} tasks.")
