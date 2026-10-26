"""Shared read-only club balance, explicitly approved by the account owner."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from hmac import compare_digest
import json
import secrets
from time import time
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, request, session, url_for
import requests

from banking_check import API, BankingCheckError, authorization
from club_auth import connection, current_member, member_required, members

bank = Blueprint("bank", __name__)


class BankError(Exception):
    pass


def db():
    database = connection()
    database.execute("CREATE TABLE IF NOT EXISTS bank_connection (id INTEGER PRIMARY KEY CHECK(id=1), encrypted TEXT NOT NULL)")
    database.execute("CREATE TABLE IF NOT EXISTS bank_pending (state_hash TEXT PRIMARY KEY, owner TEXT NOT NULL, expires INTEGER NOT NULL)")
    database.commit()
    return database


def cipher():
    try:
        return Fernet(current_app.config.get("ENABLE_BANKING_ENCRYPTION_KEY", "").encode())
    except (ValueError, TypeError):
        raise BankError("Bankkopplingen är inte färdigkonfigurerad.") from None


def ready():
    config = current_app.config
    try:
        cipher()
    except BankError:
        return False
    return bool(config.get("ENABLE_BANKING_APPLICATION_ID") and config.get("ENABLE_BANKING_PRIVATE_KEY_PATH")
                and config.get("ENABLE_BANKING_ADMIN_EMAIL") in members()
                and config.get("ENABLE_BANKING_ENVIRONMENT") in {"SANDBOX", "PRODUCTION"})


def is_admin():
    user = current_member()
    return bool(user and user["email"] == current_app.config.get("ENABLE_BANKING_ADMIN_EMAIL"))


def verify_post():
    token = session.get("csrf_token", "")
    if not token or not compare_digest(token.encode(), request.form.get("csrf_token", "").encode()):
        abort(400)
    if not is_admin():
        abort(403)


def api(method, path, body=None):
    try:
        response = requests.request(method, API + path, headers=authorization(current_app.config),
                                    json=body, timeout=(5, 15), allow_redirects=False)
    except (requests.RequestException, BankingCheckError):
        raise BankError("Banken kunde inte kontaktas. Försök igen om en stund.") from None
    if response.status_code in {401, 403, 404, 410}:
        raise BankError("Bankåtkomsten är inte längre tillgänglig. Kassören behöver kontrollera eller förnya anslutningen.")
    if response.status_code != 200:
        raise BankError("Banken kunde inte slutföra förfrågan. Försök igen senare.")
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError:
        raise BankError("Banken lämnade ett oväntat svar.") from None


def load_link():
    row = db().execute("SELECT encrypted FROM bank_connection WHERE id=1").fetchone()
    if not row:
        return None
    try:
        link = json.loads(cipher().decrypt(row[0].encode()))
    except (InvalidToken, ValueError, TypeError):
        raise BankError("Bankkopplingen kunde inte läsas. Kontrollera serverns krypteringsnyckel.") from None
    if (link.get("application_id") != current_app.config.get("ENABLE_BANKING_APPLICATION_ID")
            or link.get("environment") != current_app.config.get("ENABLE_BANKING_ENVIRONMENT")
            or link.get("admin_email") != current_app.config.get("ENABLE_BANKING_ADMIN_EMAIL")):
        raise BankError("Bankinställningarna har ändrats. Kassören behöver ansluta kontot på nytt.")
    return link


def save_link(link):
    encrypted = cipher().encrypt(json.dumps(link).encode()).decode()
    database = db()
    with database:
        database.execute("INSERT INTO bank_connection(id,encrypted) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET encrypted=excluded.encrypted", (encrypted,))


def account_label(account):
    identifier = (account.get("account_id") or {}).get("iban", "")
    return str(account.get("name") or "Nordea-konto")[:100] + (" · •••• " + identifier[-4:] if identifier else "")


def valid_uuid(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError):
        raise BankError("Banken lämnade ett ogiltigt konto eller sessions-ID.") from None


def trusted_authorization_url(value):
    # Enable Banking is migrating from tilisy to auth; both exact hosts are valid.
    if not isinstance(value, str) or any(ord(char) <= 32 or ord(char) == 127 for char in value) or "\\" in value:
        return False
    try:
        destination = urlsplit(value)
        return (destination.scheme == "https"
                and destination.hostname in {"auth.enablebanking.com", "tilisy.enablebanking.com"}
                and destination.port in {None, 443}
                and not destination.username and not destination.password)
    except ValueError:
        return False


@bank.post("/klubben/bank/anslut")
@member_required
def connect():
    verify_post()
    try:
        if not ready():
            raise BankError("Bankkopplingen är inte färdigkonfigurerad.")
        info = api("GET", "/application")
        mode = current_app.config["ENABLE_BANKING_ENVIRONMENT"]
        if info.get("environment") != mode or info.get("active") is not True:
            raise BankError("Banknyckeln hör inte till vald aktiv miljö. Sandbox och produktion kräver separata uppgifter.")
        callback = current_app.config["ENABLE_BANKING_REDIRECT_URI"]
        if callback not in info.get("redirect_urls", []):
            raise BankError("Bankens callback-adress behöver registreras hos Enable Banking. Se projektets bankinstruktioner.")
        state = secrets.token_urlsafe(32)
        result = api("POST", "/auth", {
            "access": {"valid_until": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                       "balances": True, "transactions": False},
            "aspsp": {"name": "Nordea", "country": "SE"}, "psu_type": "personal",
            "state": state, "redirect_url": callback, "language": "sv",
        })
        if not trusted_authorization_url(result.get("url", "")):
            raise BankError("Banken lämnade en oväntad inloggningsadress.")
        hashed = sha256(state.encode()).hexdigest()
        database = db()
        with database:
            database.execute("DELETE FROM bank_pending WHERE expires < ? OR owner=?", (int(time()), current_member()["subject"]))
            database.execute("INSERT INTO bank_pending VALUES(?,?,?)", (hashed, current_member()["subject"], int(time()) + 600))
        session["bank_state"] = hashed
        return redirect(result["url"])
    except BankError as error:
        flash(str(error), "bank")
        return redirect(url_for("club.index") + "#klubbkassan")


@bank.get("/callback")
@bank.get("/bank/callback")
@member_required
def callback():
    if not is_admin():
        abort(403)
    supplied = request.args.get("state", "")
    hashed = sha256(supplied.encode()).hexdigest()
    expected = session.pop("bank_state", "")
    if not expected or not compare_digest(hashed, expected):
        abort(400)
    database = db()
    with database:
        consumed = database.execute("DELETE FROM bank_pending WHERE state_hash=? AND owner=? AND expires>?",
                                    (hashed, current_member()["subject"], int(time()))).rowcount
    if consumed != 1:
        abort(400)
    if request.args.get("error"):
        flash("Bankanslutningen avbröts. Inget nytt konto har anslutits.", "bank")
        return redirect(url_for("club.index") + "#klubbkassan")
    try:
        code = request.args.get("code", "")
        if not code or len(code) > 4096:
            raise BankError("Bankens godkännande saknas. Starta anslutningen på nytt.")
        data = api("POST", "/sessions", {"code": code})
        session_id = valid_uuid(data.get("session_id"))
        accounts = [{"id": valid_uuid(account.get("uid")), "label": account_label(account)}
                    for account in data.get("accounts", []) if isinstance(account, dict)]
        if not accounts:
            raise BankError("Inga konton blev tillgängliga i bankens godkännande.")
        selected = accounts[0]["id"] if len(accounts) == 1 else None
        save_link({"session_id": session_id, "accounts": accounts, "selected": selected,
                   "application_id": current_app.config["ENABLE_BANKING_APPLICATION_ID"],
                   "environment": current_app.config["ENABLE_BANKING_ENVIRONMENT"],
                   "admin_email": current_member()["email"],
                   "valid_until": (data.get("access") or {}).get("valid_until")})
        if selected:
            flash("Banken är ansluten. Ditt enda konto är valt och saldot visas för klubbens godkända medlemmar.", "bank")
        else:
            flash("Banken är ansluten och lämnade flera konton. Välj vilket konto som ska visas för klubbens medlemmar.", "bank")
    except BankError as error:
        flash(str(error), "bank")
    return redirect(url_for("club.index") + "#klubbkassan")


@bank.post("/klubben/bank/valj-konto")
@member_required
def choose_account():
    verify_post()
    if request.form.get("share_confirm") != "yes":
        abort(400)
    try:
        link = load_link()
        account_id = request.form.get("account_id")
        if not link or account_id not in {item["id"] for item in link["accounts"]}:
            abort(400)
        link["selected"] = account_id
        save_link(link)
        flash("Kontot är valt. Saldot visas nu för klubbens godkända medlemmar.", "bank")
    except BankError as error:
        flash(str(error), "bank")
    return redirect(url_for("club.index") + "#klubbkassan")


@bank.get("/klubben/bank/saldo")
@member_required
def balance():
    # The owner approved member-wide access; only the expressly selected account is exposed.
    admin = is_admin()
    base = {"admin": admin, "environment": current_app.config.get("ENABLE_BANKING_ENVIRONMENT", "SANDBOX")}
    if not ready():
        return jsonify(**base, status="unconfigured")
    try:
        link = load_link()
        if not link:
            return jsonify(**base, status="disconnected")
        account_id = link.get("selected")
        if not account_id:
            return jsonify(**base, status="choose", accounts=link["accounts"] if admin else [])
        access = api("GET", "/sessions/" + valid_uuid(link["session_id"]))
        if access.get("status") != "AUTHORIZED" or account_id not in access.get("accounts", []):
            raise BankError("Bankåtkomsten har löpt ut eller avslutats. Kassören behöver ansluta på nytt.")
        data = api("GET", "/accounts/" + valid_uuid(account_id) + "/balances")
        balances = []
        for item in data.get("balances", []):
            amount = item.get("balance_amount") or {}
            value = str(amount.get("amount", ""))
            try:
                if not Decimal(value).is_finite():
                    raise InvalidOperation()
            except InvalidOperation:
                raise BankError("Banken lämnade ett ogiltigt saldobelopp.") from None
            balances.append({"amount": value, "currency": str(amount.get("currency", "")),
                             "type": str(item.get("balance_type", "")),
                             "name": str(item.get("name", "Saldo")),
                             "date": item.get("reference_date") or item.get("last_change_date_time") or ""})
        selected = next(item for item in link["accounts"] if item["id"] == account_id)
        return jsonify(**base, status="connected", account=selected["label"], balances=balances,
                       checked_at=datetime.now(timezone.utc).isoformat())
    except BankError as error:
        return jsonify(**base, status="error", message=str(error)), 502


def init_banking(app):
    app.register_blueprint(bank)

    @app.context_processor
    def bank_context():
        return {"bank_admin": is_admin(), "bank_mode": app.config.get("ENABLE_BANKING_ENVIRONMENT", "SANDBOX")}
