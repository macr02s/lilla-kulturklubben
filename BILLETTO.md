# Gemensamt evenemangsflöde och Billetto

All evenemangssökning ligger på startsidan. Medlemssidan `/klubben`
innehåller klubbkassan och kalendern, utan evenemangslista eller sökskript.
Den tidigare sökrouten `/klubben/evenemang` är borttagen.

Startsidan hämtar offentliga evenemang via `/api/combined-events`.
Bankuppgifter och medlemsdata ingår aldrig i det publika evenemangsanropet.
Alla konfigurerade leverantörer är förvalda. Kryssrutorna kan avmarkeras
var för sig och **Välj alla** återställer dem. Om alla avmarkeras visas
ett tomt resultat och inga leverantörer kontaktas. Valen gäller den öppna
sidan och behålls vid månadsval, kategorifilter, sidbyte och uppdatering av
resultaten. En ny sidladdning börjar med alla valda igen.

API-parametern `sources` är en kommaseparerad lista med `visit-stockholm`,
`ticketmaster` och `billetto`. Utelämnad parameter väljer alla tillgängliga
leverantörer; `sources=` väljer ingen. Okända värden nekas. Valet sker
före hämtning, normalisering och sammanslagning så att avmarkerade källor
inte hämtas eller bidrar med länkar, bilder eller källhänvisning.
Varje period och leverantörsurval har en separat cachepost. Antalet avser
unika evenemang och korten visar sina valda ursprungskällor.

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
Tickster och Kulturbiljetter har valfria adaptrar som behöver egna nycklar; se
[TICKSTER_KULTURBILJETTER.md](TICKSTER_KULTURBILJETTER.md). AXS, Nortic och
Eventbrite är inte anslutna.

Varje post normaliseras till namn, plats, stad, datum, klockslag, kategori,
bild, biljettlänk och källor. Bara bekräftad stad Stockholm godtas;
Solna, Johanneshov och poster utan stad tas inte med i detta flöde.
De separata leverantörsanropen finns kvar för kompatibilitet, men används
inte som separata listor i gränssnittet.

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

Första sidan visar en snabb förhandsvisning från Visit Stockholm när den
källan är vald. Den behöver bara en API-sida innan de första korten
visas; den fulla katalogen laddas efteråt. Parametern `preview=1` godtas
bara för Visit Stockholm med sida 1. Förhandsvisningens antal är
preliminärt och **Visa fler** aktiveras efter den kompletta hämtningen. Övriga valda leverantörer fyller sedan på samma lista. Leverantörs-
kataloger delar en separat cache med högst 48 poster per process. Identiska
pågående hämtningar återanvänds och andra sökningar blockeras inte av
ett globalt nätverkslås. Fel eller ofullständiga kataloger prövas igen
efter en minut; fullständiga leverantörskataloger hålls i tio minuter.


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
inklusive sommartid. Billetto-bilder hämtas från API-fältet `image_link`. Bildlänkarna
översätts till signerade adresser under `/images/billetto/` så att bilden
serveras från vår egen Flask-server enligt publiceringsdokumentationen.
Ingen bild laddas ned under kataloghämtningen; kortets lazy loading startar
bildanropet när det behövs. En Billetto-bild kan också fylla en saknad
bild på ett kort som har slagits ihop med en annan källa.
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
bekräftad. Billetto-bilder är verifierade i riktiga evenemangskort via den egna
bildcachen, inklusive villkorlig HTTP-hämtning (304).

Källor: [offentliga evenemang](https://api.billetto.com/reference/list-public-events),
[publiceringskrav](https://api.billetto.com/docs/requirements),
[platsfält](https://api.billetto.com/reference/location),
[sidbläddring](https://api.billetto.com/docs/pagination).

## Billetto-bildcache

`billetto_images.py` verifierar signerade bildadresser och accepterar endast
HTTPS från den verifierade bildhosten `billetto.imgix.net`. Omdirigeringar
följs inte. API-nycklar och besökarens cookies skickas aldrig till bildhosten.
Bildfiler sparas atomiskt i `instance/event-images/billetto/`, som redan
är undantagen från Git. Giltig JPEG, PNG, WebP eller GIF kontrolleras via
filens signatur; HTML och SVG accepteras inte. Högst 5 MiB per bild hämtas.

Cachen gäller ett dygn och begränsas till 256 filer och 128 MiB. Endast
appens egna hash-namngivna cachefiler städas. Samtidiga anrop för samma bild
delar nedladdning inom processen. Svaren har innehållstyp, nosniff och ETag
för villkorlig HTTP-cache. Ett fel ger 404 och kortets befintliga reservbild.
Cachefilerna är tillfälliga på Render Free och kan hämtas på nytt efter
omstart. Ingen ny miljövariabel krävs; appens befintliga `SECRET_KEY`
används med en separat signeringssalt för de publika bildadresserna.
