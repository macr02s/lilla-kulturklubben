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
from event_months import month_range
from event_query import parse_filters, parse_sources, SOURCE_NAMES
import club_events

runtime_env = runtime_environment(os.environ, Path(__file__).with_name(".env"))
mimetypes.add_type("image/webp", ".webp")
app = Flask(__name__)
app.config.update(auth_settings(runtime_env))
app.config["TICKETMASTER_API_KEY"] = runtime_env.get("TICKETMASTER_API_KEY", "").strip()
app.config["BILLETTO_API_KEYPAIR"] = runtime_env.get("BILLETTO_API_KEYPAIR", "").strip()
init_auth(app)
init_banking(app)

missing_auth = [key for key in ("SECRET_KEY", "GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "CLUB_MEMBERS")
                if not str(app.config.get(key) or "").strip()]
if missing_auth:
    app.logger.warning("Google login is disabled. Set these environment variables: %s", ", ".join(missing_auth))

@app.route("/")
def home():
    active = club_events.providers(app.config)
    event_sources = [{"slug": slug, "name": name} for slug, name in SOURCE_NAMES.items() if name in active]
    return render_template("index.html", event_sources=event_sources)


@app.get("/api/events")
@app.get("/api/ticketmaster/events", endpoint="ticketmaster_events")
def events():
    category = request.args.get("category", "")
    subcategory = request.args.get("subcategory", "")
    page = request.args.get("page", "1")
    try:
        start_date, end_date = month_range(request.args.get("from_month", ""), request.args.get("to_month", ""))
    except ValueError:
        return jsonify(error="Välj en giltig från- och tillmånad i rätt ordning."), 400
    period = {"start_date": start_date, "end_date": end_date} if start_date else {}
    if (any(value and not re.fullmatch(r"[a-z0-9-]{1,80}", value)
            for value in (category, subcategory))
            or len(page) > 4 or not page.isascii() or not page.isdecimal()
            or not 1 <= int(page) <= 1000):
        return jsonify(error="Ogiltigt kategorival eller sidnummer."), 400
    try:
        if request.endpoint == "ticketmaster_events":
            return jsonify(ticketmaster.get_events(app.config["TICKETMASTER_API_KEY"], category, subcategory, int(page), **period))
        return jsonify(get_events(category, subcategory, int(page), **period))
    except (SourceUnavailable, ticketmaster.SourceUnavailable):
        return jsonify(error="Evenemangen kunde inte hämtas just nu. Försök igen om en stund."), 503

@app.get("/api/combined-events")
def combined_events():
    try:
        filters = parse_filters(request.args)
        sources = parse_sources(request.args)
    except ValueError:
        return jsonify(error="Kontrollera kategori, sida och månadsperiod."), 400
    try:
        return jsonify(club_events.get_events(app.config, *filters, selected_sources=sources))
    except club_events.SourceUnavailable:
        return jsonify(error="Evenemangen kunde inte hämtas just nu. Försök igen om en stund."), 503


if __name__ == "__main__":
    app.run(debug=runtime_env.get("FLASK_DEBUG") == "1")
