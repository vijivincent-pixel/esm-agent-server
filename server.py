"""
ESM Sales Form Agent Server — powered by Claude
Calls Apps Script API to update Google Sheets
No service account needed — uses secret token auth
"""

import os, json, re, requests, threading, time
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import anthropic

app = Flask(__name__)
CORS(app)

# ── Config (set as Render environment variables) ──────────
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
APPS_SCRIPT_URL    = os.environ.get("APPS_SCRIPT_URL", "")
RENDER_SECRET_TOKEN = "1cc95fd5cdfb4e22de2916252fdcbc202cf37feac1c2cad3be4845ca126bedee"
# ─────────────────────────────────────────────────────────

DROPDOWN_MAP = {
    "brand":"Brand","industry":"Industry","hqCountry":"HQ Country",
    "customerName":"Customer Name","customerName2":"Customer Name 2",
    "role":"Role","level":"Level","salesRep":"Sales Rep",
    "pocCity":"POC City","pocState":"POC State","pocCountry":"POC Country",
    "type":"Type","means":"Means","topic":"Topic","size":"Size",
}

def call_apps_script(action, **kwargs):
    """Call the Apps Script API endpoint."""
    try:
        params = {"token": RENDER_SECRET_TOKEN, "action": action}
        params.update(kwargs)
        response = requests.post(
            APPS_SCRIPT_URL,
            data=params,
            timeout=30,
            allow_redirects=True
        )
        if response.status_code == 200:
            try:
                return response.json()
            except:
                return {"success": True, "message": response.text}
        return {"success": False, "message": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "message": str(e)}

def add_option(field, value):
    """Add a new option to a dropdown via Apps Script."""
    result = call_apps_script("add_option", field=field, value=value)
    if result.get("success"):
        return True, result.get("message", "added")
    return False, result.get("message", "unknown error")

def update_brand_db(brand, field, value):
    """Update BrandDB via Apps Script."""
    call_apps_script("update_brand_db", brand=brand, field=field, value=value)

def batch_update(updates):
    """Send multiple updates in one Apps Script call."""
    result = call_apps_script(
        "batch_update",
        updates=json.dumps(updates)
    )
    return result

def handle_structured_request(payload_str):
    """Handle structured requests from New Brand / New Contact panels."""
    try:
        payload = json.loads(payload_str)
        action  = payload.get("action")
        changes = []
        added_items = []
        brand_links = []

        if action == "add_brand":
            brand       = payload.get("brand", "").strip()
            industry    = payload.get("industry", "").strip()
            country     = payload.get("country", "").strip()
            customer    = payload.get("customer", "").strip()
            role        = payload.get("role", "").strip()
            level       = payload.get("level", "").strip()
            city        = payload.get("city", "").strip()
            poc_country = payload.get("pocCountry", "").strip()
            rep         = payload.get("rep", "").strip()

            if not brand:
                return {"reply": "❌ Brand name is required.", "added": [], "brandLinks": []}

            # Build batch updates
            updates = []
            field_map = [
                ("brand", brand, None),
                ("industry", industry, brand),
                ("hqCountry", country, brand),
                ("customerName", customer, brand),
                ("role", role, brand),
                ("pocCity", city, brand),
                ("pocCountry", poc_country, brand),
            ]

            for field, val, link_brand in field_map:
                if not val: continue
                updates.append({
                    "field": field,
                    "value": val,
                    "brand": link_brand
                })

            # Send batch to Apps Script
            results = batch_update(updates)

            for update in updates:
                field = update["field"]
                val   = update["value"]
                label = DROPDOWN_MAP.get(field, field)
                changes.append(f"✅ Added {val} to {label}")
                added_items.append({"field": field, "value": val})
                if update.get("brand"):
                    brand_links.append({"brand": update["brand"], "field": field, "value": val})

            # Level and rep — only link to brand, don't add to dropdown
            if level: update_brand_db(brand, "level", level)
            if rep:   update_brand_db(brand, "salesRep", rep)

        elif action == "add_contact":
            brand       = payload.get("brand", "").strip()
            customer    = payload.get("customer", "").strip()
            role        = payload.get("role", "").strip()
            level       = payload.get("level", "").strip()
            city        = payload.get("city", "").strip()
            poc_country = payload.get("pocCountry", "").strip()
            rep         = payload.get("rep", "").strip()

            if not brand or not customer:
                return {"reply": "❌ Brand and Customer Name are required.", "added": [], "brandLinks": []}

            updates = []
            field_map = [
                ("customerName", customer, brand),
                ("role", role, brand),
                ("pocCity", city, brand),
                ("pocCountry", poc_country, brand),
            ]

            for field, val, link_brand in field_map:
                if not val: continue
                updates.append({"field": field, "value": val, "brand": link_brand})

            batch_update(updates)

            for update in updates:
                field = update["field"]
                val   = update["value"]
                label = DROPDOWN_MAP.get(field, field)
                changes.append(f"✅ Added {val} to {label}")
                added_items.append({"field": field, "value": val})
                brand_links.append({"brand": brand, "field": field, "value": val})

            if level: update_brand_db(brand, "level", level)
            if rep:   update_brand_db(brand, "salesRep", rep)

        if not changes:
            return {"reply": "ℹ️ No changes were needed.", "added": [], "brandLinks": []}

        reply = "\n".join(changes) + "\n\n🔄 New options are now available in the dropdowns!"
        return {"reply": reply, "added": added_items, "brandLinks": brand_links}

    except Exception as e:
        return {"reply": f"❌ Error: {str(e)}", "added": [], "brandLinks": []}

def parse_intent(user_request):
    """Parse free-text using Claude."""
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
- If user says "for [Brand]" extract brandLink
- Return ONLY valid JSON, no markdown

Format:
{{"actions":[{{"action":"add or remove","field":"field_name","values":["value1"],"brandLink":"BrandName or null"}}],"summary":"short description"}}"""

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = message.content[0].text.strip()
    raw = re.sub(r'^```(?:json)?|```$', '', raw, flags=re.MULTILINE).strip()
    return json.loads(raw)

@app.route("/", methods=["GET"])
def health():
    return jsonify({"status": "ESM Agent Server is running ✅ (powered by Claude)"})

@app.route("/ping", methods=["GET"])
def ping():
    return jsonify({"status": "pong", "time": datetime.now().isoformat()})

@app.route("/chat", methods=["POST"])
def chat():
    try:
        data    = request.get_json()
        message = data.get("message", "").strip()
        mode    = data.get("mode", "text")

        if not message:
            return jsonify({"reply": "Please type a request.", "added": [], "brandLinks": []})

        # Structured mode from New Brand / New Contact panels
        if mode == "structured":
            return jsonify(handle_structured_request(message))

        # Free text mode — use Claude to parse
        intent = parse_intent(message)
        if not intent.get("actions"):
            return jsonify({
                "reply": "Sorry, I didn't understand. Try: 'Add Cape Town to POC City'",
                "added": [], "brandLinks": []
            })

        all_changes = []
        added_items = []
        brand_links = []

        for a in intent.get("actions", []):
            action     = a["action"]
            field      = a["field"]
            values     = a["values"]
            brand_link = a.get("brandLink")

            if field not in DROPDOWN_MAP:
                continue

            label = DROPDOWN_MAP[field]

            if action == "add":
                for val in values:
                    ok, msg = add_option(field, val)
                    if ok and msg == "added":
                        all_changes.append(f"✅ Added {val} to {label}")
                        added_items.append({"field": field, "value": val})
                        if brand_link and brand_link.lower() != "null":
                            update_brand_db(brand_link, field, val)
                            brand_links.append({"brand": brand_link, "field": field, "value": val})
                    elif ok and msg == "already_exists":
                        if brand_link and brand_link.lower() != "null":
                            update_brand_db(brand_link, field, val)
                            brand_links.append({"brand": brand_link, "field": field, "value": val})
                            all_changes.append(f"✅ Linked {val} to {brand_link}")
                        else:
                            all_changes.append(f"ℹ️ {val} already exists in {label}")
                    else:
                        all_changes.append(f"❌ Could not add {val}: {msg}")

        if not all_changes:
            return jsonify({"reply": "No changes made.", "added": [], "brandLinks": []})

        reply = "\n".join(all_changes)
        if any("✅" in c for c in all_changes):
            reply += "\n\n🔄 New options are now available in the dropdowns!"

        return jsonify({"reply": reply, "added": added_items, "brandLinks": brand_links})

    except Exception as e:
        return jsonify({"reply": f"❌ Error: {str(e)}", "added": [], "brandLinks": []})

def keep_alive():
    time.sleep(60)
    while True:
        try:
            port = os.environ.get("PORT", "5000")
            requests.get(f"http://localhost:{port}/ping", timeout=5)
        except:
            pass
        time.sleep(600)
@app.route("/test-appsscript", methods=["GET"])
def test_appsscript():
    result = call_apps_script("add_option", field="brand", value="RenderTest123")
    return jsonify(result)
if __name__ == "__main__":
    threading.Thread(target=keep_alive, daemon=True).start()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
else:
    threading.Thread(target=keep_alive, daemon=True).start()
