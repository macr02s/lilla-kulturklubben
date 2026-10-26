import re
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
from app_config import auth_settings
from club_auth import init_auth
from visit_stockholm import get_events, SourceUnavailable

load_dotenv(Path(__file__).with_name(".env"))
app = Flask(__name__)
app.config.update(auth_settings(os.environ))
init_auth(app)

@app.route("/")
def home():
    return render_template("index.html")


@app.get("/api/events")
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
        return jsonify(get_events(category, subcategory, int(page)))
    except SourceUnavailable:
        return jsonify(error="Evenemangen kunde inte hämtas just nu. Försök igen om en stund."), 503

if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
