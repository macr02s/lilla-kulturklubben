import re
import os
import mimetypes
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from app_config import auth_settings, runtime_environment
from club_auth import init_auth
from club_banking import init_banking
from visit_stockholm import get_events, SourceUnavailable
import ticketmaster_events as ticketmaster

runtime_env = runtime_environment(os.environ, Path(__file__).with_name(".env"))
mimetypes.add_type("image/webp", ".webp")
app = Flask(__name__)
app.config.update(auth_settings(runtime_env))
app.config["TICKETMASTER_API_KEY"] = runtime_env.get("TICKETMASTER_API_KEY", "").strip()
init_auth(app)
init_banking(app)

missing_auth = [key for key in ("SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "CLUB_MEMBERS")
                if not str(app.config.get(key) or "").strip()]
if missing_auth:
    app.logger.warning("Google login is disabled. Set these environment variables: %s", ", ".join(missing_auth))

@app.route("/")
def home():
    return render_template("index.html", ticketmaster_enabled=bool(app.config["TICKETMASTER_API_KEY"]))


@app.get("/api/events")
@app.get("/api/ticketmaster/events", endpoint="ticketmaster_events")
def events():
    category = request.args.get("category", "")
    subcategory = request.args.get("subcategory", "")
    page = request.args.get("page", "1")
    if (any(value and not re.fullmatch(r"[a-z0-9-]{1,80}", value)
            for value in (category, subcategory))
            or len(page) > 4 or not page.isascii() or not page.isdecimal()
            or not 1 <= int(page) <= 1000):
        return jsonify(error="Ogiltigt kategorival eller sidnummer."), 400
    try:
        if request.endpoint == "ticketmaster_events":
            return jsonify(ticketmaster.get_events(app.config["TICKETMASTER_API_KEY"], category, subcategory, int(page)))
        return jsonify(get_events(category, subcategory, int(page)))
    except (SourceUnavailable, ticketmaster.SourceUnavailable):
        return jsonify(error="Evenemangen kunde inte hämtas just nu. Försök igen om en stund."), 503

if __name__ == "__main__":
    app.run(debug=runtime_env.get("FLASK_DEBUG") == "1")
