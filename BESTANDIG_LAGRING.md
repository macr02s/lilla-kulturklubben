# Beständig lagring för Klubbkassan

Appen kan använda PostgreSQL för både medlemskopplingar och krypterad
bankåtkomst. Då ligger uppgifterna kvar när Render vilar, startas om eller
publicerar en ny kodversion. Om `DATABASE_URL` saknas används den lokala
SQLite-filen som tidigare. På Renders Free-tjänst är den filen tillfällig.

## Kostnadsfritt alternativ: Neon

Neon har en Free-plan utan tidsgräns, med resursgränser enligt deras
[prissida](https://neon.com/pricing). Den skiljer sig från Renders
kostnadsfria PostgreSQL-testdatabas som löper ut efter 30 dagar.

1. Öppna https://console.neon.tech och skapa ett konto eller logga in.
2. Skapa ett projekt med namnet **Lilla kulturklubben** och välj Free-planen.
   Välj gärna en EU-region. Behåll den PostgreSQL-version som föreslås.
3. Öppna **Connect** i projektet och kopiera dess PostgreSQL-anslutningssträng.
   Använd en anslutning med `sslmode=require` och behåll eventuella ytterligare
   säkerhetsparametrar som Neon anger.
4. Spara den direkt i din privata `.env.render` på en ny rad:

   ```dotenv
   DATABASE_URL='hela-anslutningsstrangen-fran-Neon'
   ```

   Anslutningssträngen innehåller databasens lösenord. Klistra inte in den i
   chatten eller i filer som ska skickas till GitHub.
5. Lägg samma värde som **DATABASE_URL** i Render → din webbservice →
   **Environment**. Behåll övriga Google-, kalender- och bankinställningar.
6. Publicera den uppdaterade koden och miljöinställningarna. Appen skapar
   de tabeller som behövs automatiskt i den nya databasen.
7. Logga in och anslut Nordea en gång i den nya databasen. En tidigare
   tillfällig SQLite-fil flyttas inte automatiskt. Medlemslistan och bankens
   krypteringsnyckel ska vara oförändrade.

Om vi ska kontrollera anslutningen från datorn kan du även lägga samma
`DATABASE_URL` i den privata lokala `.env`. Då använder båda miljöerna samma
databas. Samma `ENABLE_BANKING_ENCRYPTION_KEY`, bank-app-ID och medlemsägare
behöver användas för att båda ska kunna läsa samma bankanslutning.
Utan lokal `DATABASE_URL` fortsätter datorn använda sin egen SQLite-fil.

Neons databas kan gå ned i vila mellan förfrågningar men sparade data ligger
kvar. Den startas igen vid anslutning. Databasens faktiska tillgänglighet och
resursgränser styrs av vald plan.

## Alternativ: databas hos Render

Det går också att skapa en betald Render Postgres-databas i samma region som
webbappen. Lägg dess **Internal Database URL** som `DATABASE_URL` i webbappens
Environment. Välj och godkänn kostnaden i Render innan databasen skapas.
Renders fria PostgreSQL-databas är tidsbegränsad och passar inte som permanent
lagring här. En redan ansluten beständig disk med SQLite kan också behållas.

## Automatisk saldovisning

- Sidan hämtar saldo automatiskt efter inloggning och uppdaterar det var femte
  minut när fliken är synlig. Medlemmar delar en fem minuters servercache, så
  att flera öppna flikar inte behöver hämta samma uppgifter från banken igen.
- Giltig bankåtkomst återanvänds; ingen ny bankauktorisering startas vid
  vanlig sidvisning eller Google-inloggning.
- Nya bankanslutningar begär upp till bankens tillåtna giltighet, högst 180
  dagar. Nordea Sverige rapporterade 180 dagar vid kontrollen. Banken kan
  fortfarande avsluta eller förkorta åtkomsten och kräva nytt godkännande.
- En gammal endygnsanslutning förlängs inte genom en koduppdatering. Nästa
  faktiska förnyelse hos banken använder den nya, längre giltighetstiden.
- Knappen för bankanslutning visas bara för kontoägaren när anslutning saknas
  eller behöver förnyas. Ett tillfälligt nätfel startar ingen ny bankinloggning.
- Bankens sessions-ID och kontolista lagras krypterade med den befintliga
  `ENABLE_BANKING_ENCRYPTION_KEY`. Behåll nyckeln stabil i Render.

PostgreSQL-stödet är verifierat mot den konfigurerade Neon-databasen:
appens tabeller skapas, bundna parametrar och transaktioner fungerar och
tabellerna finns kvar efter återanslutning. En tillfällig testtabell togs bort
automatiskt efter kontrollen. Befintliga bank- och inloggningstester körs även
mot SQLite. Render behöver fortfarande få `DATABASE_URL` i Environment;
den privata `.env.render` läses inte automatiskt av Render.

Källor: [Neon: anslut från en app](https://neon.com/docs/connect/connect-from-any-app),
[Render: filsystem och fria databaser](https://render.com/docs/free),
[Enable Banking: giltighetstid](https://enablebanking.com/docs/api/reference/).
