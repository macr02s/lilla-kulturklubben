"""Step 2: verify Enable Banking sandbox access without accessing bank accounts.

Run: python banking_check.py
"""
import os
from pathlib import Path
from time import time
from uuid import UUID

import jwt
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app_config import runtime_environment

ROOT = Path(__file__).resolve().parent
API = "https://api.enablebanking.com"


class BankingCheckError(Exception):
    pass


def authorization(environ):
    application_id = environ.get("ENABLE_BANKING_APPLICATION_ID", "").strip()
    key_path = environ.get("ENABLE_BANKING_PRIVATE_KEY_PATH", "").strip()
    if not application_id or not key_path:
        raise BankingCheckError("Fyll i ENABLE_BANKING_APPLICATION_ID och ENABLE_BANKING_PRIVATE_KEY_PATH i .env.")
    try:
        if UUID(application_id).version != 4:
            raise ValueError()
    except ValueError:
        raise BankingCheckError("Application ID ska vara applikationens UUID från Enable Banking.") from None
    path = Path(key_path).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    if path.resolve().is_relative_to((ROOT / "static").resolve()):
        raise BankingCheckError("Flytta den privata nyckeln från static/ till exempelvis secrets/.")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise ValueError()
    except (OSError, ValueError, TypeError):
        raise BankingCheckError("Kunde inte läsa en privat RSA-nyckel. Kontrollera sökvägen till din nedladdade PEM-fil.") from None
    now = int(time())
    token = jwt.encode({"iss": "enablebanking.com", "aud": "api.enablebanking.com",
                        "iat": now, "exp": now + 3600}, key, algorithm="RS256",
                       headers={"kid": application_id})
    return {"Authorization": "Bearer " + token, "Accept": "application/json"}


def get_json(path, headers, params=None):
    try:
        response = requests.get(API + path, headers=headers, params=params,
                                timeout=20, allow_redirects=False)
    except requests.RequestException:
        raise BankingCheckError("Kunde inte kontakta Enable Banking. Kontrollera nätanslutningen och försök igen.") from None
    if response.status_code != 200:
        raise BankingCheckError(f"Enable Banking svarade HTTP {response.status_code}. Kontrollera Application ID, nyckel och aktivering.")
    try:
        data = response.json()
    except ValueError:
        raise BankingCheckError("Enable Banking returnerade inte giltig JSON.") from None
    if not isinstance(data, dict):
        raise BankingCheckError("Oväntat svar från Enable Banking.")
    return data


def check_sandbox(environ):
    headers = authorization(environ)
    application = get_json("/application", headers)
    if application.get("environment") != "SANDBOX":
        raise BankingCheckError("Applikationen är inte registrerad i Sandbox. Använd uppgifterna för Sandbox-applikationen.")
    if application.get("active") is not True:
        raise BankingCheckError("Sandbox-applikationen är inte aktiv hos Enable Banking.")
    banks = get_json("/aspsps", headers, params={"country": "SE"})
    items = banks.get("aspsps")
    if not isinstance(items, list):
        raise BankingCheckError("Banklistan saknas i svaret från Enable Banking.")
    # Return only basic bank directory details, never keys, JWTs or account data.
    names = sorted({bank["name"] for bank in items
                    if isinstance(bank, dict) and bank.get("country") == "SE" and isinstance(bank.get("name"), str)})
    return names


def main():
    environ = runtime_environment(os.environ, ROOT / ".env")
    try:
        names = check_sandbox(environ)
    except BankingCheckError as error:
        print(error)
        return 1
    print("OK: anslutningen fungerar och applikationen är aktiv i Sandbox.")
    print(f"Tillgängliga bankalternativ för Sverige: {len(names)}")
    for name in names:
        print("- " + name)
    print("Inga bankkonton har anslutits i detta steg.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
