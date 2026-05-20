"""
ESM Sales Form Agent Server — powered by Claude (Anthropic)
------------------------------------------------------------
Hosted on Render (free tier)
Supports brand-linked customer name additions.
"""

import os
import json
import base64
import re
import requests
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

# ── Config (set as Environment Variables on Render) ──
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GITHUB_TOKEN      = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO       = os.environ.get("GITHUB_REPO", "vijivincent-pixel/Sales-Activity")
GITHUB_FILE_PATH  = os.environ.get("GITHUB_FILE_PATH", "index.html")
GITHUB_BRANCH     = os.environ.get("GITHUB_BRANCH", "main")

GITHUB_API = "https://api.github.com"
GH_HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

DROPDOWN_MAP = {
    "brand":         "Brand",
    "industry":      "Industry",
    "hqCountry":     "HQ Country",
    "customerName":  "Customer Name",
    "customerName2": "Customer Name 2",
    "role":          "Role",
    "level":         "Level",
    "salesRep":      "Sales Rep",
    "pocCity":       "POC City",
    "pocState":      "POC State",
    "pocCountry":    "POC Country",
    "type":          "Type",
    "means":         "Means",
    "topic":         "Topic",
    "size":          "Size",
}

# ── GitHub helpers ────────────────────────────────────────

def get_file_from_github():
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=GH_HEADERS)
    if r.status_code != 200:
        raise Exception(f"GitHub fetch failed: {r.status_code}")
    data = r.json()
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]

def push_file_to_github(content, sha, commit_message):
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{GITHUB_FILE_PATH}"
    payload = {
        "message": commit_message,
        "content": base64.b64encode(content.encode()).decode(),
        "sha": sha,
        "branch": GITHUB_BRANCH
    }
    r = requests.put(url, headers=GH_HEADERS, json=payload)
    if r.status_code not in (200, 201):
        raise Exception(f"GitHub push failed: {r.status_code}")

# ── HTML option helpers ───────────────────────────────────

def insert_options_sorted(html, field_name, new_options):
    pattern = rf'(<select name="{field_name}"[^>]*>)(.*?)(</select>)'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return html, []
    before, block, after = match.group(1), match.group(2), match.group(3)
    existing = [o.strip() for o in re.findall(r'<option(?:[^>]*)>([^<]+)</option>', block)]
    existing_lower = [o.lower() for o in existing]
    added = []
    for opt in new_options:
        if opt.lower() not in existing_lower:
            existing.append(opt)
            added.append(opt)
    if not added:
        return html, []
    sortable = sorted(
        [o for o in existing if o not in ("— select —", "— search or select —", "__sep__")],
        key=lambda x: x.lower()
    )
    new_block = (
        '\n            <option value="">— search or select —</option>\n            '
        + "\n            ".join(f"<option>{o}</option>" for o in sortable)
        + "\n          "
    )
    return html[:match.start()] + before + new_block + after + html[match.end():], added

def remove_options(html, field_name, options_to_remove):
    pattern = rf'(<select name="{field_name}"[^>]*>)(.*?)(</select>)'
    match = re.search(pattern, html, re.DOTALL)
    if not match:
        return html, []
    before, block, after = match.group(1), match.group(2), match.group(3)
    remove_lower = [o.lower() for o in options_to_remove]
    removed = []
    def remove_option(m):
        text = m.group(1).strip()
        if text.lower() in remove_lower:
            removed.append(text)
            return ""
        return m.group(0)
    new_block = re.sub(r'<option(?:[^>]*)>([^<]+)</option>', remove_option, block)
    return html[:match.start()] + before + new_block + after + html[match.end():], removed

def update_brand_db(html, brand, field, value):
    """Update BRAND_DB JSON inside the HTML to link a value to a brand."""
    start_marker = 'const BRAND_DB = '
    end_marker   = ';\n\n// Fields that can be autofilled'
    start_idx = html.find(start_marker)
    end_idx   = html.find(end_marker, start_idx)
    if start_idx == -1 or end_idx == -1:
        return html, False

    db_str = html[start_idx + len(start_marker):end_idx]
    try:
        db = json.loads(db_str)
    except json.JSONDecodeError:
        return html, False

    # Add or update brand entry
    if brand not in db:
        db[brand] = {}

    if field not in db[brand]:
        db[brand][field] = {"byFreq": [value], "top": value, "topPct": 100}
    else:
        freq_list = db[brand][field].get("byFreq", [])
        if value not in freq_list:
            freq_list.insert(0, value)  # Put new value at top (most relevant)
            db[brand][field]["byFreq"] = freq_list
            db[brand][field]["top"] = freq_list[0]

    new_db_str = json.dumps(db, separators=(',', ':'))
    html = html[:start_idx + len(start_marker)] + new_db_str + html[end_idx:]
    return html, True

# ── Claude intent parsing ─────────────────────────────────

def parse_intent(user_request):
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    fields_list = "\n".join([f'  "{k}": "{v}"' for k, v in DROPDOWN_MAP.items()])

    prompt = f"""You manage a sales form dropdown options.
Parse the user request into JSON.

Available fields:
{fields_list}

User request: "{user_request}"

Rules:
- Map "Brand"/"Company" to "brand"
- Map "Customer"/"Contact"/"Name" to "customerName"
- Map "Role"/"Position"/"Title" to "role"
- Map "City"/"POC City" to "pocCity"
- Map "Country"/"POC Country" to "pocCountry"
- Map "State"/"POC State" to "pocState"
- Map "HQ Country" to "hqCountry"
- Map "Industry"/"Sector" to "industry"
- If the user says "for [Brand]" or "works for [Brand]" or "at [Brand]", extract the brand name into "brandLink"
- Return ONLY valid JSON, no markdown, no explanation

Return exactly this format:
{{"actions":[{{"action":"add or remove","field":"field_name","values":["value1"],"brandLink":"BrandName or null"}}],"summary":"short description"}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
    return json.loads(raw)

# ── API Routes ────────────────────────────────────────────

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ESM Agent Server is running ✅ (powered by Claude)"})

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data = request.get_json()
        user_message = data.get("message", "").strip()

        if not user_message:
            return jsonify({"reply": "Please type a request."})

        # Parse intent with Claude
        intent = parse_intent(user_message)
        if not intent.get("actions"):
            return jsonify({"reply": "Sorry, I didn't understand that. Try: 'Add Cleo to Brand' or 'Add John Smith to Customer Name for Cleo'"})

        # Fetch HTML from GitHub
        html, sha = get_file_from_github()

        # Apply changes
        all_changes = []
        added_items  = []
        brand_links  = []

        for a in intent.get("actions", []):
            action     = a["action"]
            field      = a["field"]
            values     = a["values"]
            brand_link = a.get("brandLink")

            if field not in DROPDOWN_MAP:
                continue

            label = DROPDOWN_MAP[field]

            if action == "add":
                html, added = insert_options_sorted(html, field, values)
                if added:
                    all_changes.append(f"✅ Added {', '.join(added)} to {label}")
                    for v in added:
                        added_items.append({"field": field, "value": v})

                    # If brand link provided, update BRAND_DB too
                    if brand_link and brand_link.lower() != "null":
                        for v in added:
                            html, db_updated = update_brand_db(html, brand_link, field, v)
                            if db_updated:
                                all_changes.append(f"✅ Linked {v} to {brand_link} in suggestions")
                                brand_links.append({"brand": brand_link, "field": field, "value": v})
                else:
                    # Even if already exists, still update brand link if provided
                    if brand_link and brand_link.lower() != "null":
                        for v in values:
                            html, db_updated = update_brand_db(html, brand_link, field, v)
                            if db_updated:
                                all_changes.append(f"✅ Linked {v} to {brand_link} in suggestions")
                                brand_links.append({"brand": brand_link, "field": field, "value": v})
                            else:
                                all_changes.append(f"ℹ️ {v} already linked to {brand_link}")
                    else:
                        all_changes.append(f"ℹ️ {', '.join(values)} already exists in {label}")

            elif action == "remove":
                html, removed = remove_options(html, field, values)
                if removed:
                    all_changes.append(f"✅ Removed {', '.join(removed)} from {label}")
                else:
                    all_changes.append(f"ℹ️ {', '.join(values)} not found in {label}")

        if not any("✅" in c for c in all_changes):
            return jsonify({"reply": "\n".join(all_changes) or "No changes needed.", "added": [], "brandLinks": []})

        # Push to GitHub
        timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M")
        commit_msg = f"[ESM Agent] {intent.get('summary', 'Update')} — {timestamp}"
        push_file_to_github(html, sha, commit_msg)

        reply = "\n".join(all_changes)
        reply += "\n\n🔄 Form updated! New options are now available in the dropdowns."
        return jsonify({"reply": reply, "added": added_items, "brandLinks": brand_links})

    except Exception as e:
        return jsonify({"reply": f"❌ Error: {str(e)}", "added": [], "brandLinks": []})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
