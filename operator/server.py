import os
import time
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder=".")
CORS(app)


def _livekit_config():
    return (
        (os.environ.get("LIVEKIT_URL") or "").strip(),
        (os.environ.get("LIVEKIT_API_KEY") or "").strip(),
        (os.environ.get("LIVEKIT_API_SECRET") or "").strip(),
    )


@app.route("/cavalla-rtc/token", methods=["GET"])
def cavalla_rtc_token():
    url, api_key, api_secret = _livekit_config()
    if not url or not api_key or not api_secret:
        return jsonify({
            "error": "LiveKit is not configured",
            "code": "LIVEKIT_NOT_CONFIGURED",
            "setup": "Set LIVEKIT_URL, LIVEKIT_API_KEY, and LIVEKIT_API_SECRET.",
        }), 503

    try:
        from livekit import api as livekit_api
    except Exception:
        return jsonify({
            "error": "LiveKit server SDK is unavailable",
            "code": "LIVEKIT_SDK_MISSING",
            "setup": "Install dependencies from requirements.txt.",
        }), 500

    room = (request.args.get("room") or "cavalla-rtc").strip()
    identity = (request.args.get("identity") or f"participant-{int(time.time() * 1000)}").strip()
    name = (request.args.get("name") or identity).strip()
    can_publish = (request.args.get("canPublish") or "false").strip().lower() in {"1", "true", "yes", "on"}
    can_subscribe = (request.args.get("canSubscribe") or "true").strip().lower() in {"1", "true", "yes", "on"}

    token = (
        livekit_api.AccessToken(api_key, api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_grants(
            livekit_api.VideoGrants(
                room=room,
                room_join=True,
                can_publish=can_publish,
                can_subscribe=can_subscribe,
            )
        )
        .to_jwt()
    )

    return jsonify({
        "url": url,
        "room": room,
        "identity": identity,
        "token": token,
    })


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve(path):
    if path and os.path.exists(os.path.join(app.static_folder, path)):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
