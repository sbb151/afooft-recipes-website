(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const app = $('#app');
  const listEl = $('#list');
  const detailEl = $('#detail');
  const searchEl = $('#search');
  const catsEl = $('#categories');

  const store = {
    get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
  };

  let recipes = [];
  let byId = new Map();
  let favorites = new Set(store.get('favorites', []));
  let recent = store.get('recent', []);
  let category = 'All';
  let query = '';
  let currentId = null;
  let wakeLock = null;
  let cook = store.get('cook', false);
  if (cook) app.classList.add('cook');

  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const norm = s => String(s).toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '');

  // ---------- data ----------
  async function load() {
    const res = await fetch('data/index.json');
    recipes = await res.json();
    recipes.forEach(r => { r._k = norm(r.t + ' ' + (r.k || '')); byId.set(r.id, r); });
    renderCategories();
    route();
  }

  function filtered() {
    let rs = recipes;
    if (category === 'Favorites') rs = rs.filter(r => favorites.has(r.id));
    else if (category === 'Recent') rs = recent.map(id => byId.get(id)).filter(Boolean);
    else if (category !== 'All') rs = rs.filter(r => r.c.includes(category));
    if (query) {
      const terms = norm(query).split(/\s+/).filter(Boolean);
      rs = rs.filter(r => terms.every(t => r._k.includes(t)));
      const q = norm(query);
      rs = rs.slice().sort((a, b) => (norm(b.t).includes(q) - norm(a.t).includes(q)));
    }
    return rs;
  }

  // ---------- render: categories ----------
  function renderCategories() {
    const counts = {};
    recipes.forEach(r => r.c.forEach(c => counts[c] = (counts[c] || 0) + 1));
    const cats = Object.keys(counts).sort((a, b) => a.localeCompare(b));
    const btn = (name, n) => `<button data-cat="${esc(name)}" class="${name === category ? 'active' : ''}">${esc(name)}<span class="n">${n ?? ''}</span></button>`;
    catsEl.innerHTML =
      btn('All', recipes.length) + btn('Favorites', favorites.size) + btn('Recent', recent.length) +
      '<h4>Categories</h4>' + cats.map(c => btn(c, counts[c])).join('');
  }

  catsEl.addEventListener('click', e => {
    const b = e.target.closest('button[data-cat]');
    if (!b) return;
    category = b.dataset.cat;
    app.classList.remove('menu');
    renderCategories();
    renderList();
    if (matchMedia('(max-width: 760px)').matches) location.hash = '';
  });

  // ---------- render: list ----------
  let listToken = 0;
  function renderList() {
    const rs = filtered();
    $('#listTitle').textContent = query ? `“${query}”` : category === 'All' ? 'All recipes' : category;
    $('#listCount').textContent = `${rs.length}`;
    const token = ++listToken;
    listEl.innerHTML = '';
    // render in chunks so a 2,000-item list stays snappy
    let i = 0;
    const chunk = () => {
      if (token !== listToken) return;
      const html = rs.slice(i, i + 150).map(r => `
        <li><a href="#/r/${r.id}" data-id="${r.id}" class="${r.id === currentId ? 'active' : ''}">
          <span class="thumb" ${r.img ? `style="background-image:url('${esc(r.img)}')"` : ''}>${r.img ? '' : esc(r.t[0] || '')}</span>
          <span><div class="t">${esc(r.t)}</div><div class="s">${esc(r.s || r.c.join(' · '))}</div></span>
        </a></li>`).join('');
      listEl.insertAdjacentHTML('beforeend', html);
      i += 150;
      if (i < rs.length) requestAnimationFrame(chunk);
    };
    chunk();
  }

  let searchTimer;
  searchEl.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => { query = searchEl.value.trim(); renderList(); }, 120);
  });

  // ---------- quantity scaling ----------
  const FRAC = { '½': .5, '⅓': 1 / 3, '⅔': 2 / 3, '¼': .25, '¾': .75, '⅛': .125, '⅜': .375, '⅝': .625, '⅞': .875, '⅕': .2, '⅙': 1 / 6 };
  const qtyRe = /^(\d+\s+\d+\/\d+|\d+\s*[½⅓⅔¼¾⅛⅜⅝⅞⅕⅙]|\d+\/\d+|\d*\.\d+|\d+|[½⅓⅔¼¾⅛⅜⅝⅞⅕⅙])(\s*(?:-|–|to)\s*(\d+\s+\d+\/\d+|\d+\/\d+|\d*\.\d+|\d+|[½⅓⅔¼¾⅛⅜⅝⅞⅕⅙]))?/;
  function parseQty(s) {
    s = s.trim();
    let m;
    if ((m = s.match(/^(\d+)\s+(\d+)\/(\d+)$/))) return +m[1] + m[2] / m[3];
    if ((m = s.match(/^(\d+)\s*([½⅓⅔¼¾⅛⅜⅝⅞⅕⅙])$/))) return +m[1] + FRAC[m[2]];
    if ((m = s.match(/^(\d+)\/(\d+)$/))) return m[1] / m[2];
    if (FRAC[s] != null) return FRAC[s];
    return parseFloat(s);
  }
  function fmtQty(n) {
    const whole = Math.floor(n + 1e-9);
    const rem = n - whole;
    const opts = [[0, ''], [.125, '⅛'], [.25, '¼'], [1 / 3, '⅓'], [.375, '⅜'], [.5, '½'], [.625, '⅝'], [2 / 3, '⅔'], [.75, '¾'], [.875, '⅞'], [1, '']];
    let best = opts[0];
    for (const o of opts) if (Math.abs(o[0] - rem) < Math.abs(best[0] - rem)) best = o;
    if (Math.abs(best[0] - rem) > .04 && n < 10) return String(+n.toFixed(2));
    const w = best[0] === 1 ? whole + 1 : whole;
    return (w ? w : '') + (best[1] ? best[1] : '') || '0';
  }
  function scaleLine(line, f) {
    if (f === 1) return esc(line);
    const m = line.match(qtyRe);
    if (!m) return esc(line);
    const a = fmtQty(parseQty(m[1]) * f);
    const b = m[3] ? fmtQty(parseQty(m[3]) * f) : null;
    return `<b>${a}${b ? '–' + b : ''}</b>` + esc(line.slice(m[0].length));
  }

  // ---------- render: detail ----------
  let scale = 1;
  async function showRecipe(id) {
    const meta = byId.get(id);
    if (!meta) { detailEl.innerHTML = '<div class="empty-detail">Recipe not found.</div>'; return; }
    currentId = id;
    app.dataset.view = 'detail';
    document.querySelectorAll('.recipe-list a.active').forEach(a => a.classList.remove('active'));
    const a = listEl.querySelector(`a[data-id="${id}"]`);
    if (a) a.classList.add('active');

    recent = [id, ...recent.filter(x => x !== id)].slice(0, 30);
    store.set('recent', recent);

    let r;
    try { r = await (await fetch(`data/r/${id}.json`)).json(); }
    catch { detailEl.innerHTML = '<div class="empty-detail">This recipe isn’t available offline yet.</div>'; return; }
    if (currentId !== id) return;
    scale = 1;
    document.title = `${r.title} · AFOOFT Recipes`;
    renderDetail(r);
    detailEl.scrollTop = 0;
  }

  function renderDetail(r) {
    const state = store.get('progress:' + r.id, { ing: [], step: -1 });
    const fav = favorites.has(r.id);
    const facts = [['Serves', r.servings], ['Prep', r.prep], ['Cook', r.cook], ['Total', r.total]]
      .filter(f => f[1]).map(f => `<span><b>${esc(f[0])}</b> ${esc(f[1])}</span>`).join('');
    const ing = (r.ingredients || []).map((x, i) => typeof x === 'object'
      ? `<li class="head">${esc(x.h)}</li>`
      : `<li data-i="${i}" class="${state.ing.includes(i) ? 'done' : ''}">${scaleLine(x, scale)}</li>`).join('');
    let n = -1;
    const steps = (r.directions || []).map((x, i) => typeof x === 'object'
      ? `<li class="head">${esc(x.h)}</li>`
      : (n++, `<li data-i="${i}" class="${i === state.step ? 'current' : ''} ${i < state.step ? 'done' : ''}">${esc(x)}</li>`)).join('');
    const body = (r.ingredients?.length && r.directions?.length)
      ? `<div class="cols">
          <section>${ing ? `<h2>Ingredients</h2><ul class="ingredients">${ing}</ul>` : ''}</section>
          <section>${steps ? `<h2>Directions</h2><ol class="steps">${steps}</ol>` : ''}
            ${r.notes ? `<h2>Notes</h2><div class="notes">${esc(r.notes)}</div>` : ''}</section>
        </div>`
      : `<div class="raw">${esc(r.text || '')}</div>`;

    detailEl.innerHTML = `
      <article class="recipe">
        <div class="toolbar">
          <a class="btn back" href="#/">‹ Recipes</a>
          <span class="spacer"></span>
          ${r.ingredients?.length ? `<span class="btn" id="scaleBtn" title="Scale quantities">× ${fmtQty(scale)}</span>` : ''}
          <button class="btn ${wakeLock ? 'on' : ''}" id="awakeBtn" title="Keep the screen on while cooking">☀︎<span class="lbl"> Keep awake</span></button>
          <button class="btn ${cook ? 'on' : ''}" id="cookBtn" title="Larger text">A↑<span class="lbl"> Big text</span></button>
          <button class="btn ${fav ? 'on' : ''}" id="favBtn">${fav ? '★' : '☆'}<span class="lbl"> Favorite</span></button>
          <button class="btn" id="resetBtn" title="Clear checked ingredients and steps">↺</button>
        </div>
        <div class="hero ${r.image ? '' : 'noimg'}">
          ${r.image ? `<img src="${esc(r.image)}" alt="" id="heroImg">` : ''}
          <div>
            <h1>${esc(r.title)}</h1>
            <div class="facts">${facts}${r.categories?.length ? `<span>${esc(r.categories.join(' · '))}</span>` : ''}</div>
            ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ''}
          </div>
        </div>
        ${body}
        <div class="source">From <i>${esc(r.file)}</i>${r.source ? ` · <a href="${esc(r.source)}" target="_blank" rel="noopener">original source</a>` : ''}</div>
      </article>`;

    const save = () => store.set('progress:' + r.id, state);
    detailEl.querySelector('.ingredients')?.addEventListener('click', e => {
      const li = e.target.closest('li[data-i]'); if (!li) return;
      const i = +li.dataset.i;
      li.classList.toggle('done');
      state.ing = li.classList.contains('done') ? [...state.ing, i] : state.ing.filter(x => x !== i);
      save();
    });
    detailEl.querySelector('.steps')?.addEventListener('click', e => {
      const li = e.target.closest('li[data-i]'); if (!li) return;
      const i = +li.dataset.i;
      state.step = state.step === i ? -1 : i;
      detailEl.querySelectorAll('.steps li[data-i]').forEach(x => {
        const j = +x.dataset.i;
        x.classList.toggle('current', j === state.step);
        x.classList.toggle('done', state.step >= 0 && j < state.step);
      });
      save();
    });
    $('#favBtn').onclick = () => {
      favorites.has(r.id) ? favorites.delete(r.id) : favorites.add(r.id);
      store.set('favorites', [...favorites]);
      renderCategories(); renderDetail(r);
    };
    $('#cookBtn').onclick = () => { cook = !cook; store.set('cook', cook); app.classList.toggle('cook', cook); $('#cookBtn').classList.toggle('on', cook); };
    $('#awakeBtn').onclick = toggleWake;
    $('#resetBtn').onclick = () => { store.set('progress:' + r.id, { ing: [], step: -1 }); renderDetail(r); };
    const sb = $('#scaleBtn');
    if (sb) sb.onclick = () => {
      const steps = [.5, 1, 1.5, 2, 3];
      scale = steps[(steps.indexOf(scale) + 1) % steps.length];
      renderDetail(r);
    };
    const img = $('#heroImg');
    if (img) img.onclick = () => window.open(img.src, '_blank');
  }

  async function toggleWake() {
    try {
      if (wakeLock) { await wakeLock.release(); wakeLock = null; }
      else if ('wakeLock' in navigator) {
        wakeLock = await navigator.wakeLock.request('screen');
        wakeLock.addEventListener('release', () => { wakeLock = null; $('#awakeBtn')?.classList.remove('on'); });
      } else { alert('This browser can’t keep the screen on. On iPhone, update to iOS 16.4 or later.'); }
    } catch (e) { wakeLock = null; }
    $('#awakeBtn')?.classList.toggle('on', !!wakeLock);
  }
  // Wake locks drop when the tab is hidden; take it back when the cook returns.
  let wantWake = false;
  document.addEventListener('visibilitychange', async () => {
    if (document.visibilityState === 'hidden') wantWake = !!wakeLock;
    else if (wantWake && !wakeLock) toggleWake();
  });

  // ---------- routing ----------
  function route() {
    const m = location.hash.match(/^#\/r\/([\w-]+)/);
    if (m) showRecipe(m[1]);
    else {
      app.dataset.view = 'list';
      currentId = null;
      document.title = 'AFOOFT Recipes';
      if (!matchMedia('(max-width: 760px)').matches && !detailEl.querySelector('.recipe')) {
        detailEl.innerHTML = '<div class="empty-detail">Pick a recipe to start cooking.</div>';
      }
    }
    if (!listEl.children.length || !m) renderList();
  }
  window.addEventListener('hashchange', route);

  $('#menuBtn').onclick = () => app.classList.toggle('menu');
  $('#scrim').onclick = () => app.classList.remove('menu');

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  load();
})();
