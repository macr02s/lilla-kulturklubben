"""Google login and membership access, kept separate from the event integration."""
from functools import wraps
from hmac import compare_digest
from pathlib import Path
import secrets
import sqlite3
from urllib.parse import urlencode, urlsplit

from authlib.integrations.flask_client import OAuth
from authlib.integrations.base_client.errors import OAuthError
from flask import (Blueprint, abort, current_app, g, redirect, render_template,
                   request, session, url_for)
from joserfc.errors import JoseError
from requests.exceptions import RequestException
from club_database import DatabaseUnavailable, open_database

club = Blueprint("club", __name__)


def members():
    return {email.strip().casefold() for email in current_app.config.get("CLUB_MEMBERS", "").split(",") if email.strip()}


def auth_ready():
    config = current_app.config
    uri = urlsplit(config.get("GOOGLE_REDIRECT_URI", ""))
    valid_uri = (uri.scheme == "https" or
                 (uri.scheme == "http" and uri.hostname in {"127.0.0.1", "localhost"}))
    local_http = uri.scheme == "http" and uri.hostname in {"127.0.0.1", "localhost"}
    return bool(config.get("SECRET_KEY") and config.get("GOOGLE_CLIENT_ID")
                and config.get("GOOGLE_CLIENT_SECRET") and members()
                and valid_uri and uri.hostname and uri.path == "/auth/google/callback"
                and not uri.query and not uri.fragment and not uri.username
                and (local_http or config.get("SESSION_COOKIE_SECURE")))


def connection():
    if "club_db" not in g:
        g.club_db = open_database(current_app.config.get("DATABASE_URL", ""), current_app.config["CLUB_DATABASE"])
        g.club_db.execute("""CREATE TABLE IF NOT EXISTS members (
            email TEXT PRIMARY KEY, provider TEXT NOT NULL, subject TEXT NOT NULL,
            UNIQUE(provider, subject))""")
        g.club_db.commit()
    return g.club_db


def bind_member(email, subject):
    """Bind an invited email to a stable Google account ID on its first login."""
    db = connection()
    try:
        with db:
            db.execute("INSERT INTO members(email, provider, subject) VALUES (?, 'google', ?) ON CONFLICT DO NOTHING",
                       (email, subject))
        row = db.execute("SELECT subject FROM members WHERE email = ? AND provider = 'google'", (email,)).fetchone()
        return bool(row and row[0] == subject)
    except sqlite3.IntegrityError:
        return False


def current_member():
    user = session.get("member")
    if not isinstance(user, dict) or not auth_ready():
        return None
    email, subject = user.get("email"), user.get("subject")
    if email not in members() or not subject or user.get("provider") != "google":
        session.pop("member", None)
        return None
    row = connection().execute("SELECT subject FROM members WHERE email = ? AND provider = 'google'", (email,)).fetchone()
    if not row or row[0] != subject:
        session.pop("member", None)
        return None
    return user


def csrf_token():
    if not session.get("csrf_token"):
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def member_required(view):
    @wraps(view)
    def protected(*args, **kwargs):
        if not current_member():
            return redirect(url_for("club.index"))
        return view(*args, **kwargs)
    return protected


@club.get("/klubben")
def index():
    user = current_member()
    calendar = None
    calendar_id = current_app.config.get("CLUB_CALENDAR_ID", "").strip()
    if user and calendar_id:
        calendar = {
            "embed_url": "https://calendar.google.com/calendar/embed?" + urlencode({
                "src": calendar_id, "ctz": "Europe/Stockholm", "hl": "sv",
                "mode": "MONTH", "showTitle": "0", "showPrint": "0",
                "showCalendars": "0", "showTz": "0", "bgcolor": "#f8f5ed",
            }),
            "open_url": "https://calendar.google.com/calendar/render?" + urlencode({"cid": calendar_id}),
        }
    return render_template("club.html", member=user, auth_ready=auth_ready(),
                           error=None, csrf_token=csrf_token() if user else None,
                           calendar=calendar)


def login_error(message, status):
    return render_template("club.html", member=None, auth_ready=auth_ready(), error=message), status


@club.get("/auth/google")
def login():
    if not auth_ready():
        return login_error("Inloggningen är inte tillgänglig ännu. Kontakta klubbens administratör.", 503)
    session.clear()
    try:
        return current_app.extensions["club_oauth"].google.authorize_redirect(
            current_app.config["GOOGLE_REDIRECT_URI"], prompt="select_account")
    except (OAuthError, JoseError, RequestException, ValueError):
        session.clear()
        return login_error("Det gick inte att kontakta Google. Försök igen om en stund.", 502)


@club.get("/auth/google/callback")
def callback():
    if not auth_ready():
        return login_error("Inloggningen är inte tillgänglig ännu. Kontakta klubbens administratör.", 503)
    try:
        # Authlib validates OAuth state and the ID token's signature, issuer,
        # audience, expiry and nonce before returning these claims.
        token = current_app.extensions["club_oauth"].google.authorize_access_token()
        if not token.get("id_token"):
            raise ValueError("Missing ID token")
        user = token.get("userinfo") or {}
    except (OAuthError, JoseError, RequestException, ValueError, KeyError):
        session.clear()
        return login_error("Inloggningen kunde inte slutföras. Försök logga in igen.", 400)
    # A missing or unverified identity never becomes an authenticated member.
    email = user.get("email", "")
    subject = user.get("sub")
    if not isinstance(email, str) or not isinstance(subject, str) or not subject or user.get("email_verified") is not True:
        session.clear()
        return login_error("Google kunde inte bekräfta ditt konto. Använd ett konto med verifierad e-postadress.", 403)
    email = email.casefold()
    if email not in members() or not bind_member(email, subject):
        session.clear()
        return login_error("Det här Google-kontot har inte tillgång till Klubben. Kontakta klubbens administratör om du är medlem.", 403)
    session.clear()
    session.permanent = True
    session["member"] = {"provider": "google", "subject": subject,
                         "email": email, "name": str(user.get("given_name") or user.get("name") or "medlem")[:100]}
    return redirect(url_for("club.index"))


@club.post("/auth/logout")
def logout():
    supplied = request.form.get("csrf_token", "")
    expected = session.get("csrf_token")
    if not expected or not compare_digest(supplied.encode(), expected.encode()):
        abort(400)
    session.clear()
    return redirect(url_for("home"))


def init_auth(app):
    app.config.setdefault("CLUB_DATABASE", str(Path(app.instance_path) / "club.sqlite3"))
    oauth = OAuth(app)
    oauth.register("google", server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
                   client_kwargs={"scope": "openid email profile", "code_challenge_method": "S256", "timeout": 10})
    app.extensions["club_oauth"] = oauth
    app.register_blueprint(club)

    @app.errorhandler(DatabaseUnavailable)
    def database_unavailable(error):
        return "Medlemstjänsten är tillfälligt otillgänglig. Försök igen om en stund.", 503, {"Cache-Control": "no-store"}

    @app.context_processor
    def membership_context():
        user = current_member()
        return {"club_member": user, "logout_csrf": csrf_token() if user else None}

    @app.after_request
    def private_headers(response):
        if request.blueprint in {"club", "bank"} or session.get("member"):
            response.headers["Cache-Control"] = "no-store, private"
            response.headers["Pragma"] = "no-cache"
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    @app.teardown_appcontext
    def close_db(error):
        db = g.pop("club_db", None)
        if db is not None:
            db.close()
