# Steg 2 – första anropet till Enable Banking

Vi använder det befintliga Python-/Flask-projektet och dess `venv`.
`requests`, `PyJWT` och `cryptography` finns i `requirements.txt` och är
installerade i den lokala miljön.

## 1. Ange sandbox-uppgifterna

Fyll i de två nya raderna i din lokala `.env`:

```dotenv
ENABLE_BANKING_APPLICATION_ID=applikationens-uuid-fran-enable-banking
ENABLE_BANKING_PRIVATE_KEY_PATH=secrets/enablebanking.pem
```

Använd det riktiga Application ID:t och den faktiska sökvägen till den
PEM-fil som laddades ner vid registreringen. Mappen `E:\Lilla kulturklubben\secrets`
är skapad: lägg filen där och döp kopian till `enablebanking.pem`.
Application ID:t är fortfarande det UUID du fick vid registreringen, även
efter att filnamnet ändras. Sökvägen är förberedd i din lokala `.env`.

Du kan behålla nyckeln utanför projektet eller lägga den i `secrets/`.
`secrets/`, `*.pem` och `*.key` är undantagna från Git. Lägg aldrig nyckeln
i `static/`, en HTML-mall eller JavaScript. Behåll de befintliga Google- och
kalenderinställningarna i `.env`.

## 2. Kör testanropet

Från projektmappen i PowerShell:

```powershell
.\venv\Scripts\python.exe banking_check.py
```

Skriptet skapar en kortlivad RS256-signerad JWT med applikationens ID som
`kid`, och gör först `GET https://api.enablebanking.com/application`.
Det kontrollerar att applikationen är aktiv och tillhör `SANDBOX`.
Därefter görs `GET https://api.enablebanking.com/aspsps?country=SE`.
Resultatet är namnen på de svenska bankalternativ som just din
sandbox-applikation kan använda. Nordea väljs inte automatiskt.

Vid ett lyckat anrop börjar utskriften med:

```text
OK: anslutningen fungerar och applikationen är aktiv i Sandbox.
```

Detta steg ansluter inga bankkonton och hämtar inga saldon eller
transaktioner. Någon bank-callback behövs inte för de två GET-anropen.
Bankauktorisering, state-validering och callback byggs i nästa steg.

## Vanliga fel

- Saknade inställningar: fyll i de två variablerna i `.env` och kör igen.
- Nyckeln kan inte läsas: kontrollera filens sökväg och att det är den privata
  RSA-nyckeln som hör till applikationen.
- HTTP 401/403: kontrollera att Application ID och PEM-fil hör ihop och att
  applikationen är aktiv i Enable Banking.
- Fel miljö: använd sandbox-applikationens uppgifter för detta steg.

Skriptet skriver inte ut JWT:n, den privata nyckeln eller autentiseringshuvuden.
Det första riktiga anropet kan göras när dina sandbox-uppgifter har fyllts i.

## Samma nyckel på Render

Den lokala mappen följer inte med Git. Gör därför detta på Render:

1. Öppna tjänsten → **Environment → Secret Files → Add Secret File**.
2. Ange filnamnet `enablebanking.pem`.
3. Öppna din lokala PEM-fil i en textredigerare och klistra in hela innehållet
   direkt i Renders **Contents**, inklusive BEGIN- och END-raderna.
4. Ange `ENABLE_BANKING_APPLICATION_ID` under tjänstens miljövariabler.
5. Ange `ENABLE_BANKING_PRIVATE_KEY_PATH=/etc/secrets/enablebanking.pem`.
6. Spara och publicera tjänsten på nytt.

Samma Python-kod använder därmed den lokala filen på datorn och en Secret File
på Render. Sökvägarna är förberedda i `.env` respektive `.env.render`.
PEM-innehållet lagras inte i dessa miljöfiler och ska inte klistras in i chatten.
Render-instruktioner: [Secret Files](https://render.com/docs/configure-environment-variables#secret-files).

Officiell dokumentation:
[Quick Start](https://enablebanking.com/docs/api/quick-start/),
[API reference](https://enablebanking.com/docs/api/reference/).
