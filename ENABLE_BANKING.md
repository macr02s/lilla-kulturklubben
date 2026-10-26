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
just klubbkontot och bekräfta delningen om flera konton returneras.
Om banken returnerar exakt ett konto väljs det automatiskt enligt kontoägarens
godkännande, och dess saldo visas för klubbens godkända medlemmar.
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
4. Om banken lämnar ett enda konto väljs det automatiskt. Om flera konton
   lämnas väljer du klubbens konto och bekräftar delningen med medlemmarna.
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

### Anslut ett riktigt Nordea-konto

Saldoflödet är redan implementerat i det befintliga Flask-projektet. Ingen
ny `app.py` behöver byggas. De befintliga adresserna är:

- `POST /klubben/bank/anslut`: kontoägaren startar bankens godkännande.
- `GET /callback` eller `/bank/callback`: callbacken byter godkännandekod mot en banksession.
- `POST /klubben/bank/valj-konto`: ägaren väljer och bekräftar klubbkontot.
- `GET /klubben/bank/saldo`: godkända medlemmar ser saldot på det valda kontot.

Lägg produktionens nya PEM-fil i `secrets/`, gärna med sitt ursprungliga
UUID-filnamn för att hålla isär den från sandbox-nyckeln. Konfigurera sedan:

```dotenv
ENABLE_BANKING_APPLICATION_ID=produktionens-application-id
ENABLE_BANKING_PRIVATE_KEY_PATH=secrets/produktionens-application-id.pem
ENABLE_BANKING_ENVIRONMENT=PRODUCTION
ENABLE_BANKING_CALLBACK_PATH=/callback
```

Detta projekt använder `ENABLE_BANKING_APPLICATION_ID` och
`ENABLE_BANKING_PRIVATE_KEY_PATH`, inte `ENABLEBANKING_APP_ID` eller
`ENABLEBANKING_PRIVATE_KEY`. Nyckeln läses från en serverfil.

1. Kontrollera att produktionsappen är aktiv och att klubbens verkliga konto
   är tillåtet för appen hos Enable Banking. En kontrollpanelkoppling ersätter
   inte bankauktoriseringen som webbplatsen behöver genomföra.
2. Registrera rätt callback-adresser även i **produktionsappen**.
   Registrering i sandbox-appen gäller inte automatiskt för produktionsappen.
3. Kör `python banking_check.py` för att verifiera att ID och nyckel hör till
   en aktiv **PRODUCTION**-app. Denna kontroll läser bara app- och bankmetadata.
4. På Render: byt `ENABLE_BANKING_APPLICATION_ID` till produktionsappens ID,
   byt Secret File `enablebanking.pem` till den nya produktionsnyckeln och
   sätt `ENABLE_BANKING_ENVIRONMENT=PRODUCTION`. Behåll den säkra sökvägen
   `/etc/secrets/enablebanking.pem`, kontoägarens adress och krypteringsnyckeln.
5. Efter publicering: logga in som kontoägaren, välj **Anslut / förnya Nordea**
   och godkänn bankåtkomsten. Ett enda konto väljs automatiskt; flera konton
   kräver ett uttryckligt val innan något saldo delas.

IBAN hårdkodas inte i koden. Appen använder det interna konto-ID som lämnas
efter bankens godkännande. En tidigare sandbox-session kan inte användas som
produktionssession; en ny bankauktorisering och ett nytt kontoval krävs.

### Den verifierade produktionskonfigurationen

Den nya produktionsnyckeln har verifierats mot API:t: appen är aktiv och
har Account Information-tillgång. `.env` och den privata `.env.render` har
uppdaterats till den nya appen och `PRODUCTION`. Befintliga Google- och
krypteringsnycklar har behållits.

Produktionsappen har för närvarande följande callback registrerad:

```text
https://lilla-kulturklubben.onrender.com/callback
```

Därför används `ENABLE_BANKING_CALLBACK_PATH=/callback`. För lokal
bankauktorisering behöver även denna adress registreras i produktionsappen:

```text
http://127.0.0.1:5000/callback
```

På Render: importera de uppdaterade miljövärdena från `.env.render` och ersätt
innehållet i Secret File `enablebanking.pem` med **produktionens** PEM-fil.
Behåll filnamnet på Render så att `/etc/secrets/enablebanking.pem` fortfarande
stämmer. Koden och inställningarna behöver publiceras innan banken kan anslutas.
API-kontrollen skapade ingen banksession och hämtade inga kontouppgifter.

Officiell dokumentation:
[Quick Start](https://enablebanking.com/docs/api/quick-start/),
[API reference](https://enablebanking.com/docs/api/reference/).
