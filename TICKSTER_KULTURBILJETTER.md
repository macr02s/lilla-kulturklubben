# Tickster och Kulturbiljetter

Båda adaptrarna ingår i den gemensamma startsidesökningen. Det finns ingen
evenemangssökning på medlemssidan. En leverantör visas som valbar när dess
nyckel finns i serverns miljö. Nycklarna skickas aldrig till webbläsaren.
De nya adaptrarna är testade med simulerade svar från de officiella API-
formaten. Verklig åtkomst och svarsformat ska verifieras när nycklar finns.

## Skaffa nycklar

- Tickster: ansök via https://developer.tickster.com/register . Ange att det
  gäller Event API v1.0, att ni visar offentliga Stockholm-evenemang på
  https://lilla-kulturklubben.onrender.com och länkar vidare till Tickster.
- Kulturbiljetter: be info@kulturbiljetter.se om nyckel till Events API v3.
  Beskriv samma användning: automatisk evenemangslista för Stockholm med
  evenemangens egna länkar, utan biljettköp på klubbens webbplats.

Förslag att själv skicka till respektive leverantör:

> Hej! Jag driver Lilla kulturklubben, en liten kulturklubb i Stockholm.
> Vi vill visa era offentliga Stockholm-evenemang i en gemensam
> evenemangssökning på https://lilla-kulturklubben.onrender.com.
> Besökaren klickar vidare till er egen eventsida för information och köp.
> Jag önskar en API-nyckel för detta och information om eventuella
> anropsgränser eller villkor för publicering av evenemang och bilder.

Ingen ansökan eller e-post skickas automatiskt av appen.

## Konfiguration

Fyll i den privata `.env` lokalt och `.env.render` som kopieringsunderlag:

```dotenv
TICKSTER_API_KEY='nyckeln-fran-Tickster'
KULTURBILJETTER_API_KEY='nyckeln-fran-Kulturbiljetter'
```

Lägg samma två variabler i Render Environment, utan omgivande citattecken.
`.env.render` läses inte automatiskt av Render. Starta om appen efter ändring.
Tomma variabler innebär att källorna inte används eller visas i urvalet.

API-valen heter `tickster` och `kulturbiljetter`. De kan kombineras med de
befintliga leverantörerna i `sources` eller avmarkeras med kryssrutorna.
Avmarkerade leverantörer kontaktas inte. Cacheposter skiljer på nycklar,
månadsperiod och leverantörsurval.

## Tickster

Använder `GET https://event.api.tickster.com/api/v1.0/sv/events` med
`X-API-KEY`, `query=city:Stockholm`, `take=100` och `skip`.
Stad och svensk landskod kontrolleras även i svarens spelplatsdata. Privata
försäljningar, avbokningar samt överordnade produktions-/samlingsposter
visas inte som egna evenemang. UTC-datum omvandlas till Europe/Stockholm.

Katalogen delas mellan månads- och leverantörsval och cachelagras en timme
per serverprocess för att begränsa API-anrop. Vid avbrott kan en tidigare
katalog visas i upp till två timmar med markering. Högst tio sidor hämtas inom en timeoutbudget om tolv sekunder;
begränsat utbud markeras. Månadsurval görs lokalt i katalogen.

Söksvaret saknar bild/kategori. Tickster-bilder visas inte, eftersom deras
API anger att bilder ska laddas ned och serveras från egen lagring.
Ingen gissad kategori skapas; posten hamnar i Övrigt om ingen annan matchad
källa har en prioriterad kategori. Länken går till `infoUrl`, med `shopUrl`
som reserv. Endast Tickster-domäner accepteras.

## Kulturbiljetter

Använder Events API v3 med `Authorization: Token ...`. Indexet innehåller
ID och ETag, medan stad, bilder och föreställningar kräver ett separat
anrop till `/api/v3/events/{ID}`. Indexet cachelagras tio minuter, och
ETag/If-None-Match används för att återanvända oförändrade detaljer.

Första hämtningen sker i omgångar om högst 40 detaljer, med fyra
samtidiga anrop och högst tolv sekunders väntan för detaljanropen per
omgång. Pågående anrop kan avsluta efter svarstiden och sparar då sitt
resultat i cachen. Vid ofullständig katalog visas det som pågående
uppdatering; servercachen och den synliga webbsidan tillåter ny omgång efter
en minut. Stora kataloger kan därför behöva flera omgångar innan allt
utbud är känt. Bara de första 1 000 indexposterna behandlas, och högst
2 000 detaljer behålls i minnet per process. Detta är cache, inte permanent
lagring. Renders omstart innebär att den publika katalogen värms upp igen.

Varje föreställning får sin egen tid och matchas mot sitt location_id.
Endast spelplatser med staden Stockholm inkluderas. UNIX-tider omvandlas
till Europe/Stockholm; `date_only` döljer klockslag. Bilder måste ligga på
Kulturbiljetters domän och kortet länkar till `url_event_page`. Inga
kassa-, boknings- eller personuppgiftsanrop görs. API:t anger ingen kategori,
så fristående poster visas under Övrigt.

## Sammanslagning

Samma befintliga konservativa namn-/plats-/datum-/tidsmatchning används för
alla fem källor. Olika föreställningstider behålls. En nattkonsert eller
ett flerdagarsarrangemang kan ha olika datumintervall i olika källor och
därför inte slås ihop automatiskt. Direkta biljettkällor prioriteras
Ticketmaster, Billetto, Tickster, Kulturbiljetter, därefter Visit Stockholm.
Det är en stabil prioriteringsordning, inte en prisjämförelse eller garanti
för att en viss säljare är den enda officiella.

Källor: [Tickster v1.0](https://developer.tickster.com/documentation/events/1.0),
[OpenAPI](https://event.api.tickster.com/swagger/index.html),
[Kulturbiljetter Events API](https://kulturbiljetter.se/api/events/).
