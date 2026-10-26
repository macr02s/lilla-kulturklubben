# Lilla kulturklubben

En Flask-app med startsida och en dynamisk evenemangsdel från Visit Stockholm.

## Kör lokalt

```powershell
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe app.py
```

Öppna http://127.0.0.1:5000.

## Evenemang

Kategorier, underkategorier och evenemang hämtas via Flask från det publika
dataanrop som används av https://www.visitstockholm.se/event/:
`https://www.visitstockholm.se/api/v1/singulareventdates/`.
Inga API-nycklar eller nya Python-paket behövs. Servern behöver åtkomst till
Visit Stockholm över HTTPS.

Varje sökning cachelagras i tio minuter i serverprocessen, med högst 128
cacheposter. Vid tillfälliga avbrott kan uppgifter som är högst en timme gamla
visas med en tydlig markering. Webbsidan uppdaterar resultaten var tionde minut
när fliken är synlig. Kategorier och resultat laddas också vid varje nytt val.
Evenemangens detaljsidor öppnas hos Visit Stockholm i en ny flik.

Integrationen använder deras webbplatsanrop, som saknar ett verifierat publikt
API-avtal och kan ändras. Anpassningen finns i `visit_stockholm.py`.
Fel visas i evenemangsdelen medan resten av startsidan fortsätter fungera.

## Kontroller

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/events.js
```

Enhetstesterna använder simulerade svar och kräver inte nätverksåtkomst.

## Klubben och Google-inloggning

`/klubben` visar en inloggningssida för besökare och medlemssidan för godkända,
inloggade medlemmar. En lokal `.env` har förberetts med en slumpgenererad
sessionsnyckel. Google-uppgifterna och medlemslistan behöver fyllas i innan
inloggningen aktiveras. `.env` och `instance/` är undantagna från Git.
I en ny installation: kopiera `.env.example` till `.env` och generera en egen
`SECRET_KEY` enligt kommentaren i filen.

### Aktivera lokalt

1. Öppna [Google Auth Platform](https://console.cloud.google.com/auth/overview)
   och välj eller skapa ett projekt för Lilla kulturklubben.
2. Ange appnamnet **Lilla kulturklubben** och de kontaktuppgifter som efterfrågas
   under **Branding**. Välj **External** som målgrupp under **Audience** för
   privata Google-konton. Lägg till medlemmarna som testanvändare om projektets
   testläge kräver det. Appens egen medlemslista gäller alltid oavsett Googles målgrupp.
3. Skapa en OAuth-klient under **Clients**, med typen **Web application**.
   Lägg till följande exakta adress under **Authorized redirect URIs**:

   ```text
   http://127.0.0.1:5000/auth/google/callback
   ```

4. Fyll i dessa värden i din lokala `.env`:

   ```dotenv
   GOOGLE_CLIENT_ID=klient-id-fran-google
   GOOGLE_CLIENT_SECRET=klienthemlighet-fran-google
   GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/auth/google/callback
   CLUB_MEMBERS=medlem1@gmail.com,medlem2@gmail.com,medlem3@example.com
   SESSION_COOKIE_SECURE=false
   ```

   Ange alla sex medlemmarnas faktiska Google-kontoadresser i `CLUB_MEMBERS`.
   Exempeladresserna ovan ska ersättas. Spara hemligheten direkt i `.env`;
   dela den inte i chatten eller i Git. Behåll den genererade `SECRET_KEY`.
5. Starta om Flask och öppna **http://127.0.0.1:5000/klubben**.
   Använd `127.0.0.1` även i webbläsaren, så att sessionskakan och callbacken
   använder samma värd. Om du föredrar `localhost`, ändra både adressen i
   Google och `GOOGLE_REDIRECT_URI` så att de matchar.

Inloggningen begär enbart `openid email profile`, inte Gmail eller Kalender.
Den använder Authlibs OpenID Connect-flöde med state, nonce och PKCE.
Appen kontrollerar verifierad e-postadress och medlemskap efter Googles
tokenvalidering. Kontots stabila Google-ID kopplas till medlemsadressen vid
första godkända inloggningen. Google-token sparas inte i medlemskakan.

Dokumentation: [Googles konfiguration och OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect),
[Authlibs Flask-integration](https://docs.authlib.org/en/latest/oauth2/client/web/flask.html).

### Administrera de sex medlemmarna

- Lägg till eller ta bort adresser i `CLUB_MEMBERS` och starta om appen.
  Listan har ingen hårdkodad gräns på sex personer.
- En borttagen medlem nekas tillgång vid nästa förfrågan, även om personen
  redan var inloggad. En tom lista släpper inte in någon.
- Det finns ingen separat administrationssida; för den här lilla gruppen
  hanteras listan i konfigurationen.
- Kopplingen mellan e-postadress och Google-ID sparas i `instance/club.sqlite3`.
  Säkerhetskopiera den tillsammans med övrig driftdata. Byte av en medlems
  Google-konto ska hanteras av administratören, inte automatiskt genom att
  ett annat konto råkar ha samma e-postadress.
- Inloggningen varar högst åtta timmar. Utloggning sker med ett formulär som
  skyddas mot CSRF och loggar bara ut personen från klubbens webbplats.

Inloggningskoden finns i `club_auth.py`, separat från evenemang och sidinnehåll,
så att fler inloggningsalternativ kan läggas till senare. Framtida privata
Flask-vyer ska skyddas med `@member_required` från den modulen.

### Gemensam Google-kalender

Medlemmar ser en kalenderöversikt och en knapp **Öppna i Google Kalender**
inne på `/klubben`. Kalenderdelen visas inte för besökare eller borttagna medlemmar.

Ange `CLUB_CALENDAR_ID` i den lokala `.env` och i Renders miljöinställningar.
Värdet är kalenderns **Kalender-ID**, inte hela inbäddningslänken eller den
hemliga iCal-adressen. Du hittar det i Google Kalender under **Inställningar →
välj kalender → Integrera kalender → Kalender-ID**. Det motsvarar även `src`
i inbäddningslänken, med `%40` avkodat till `@`.

Starta om Flask eller publicera Render-tjänsten efter ändringen. Kalendern
visas i månadsvy som standard, på svenska med tidszonen `Europe/Stockholm`.

Kalendern behöver vara delad med medlemmarnas Google-konton separat.
Appens medlemslista ändrar inte Googles delningsinställningar. Behåll kalendern
privat och dela den med respektive medlem i Google Kalender. Ge rätt att
redigera händelser om alla ska kunna lägga till klubbträffar. Dela inte
kalendern offentligt för att få inbäddningen att fungera.

En inbäddad privat kalender använder Googles egen webbläsarinloggning.
Webbplatsens Google-inloggning ger inte iframe-vyn en separat API-token.
Om fel Google-konto är valt eller webbläsaren blockerar inbäddad inloggning,
använd knappen för att öppna Google Kalender och välj rätt konto där.
Redigering sker i Google Kalender. Inga nya OAuth-behörigheter krävs i appen.

Googles instruktioner: [dela kalender](https://support.google.com/calendar/answer/37082?hl=sv),
[bädda in kalender](https://support.google.com/calendar/answer/41207?hl=sv).

### Vid publicering

Sätt en exakt HTTPS-callback för den riktiga domänen i både Google och
`GOOGLE_REDIRECT_URI`, till exempel `https://din-doman.se/auth/google/callback`.
Sätt `SESSION_COOKIE_SECURE=true`, behåll en stabil hemlig `SECRET_KEY` och
använd `FLASK_DEBUG=0`. Lägg samma variabler i driftplattformens hemliga
miljöinställningar om `.env` inte används där. Servermiljövariabler har företräde
framför `.env`. Ge `instance/` beständig, skrivbar lagring och använd samma
databas för alla appens processer på servern.

Den riktiga Google-inloggningen behöver provas med era egna klientuppgifter.
Testerna verifierar lokalt bland annat medlemskontroll, borttagen åtkomst,
utloggning, OAuth state och validering av signerade ID-token inklusive fel
signatur, utfärdare, mottagare, nonce och utgångstid.

### Nuvarande publicering på Render

Webbadress: https://lilla-kulturklubben.onrender.com/

Använd den befintliga **Web Service**-tjänsten på Render. Uppdatera dess kod
från projektets repository och använd:

- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 4`

Lägg in följande under tjänstens **Environment**. `.env.render.example` är
en referensfil; den laddas inte automatiskt och ska inte innehålla riktiga hemligheter.

| Variabel | Värde |
| --- | --- |
| `PUBLIC_BASE_URL` | `https://lilla-kulturklubben.onrender.com` |
| `GOOGLE_CLIENT_ID` | Klient-ID från Google |
| `GOOGLE_CLIENT_SECRET` | Klienthemligheten från Google |
| `SECRET_KEY` | En slumpgenererad, stabil hemlig nyckel |
| `CLUB_MEMBERS` | Era sex Google-kontoadresser, separerade med kommatecken |
| `SESSION_COOKIE_SECURE` | `true` |
| `FLASK_DEBUG` | `0` |

Registrera denna exakta **Authorized redirect URI** i Googles OAuth-klient:

```text
https://lilla-kulturklubben.onrender.com/auth/google/callback
```

Den lokala callback-adressen kan också finnas kvar i samma Google-klient.
För att kunna växla mellan lokal körning och Render ska båda adresserna vara
registrerade samtidigt. Din lokala `.env` använder `http://127.0.0.1:5000`
som `PUBLIC_BASE_URL`, medan Render har sin egen miljöinställning för samma
variabel. Ingen kodändring behövs när du växlar miljö. Appen tillåter vanliga
HTTP-sessionskakor som standard endast för lokal HTTP-körning på loopback;
HTTPS använder säkra kakor. En uttrycklig `SESSION_COOKIE_SECURE` har företräde.
Lämna `GOOGLE_REDIRECT_URI` tom eller ta bort den i Render om den redan är satt
till en annan adress. Appen skapar callbacken från `PUBLIC_BASE_URL`.
Om även den är tom används Renders automatiska `RENDER_EXTERNAL_URL`.
Miljöinställningarna behöver sparas och tjänsten startas om/publiceras på nytt.

Render har ett tillfälligt filsystem som standard. För nuvarande SQLite-lösning
behövs en **persistent disk**. Montera den på `/var/data` och ange:

```dotenv
CLUB_DATABASE=/var/data/club.sqlite3
```

Aktivera denna sökväg först när disken faktiskt är ansluten. Beständiga diskar
kräver en betald Render-tjänst. På en tjänst utan sådan lagring försvinner
kontokopplingarna vid omstart/publicering och medlemmarna behöver logga in
igen och kopplas på nytt. Medlemslistan i miljöinställningarna finns kvar,
men är inte en ersättning för den beständiga kontodatabasen. En extern
databas är ett alternativ som kräver en ytterligare kodanpassning.

Render-dokumentation: [miljövariabler](https://render.com/docs/environment-variables),
[beständiga diskar](https://render.com/docs/disks).

### Om domänen ändras senare

1. Koppla den nya domänen och HTTPS till webbplatsen på din driftplattform.
2. Lägg till `https://nya-domänen.se/auth/google/callback` i samma Google-klient.
3. Ändra `PUBLIC_BASE_URL` till den nya basadressen, utan sökväg.
4. Ta bort eller uppdatera en eventuell explicit `GOOGLE_REDIRECT_URI`; den
   variabeln har företräde framför basadressen om den är ifylld.
5. Starta om/publicera tjänsten och prova inloggning via den nya domänen.

Använd samma Google-klient, `SECRET_KEY`, medlemslista och beständiga databas.
Ingen ändring av Python-koden behövs för ett domänbyte. Medlemmarna behöver
logga in igen på den nya domänen eftersom webbläsarkakor hör till en viss värd.
Använd samma domän i webbläsaren som den konfigurerade callbacken under
inloggning; vid byte bör gamla länkar omdirigeras till den nya domänen.
