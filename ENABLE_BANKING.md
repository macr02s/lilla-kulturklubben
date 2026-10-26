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

## Steg 3 – saldovisning i den inloggade delen

Saldodelen finns på `/klubben` för alla godkända medlemmar, enligt kontoägarens
uttryckliga godkännande. Endast kontoägaren i `ENABLE_BANKING_ADMIN_EMAIL` får
ansluta banken och välja konto. Efter bankens godkännande måste ägaren välja
just klubbkontot och bekräfta delningen innan någon annan kan se saldot.
Övriga konton och bankens sessions-ID lämnas inte till vanliga medlemmar.

Följande inställningar har förberetts i den privata `.env` och `.env.render`:

```dotenv
ENABLE_BANKING_ADMIN_EMAIL=kontoinnehavarens-google-adress
ENABLE_BANKING_ENVIRONMENT=SANDBOX
ENABLE_BANKING_ENCRYPTION_KEY=en-stabil-fernet-nyckel
```

Använd de faktiska värdena som finns i dina privata filer, inte exemplen ovan.
Krypteringsnyckeln är separat från Flask-nyckeln. Behåll samma nyckel vid
omstarter och spara den säkert; annars kan sparad bankåtkomst inte läsas.
Bankens sessions-ID och kontolista sparas krypterade i klubbens SQLite-databas.
Webbläsaren får ingen banksession eller privat nyckel.

### Registrera bankens callback-adresser

Den nuvarande Enable Banking-applikationen har endast
`http://localhost:5000/callback` registrerad. Lägg till dessa adresser i
applikationens tillåtna redirect URLs i Enable Banking Control Panel:

```text
http://127.0.0.1:5000/bank/callback
https://lilla-kulturklubben.onrender.com/bank/callback
```

Detta är bankens callback-adresser, separata från Googles
`/auth/google/callback`. Appen räknar ut bankadressen från samma basadress som
Google-inloggningen för att webbläsarens inloggningskaka ska följa med.
En framtida egen domän behöver sin egen `/bank/callback` registrerad också.

### Prova ett testsaldo

1. Registrera callback-adresserna ovan hos Enable Banking.
2. Starta om Flask och logga in på `http://127.0.0.1:5000/klubben` som kontoägaren.
3. Klicka **Anslut / förnya Nordea (test)** och följ sandboxens godkännande.
4. Efter återkomsten väljer du klubbens konto bland de godkända kontona och
   bekräftar att dess saldo ska visas för alla godkända medlemmar.
5. Sidan hämtar kontots saldouppgifter. **Uppdatera saldo** gör ett nytt anrop.

Saldot är tydligt märkt **Sandbox · testsaldo**. Tillgängligt saldo, bokfört
saldo och eventuella andra saldotyper visas var för sig med bankens datum;
de summeras inte. När bankåtkomsten avslutas eller går ut behöver kontoägaren
ansluta på nytt. Appen begär enbart saldotillgång, inte transaktioner eller betalningar.
Saldo-anrop görs först när den privata bankdelen används; kalendern behöver
ingen bankåtkomst.

### Render

Publicera kodändringarna och uppdatera Render med bankvariablerna från
`.env.render`. Lägg PEM-filen som Secret File enligt instruktionerna ovan.
Krypterad bankanslutning använder samma databas som medlemskopplingarna.
Konfigurera beständig datalagring om anslutningen ska överleva publiceringar
och omstarter; den nuvarande fria Render-tjänstens tillfälliga lagring räcker
inte för beständiga bankanslutningar.

Ett riktigt saldo kräver en separat **PRODUCTION**-applikation och dess
nyckel, aktiverad åtkomst hos Enable Banking samt godkännande från banken.
Att enbart ändra miljövariabeln gör inte sandbox-nyckeln till en produktionsnyckel.
Appen kontrollerar att API-applikationens faktiska miljö stämmer innan anslutningen startas.

Officiell dokumentation:
[Quick Start](https://enablebanking.com/docs/api/quick-start/),
[API reference](https://enablebanking.com/docs/api/reference/).
