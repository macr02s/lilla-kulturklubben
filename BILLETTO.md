# Gemensamt evenemangsflöde och Billetto

Det nya flödet ligger efter kalendern på `/klubben` och kräver inloggning.
Startsidan behåller sina separata delar för Visit Stockholm och Ticketmaster.

## Skaffa Billetto-åtkomst

1. Skapa konto eller logga in på https://billetto.se.
2. Välj **Switch to Organiser** (arrangörsläget).
3. Öppna **Integrate → Developers** och generera ett API-nyckelpar.
4. Spara både API key och secret. Hemligheten visas bara en gång.
5. Lägg ihop dem med kolon i den privata `.env` och `.env.render`:

   ```dotenv
   BILLETTO_API_KEYPAIR='APIKey:APISecret'
   ```

6. Lägg samma värde, utan citattecken, som `BILLETTO_API_KEYPAIR` i
   Render Environment. Miljöfiler och nycklar skickas aldrig till GitHub.
7. Testa behörighet till **Public Event Search** innan anslutningen betraktas
   som verifierad. Ett arrangörskonto innebär inte ett bevis på att just
   publiceringsåtkomsten fungerar. Vid nekad åtkomst, be
   [Billetto support](https://support.billetto.com/) om tillgång till
   Public Event Search för att visa svenska evenemang på er webbplats.

Instruktionen följer
[Billettos autentiseringsguide](https://api.billetto.com/docs/obtaining-an-api-key).
Inga köp, biljetter, deltagare eller kontouppgifter hämtas.

## Flöde

`club_events.py` samlar kataloger från anslutna adaptrar. Visit Stockholm
används alltid, Ticketmaster och Billetto när respektive nyckel finns.
Tickster, AXS, Nortic, Kulturbiljetter och Eventbrite är inte anslutna.
De kan få egna adaptrar när dokumenterad åtkomst finns.

Varje post normaliseras till namn, plats, stad, datum, klockslag, kategori,
bild, biljettlänk och källor. Bara bekräftad stad Stockholm godtas;
Solna, Johanneshov och poster utan stad tas inte med i detta flöde.
De ursprungliga evenemangsdelarna på startsidan behåller sitt utbud.

Dubletter matchas konservativt på normaliserat namn, plats och exakt
datumintervall. Olika klockslag behålls som separata föreställningar.
En post utan klockslag kan slås ihop när bara ett känt klockslag finns.
Vid flera kända klockslag behålls den osäkra posten separat.
Okända platser matchas inte mellan olika källors länkar.

Direkta biljettkällor prioriteras före Visit Stockholm. Vid flera direkta
biljettkällor används deterministiskt Ticketmaster före Billetto; detta är
inte en garanti för bästa pris eller den enda officiella säljaren. Alla
matchade källor visas på kortet. Inga gissningar görs om spelplatsers
namnbyten eller liknande artistnamn. En del osäkra dubletter blir därför kvar.

Filtrering och sidbläddring sker efter normalisering och sammanslagning.
Månadsväljare, kategorier och underkategorier används på det samlade
utbudet. Kategorier normaliseras till några gemensamma grupper; okända
kategorier visas under Övrigt.

## Cache, fel och avgränsningar

Kataloger cachelagras tio minuter per period och serverprocess (högst 16
poster). Om en källa faller bort visas övrigas utbud med en markering och
ett nytt försök tillåts efter en minut. Vid totalt avbrott kan en sparad
katalog visas upp till en timme med markering. Högst 1 000 poster per källa
hämtas; ett begränsat urval markeras. Stora utbud kan därför vara
ofullständiga. Billetto avgränsas först med det verifierade filtret `region=Stockholm`
och sedan till staden Stockholm. API:t tar regionnamn, inte NUTS-kod, i
det verifierade svenska anropet. Listans `has_more` och sista evenemangets
ID används för nästa anrop med `after=ID`.

Billetto-datum konverteras till Europe/Stockholm med tidszonsdatabasen,
inklusive sommartid. Billetto-bilder används inte ännu, eftersom deras
publiceringsdokumentation ber om återpublicering från egen bildlagring.
Alla UTM-parametrar i Billetto-länkar bevaras. Vi skapar inga lokala kopior
av Billettos eventsidor. Om egna detaljsidor byggs behöver även deras
canonical-krav hanteras för dessa sidor. Kontrollera deras aktuella villkor
för avsedd publicering; huvudsidan för klubben pekas inte om till ett enskilt
Billetto-evenemang.

Adaptern använder det dokumenterade svenska public-events-anropet och
skickar `Api-Keypair` enbart till fast angiven Billetto-host. Omdirigeringar
följs inte. Nästa-sida-länkar måste ha samma host och API-sökväg.
Billetto-adaptern är verifierad med verklig Public Event Search-åtkomst,
Stockholm-filter, hela sidbläddringen och det gemensamma flödet. Det verkliga
svaret använder `location.location_name` och `categorization`, vilka
stöds tillsammans med dokumentationens tidigare fältnamn. Saknat platsnamn
gör att en post inte matchas mot en annan källas post, även när staden är
bekräftad. Billetto-bilder är fortfarande inte aktiverade.

Källor: [offentliga evenemang](https://api.billetto.com/reference/list-public-events),
[publiceringskrav](https://api.billetto.com/docs/requirements),
[platsfält](https://api.billetto.com/reference/location),
[sidbläddring](https://api.billetto.com/docs/pagination).
