(() => {
  const section = document.querySelector('#klubbkassan');
  if (!section) return;
  const status = document.querySelector('#bank-status');
  const balances = document.querySelector('#bank-balances');
  const accounts = document.querySelector('#bank-accounts');
  const checked = document.querySelector('#bank-checked');
  const refresh = document.querySelector('#bank-refresh');
  const connect = document.querySelector('#bank-connect');
  const connectLabel = document.querySelector('#bank-connect-label');
  let loading = false;
  let lastLoad = 0;
  const labels = {ITAV: 'Tillgängligt saldo', ITBD: 'Bokfört saldo',
    CLAV: 'Tillgängligt vid senaste dagsavslut', CLBD: 'Bokfört vid senaste dagsavslut',
    OPAV: 'Ingående tillgängligt saldo', OPBD: 'Ingående bokfört saldo',
    XPCD: 'Beräknat saldo', PRCD: 'Tidigare bokfört saldo', INFO: 'Informationssaldo'};
  function element(tag, text, css) {
    const el = document.createElement(tag);
    if (text) el.textContent = text;
    if (css) el.className = css;
    return el;
  }
  function input(name, value) {
    const el = element('input'); el.type = 'hidden'; el.name = name; el.value = value;
    return el;
  }
  function selectAccount(data) {
    if (!data.admin) return;
    const form = element('form', '', 'bank-account-form');
    form.method = 'post'; form.action = section.dataset.selectUrl;
    form.append(input('csrf_token', section.dataset.csrf));
    const label = element('label', 'Välj klubbens konto');
    const select = element('select'); select.name = 'account_id'; select.required = true;
    select.append(new Option('Välj konto…', ''));
    for (const account of data.accounts) select.append(new Option(account.label, account.id));
    label.append(select); form.append(label);
    const consent = element('label', '', 'bank-consent');
    const checkbox = element('input');
    checkbox.type = 'checkbox'; checkbox.name = 'share_confirm'; checkbox.value = 'yes'; checkbox.required = true;
    consent.append(checkbox, document.createTextNode('Visa saldot för detta konto för alla klubbens godkända medlemmar.'));
    form.append(consent);
    const button = element('button', 'Visa klubbens valda konto', 'button'); button.type = 'submit';
    form.append(button); accounts.append(form);
  }
  async function load() {
    if (loading) return;
    loading = true;
    refresh.disabled = true;
    if (connect) connect.hidden = true;
    balances.replaceChildren(); accounts.replaceChildren(); checked.textContent = '';
    status.textContent = 'Hämtar saldo…';
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 35000);
    try {
      const response = await fetch(section.dataset.endpoint, {signal: controller.signal, cache: 'no-store'});
      if (!(response.headers.get('Content-Type') || '').includes('application/json')) {
        throw new Error(response.status === 503 ? 'Medlemstjänsten är tillfälligt otillgänglig. Försök igen.' : 'Ladda om sidan och logga in igen för att se saldot.');
      }
      const data = await response.json();
      if (connect && data.admin && (data.status === 'disconnected' || data.needs_reconnect)) {
        connect.hidden = false;
        connectLabel.textContent = data.needs_reconnect ? 'Förnya bankåtkomst' : 'Anslut Nordea en gång';
      }
      if (!response.ok || data.status === 'error') throw new Error(data.message || 'Saldot kunde inte hämtas. Försök igen senare.');
      if (data.status === 'unconfigured') status.textContent = 'Bankkopplingen är ännu inte aktiverad på servern.';
      else if (data.status === 'disconnected') status.textContent = data.admin ? 'Anslut Nordea för att hämta klubbkontots saldo.' : 'Kontoägaren har inte anslutit klubbens konto ännu.';
      else if (data.status === 'choose') {
        status.textContent = data.admin ? 'Banken är ansluten. Välj kontot som ska visas för klubben.' : 'Kontoägaren behöver välja klubbens konto innan saldot visas.';
        selectAccount(data);
      } else if (data.status === 'connected') {
        status.textContent = data.account;
        const priority = {ITAV: 0, ITBD: 1, CLAV: 2, CLBD: 3};
        const items = [...data.balances].sort((a, b) => (priority[a.type] ?? 9) - (priority[b.type] ?? 9));
        for (const balance of items) {
          const card = element('article', '', 'bank-balance');
          card.append(element('p', labels[balance.type] || balance.name, 'bank-balance-label'));
          const parts = balance.amount.split('.');
          const amount = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, '\u00a0') + (parts.length > 1 ? ',' + parts[1] : '');
          card.append(element('p', amount + ' ' + balance.currency, 'bank-amount'));
          if (balance.date) card.append(element('p', 'Bankens datum: ' + balance.date, 'calendar-note'));
          balances.append(card);
        }
        if (!data.balances.length) balances.append(element('p', 'Banken har inte lämnat några saldouppgifter för kontot.'));
        const timestamp = new Date(data.checked_at);
        if (!Number.isNaN(timestamp.getTime())) checked.textContent = 'Hämtat ' + new Intl.DateTimeFormat('sv-SE', {dateStyle: 'short', timeStyle: 'short', timeZone: 'Europe/Stockholm'}).format(timestamp);
      }
    } catch (error) {
      status.textContent = error.name === 'AbortError' ? 'Det tog för lång tid att hämta saldot. Försök igen.' : (error instanceof TypeError ? 'Saldot kunde inte hämtas. Kontrollera anslutningen och försök igen.' : error.message);
    } finally {
      clearTimeout(timeout); refresh.disabled = false;
      loading = false;
      lastLoad = Date.now();
    }
  }
  refresh.addEventListener('click', load);
  setInterval(() => { if (!document.hidden) load(); }, 5 * 60 * 1000);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && Date.now() - lastLoad >= 5 * 60 * 1000) load();
  });
  load();
})();
