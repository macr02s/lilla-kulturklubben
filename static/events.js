document.querySelectorAll('[data-events-widget]').forEach(section => {
  const categories = section.querySelector('[data-role="categories"]');
  const subcategories = section.querySelector('[data-role="subcategories"]');
  const results = section.querySelector('[data-role="results"]');
  const status = section.querySelector('[data-role="status"]');
  const more = section.querySelector('[data-role="more"]');
  const retry = section.querySelector('[data-role="retry"]');
  const sourceName = section.dataset.source;
  let category = '', subcategory = '', next = null, allCategories = [], controller;
  let failedPage = 1, pending = false;

  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text) element.textContent = text;
    if (className) element.className = className;
    return element;
  }

  function filter(label, slug, selected, select) {
    const button = node('button', label, 'filter-button');
    button.type = 'button';
    button.setAttribute('aria-pressed', String(selected));
    button.addEventListener('click', () => select(slug));
    return button;
  }

  function renderFilters() {
    categories.replaceChildren(filter('Alla evenemang', '', !category, selectCategory));
    for (const item of allCategories) {
      categories.append(filter(item.title, item.slug, item.slug === category, selectCategory));
    }
    const children = allCategories.find(item => item.slug === category)?.subcategories || [];
    subcategories.hidden = !children.length;
    subcategories.replaceChildren();
    if (children.length) {
      subcategories.append(filter('Alla i kategorin', '', !subcategory, selectSubcategory));
      for (const item of children) {
        subcategories.append(filter(item.title, item.slug, item.slug === subcategory, selectSubcategory));
      }
    }
  }

  function selectCategory(slug) {
    category = slug;
    subcategory = '';
    renderFilters();
    // Replacing filter controls must preserve keyboard focus.
    [...categories.children].find(button => button.getAttribute('aria-pressed') === 'true')?.focus();
    load(1);
  }

  function selectSubcategory(slug) {
    subcategory = slug;
    renderFilters();
    [...subcategories.children].find(button => button.getAttribute('aria-pressed') === 'true')?.focus();
    load(1);
  }

  const formatter = new Intl.DateTimeFormat('sv-SE', {day: 'numeric', month: 'short', year: 'numeric'});
  function date(value) {
    if (!value) return '';
    const parsed = new Date(value + 'T12:00:00');
    return Number.isNaN(parsed.getTime()) ? '' : formatter.format(parsed);
  }

  function card(event) {
    const link = node('a', '', 'event-card');
    link.href = event.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    if (event.image) {
      const figure = node('figure');
      const img = node('img');
      img.src = event.image;
      img.alt = event.alt;
      img.loading = 'lazy';
      img.referrerPolicy = 'no-referrer';
      img.addEventListener('error', () => figure.replaceChildren(node('div', '✳', 'event-placeholder')), {once: true});
      figure.append(img);
      if (event.credit) figure.append(node('figcaption', event.credit));
      link.append(figure);
    } else link.append(node('div', '✳', 'event-placeholder'));
    const body = node('div', '', 'event-body');
    body.append(node('small', event.category), node('h3', event.title));
    const start = date(event.start), end = date(event.end);
    body.append(node('p', start + (end && end !== start ? ' – ' + end : '') + (event.time ? ' · ' + event.time : ''), 'event-date'));
    if (event.venue) body.append(node('p', event.venue));
    body.append(node('span', `Läs mer hos ${sourceName} ↗`, 'event-read-more'));
    link.append(body);
    return link;
  }

  async function load(page) {
    controller?.abort();
    controller = new AbortController();
    const current = controller;
    const timeout = setTimeout(() => current.abort('timeout'), 20000);
    failedPage = page;
    pending = true;
    results.setAttribute('aria-busy', 'true');
    retry.hidden = true;
    more.disabled = true;
    if (page === 1) {
      results.replaceChildren();
      more.hidden = true;
    }
    status.textContent = 'Hämtar evenemang…';
    const query = new URLSearchParams({category, subcategory, page});
    try {
      const response = await fetch(`${section.dataset.endpoint}?${query}`, {signal: current.signal});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error);
      if (current !== controller) return;
      allCategories = data.categories;
      // Keep the controls stable while visitors navigate with a keyboard.
      if (!categories.children.length) renderFilters();
      for (const event of data.events) results.append(card(event));
      next = data.next;
      more.hidden = !next;
      const title = allCategories.find(item => item.slug === category)?.title;
      status.textContent = data.count === 0 ? 'Inga evenemang hittades. Prova en annan kategori.' :
        `${data.count} evenemang${title ? ' inom ' + title : ''} · Visar ${results.children.length}`;
      if (data.truncated) status.textContent += ' · Urval av de närmaste evenemangen.';
      if (data.stale) status.textContent += ' · Tillfälligt visas tidigare hämtade uppgifter.';
    } catch (error) {
      if (current !== controller) return;
      status.textContent = `Evenemangen kunde inte hämtas just nu. Försök igen eller besök ${sourceName} via länken ovan.`;
      retry.hidden = false;
      more.hidden = true;
    } finally {
      clearTimeout(timeout);
      if (current === controller) {
        pending = false;
        results.setAttribute('aria-busy', 'false');
        more.disabled = false;
      }
    }
  }
  more.addEventListener('click', () => { if (!pending && next) load(next); });
  retry.addEventListener('click', () => load(failedPage));
  // Refresh visible results without interrupting an ongoing request.
  setInterval(() => {
    if (!document.hidden && !pending) load(1);
  }, 10 * 60 * 1000);
  load(1);
});
