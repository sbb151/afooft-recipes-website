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
    base = await res.json();
    let remote = null;
    try { const er = await fetch('data/edits.json', { cache: 'no-store' }); if (er.ok) remote = await er.json(); } catch {}
    // GitHub Pages takes a minute to publish a save, so keep whichever copy is newer
    const local = store.get('edits', null);
    edits = normEdits(local && (!remote || (local.updated || '') > (remote.updated || '')) ? local : remote);
    applyEdits();
    route();
  }

  // ---------- edits made on the site (data/edits.json) ----------
  // added: recipes typed in on the site; changed: file -> edited recipe; deleted: files hidden from the site.
  let base = [];
  let edits = normEdits(null);
  function normEdits(e) { return { updated: e?.updated || '', added: e?.added || [], changed: e?.changed || {}, deleted: e?.deleted || [] }; }
  const ingText = r => (r.ingredients || []).filter(x => typeof x === 'string').join(' ').toLowerCase().slice(0, 600);
  function entryFor(r) {
    return { id: r.id, f: r.file, t: r.title, c: r.categories?.length ? r.categories : ['Other'], img: r.thumb || r.image || null,
             s: (r.categories || []).slice(0, 2).join(', '), k: ingText(r), _full: r };
  }
  function applyEdits() {
    const gone = new Set(edits.deleted);
    recipes = base.filter(r => !gone.has(r.f)).map(r => {
      const ch = edits.changed[r.f];
      return ch ? { ...entryFor({ ...ch, id: r.id, file: r.f }), img: ch.thumb || ch.image || r.img } : r;
    });
    for (const a of edits.added) if (!gone.has(a.file)) recipes.push(entryFor(a));
    recipes.sort((a, b) => a.t.localeCompare(b.t));
    byId = new Map();
    recipes.forEach(r => { r._k = norm(r.t + ' ' + (r.k || '')); byId.set(r.id, r); });
    renderCategories();
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
          <span class="thumb" ${r.img ? `style="background-image:url('${esc(localPhotos[r.img] || r.img)}')"` : ''}>${r.img ? '' : esc(r.t[0] || '')}</span>
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
  // Amounts later in a line ("4 cups/480 grams flour", "plus 2 tablespoons") scale too,
  // but only when a unit follows, so can sizes like "(29-ounce)" stay put.
  const NUM = String.raw`\d+\s+\d+\/\d+|\d+\s*[½⅓⅔¼¾⅛⅜⅝⅞⅕⅙]|\d+\/\d+|\d*\.\d+|\d+|[½⅓⅔¼¾⅛⅜⅝⅞⅕⅙]`;
  const UNITS = 'cups?|c\\.?|tablespoons?|tbsps?\\.?|tbs\\.?|teaspoons?|tsps?\\.?|ounces?|oz\\.?|pounds?|lbs?\\.?|grams?|g|kg|kilograms?|ml|milliliters?|l|liters?|litres?|quarts?|qts?|pints?|sticks?|cloves?|slices?|pieces?|eggs?|large|medium|small';
  const innerRe = new RegExp(String.raw`(^|[\s/(])(${NUM})(?=\s*(?:${UNITS})\b)`, 'gi');
  function scaleLine(line, f) {
    if (f === 1) return esc(line);
    const m = line.match(qtyRe);
    let head = '', rest = line;
    if (m) {
      const a = fmtQty(parseQty(m[1]) * f);
      const b = m[3] ? fmtQty(parseQty(m[3]) * f) : null;
      head = `<b>${a}${b ? '–' + b : ''}</b>`;
      rest = line.slice(m[0].length);
    }
    const parts = [];
    let last = 0;
    rest.replace(innerRe, (all, pre, num, idx) => {
      const at = idx + pre.length;
      parts.push(esc(rest.slice(last, at)), `<b>${fmtQty(parseQty(num) * f)}</b>`);
      last = at + num.length;
      return all;
    });
    parts.push(esc(rest.slice(last)));
    return head + parts.join('');
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

    let r = meta._full;
    if (!r) {
      try { r = await (await fetch(`data/r/${id}.json`)).json(); }
      catch { detailEl.innerHTML = '<div class="empty-detail">This recipe isn’t available offline yet.</div>'; return; }
    }
    r = { ...r, id, file: meta.f };
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
          <a class="btn back" href="#/">‹<span class="lbl"> Recipes</span></a>
          <span class="spacer"></span>
          ${r.ingredients?.length ? `<span class="btn" id="scaleBtn" title="Scale quantities">× ${fmtQty(scale)}</span>` : ''}
          <button class="btn ${wakeLock ? 'on' : ''}" id="awakeBtn" title="Keep the screen on while cooking">☀︎<span class="lbl"> Keep awake</span></button>
          <button class="btn ${cook ? 'on' : ''}" id="cookBtn" title="Larger text">A↑<span class="lbl"> Big text</span></button>
          <button class="btn ${fav ? 'on' : ''}" id="favBtn">${fav ? '★' : '☆'}<span class="lbl"> Favorite</span></button>
          <button class="btn" id="resetBtn" title="Clear checked ingredients and steps">↺</button>
          <button class="btn" id="editBtn" title="Edit this recipe">✎<span class="lbl"> Edit</span></button>
          <button class="btn" id="delBtn" title="Delete this recipe from the site">🗑</button>
        </div>
        <div class="hero ${r.image ? '' : 'noimg'}">
          ${r.image ? `<img src="${esc(localPhotos[r.image] || r.image)}" alt="" id="heroImg">` : ''}
          <div>
            <h1>${esc(r.title)}</h1>
            <div class="facts">${facts}${r.categories?.length ? `<span>${esc(r.categories.join(' · '))}</span>` : ''}</div>
            ${r.description ? `<p class="desc">${esc(r.description)}</p>` : ''}
          </div>
        </div>
        ${body}
        <div class="source">${String(r.file).startsWith('site:') ? 'Added on the site' : `From <i>${esc(r.file)}</i>`}${edits.changed[r.file] ? ' · edited on the site' : ''}${r.source ? ` · <a href="${esc(r.source)}" target="_blank" rel="noopener">original source</a>` : ''}</div>
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
    $('#editBtn').onclick = () => openEditor(r);
    $('#delBtn').onclick = () => deleteRecipe(r);
  }

  // ---------- saving to GitHub ----------
  const REPO = 'sbb151/afooft-recipes-website';
  const api = (path, opts = {}) => fetch(`https://api.github.com/repos/${REPO}/contents/${path}`, {
    ...opts, headers: { Authorization: `Bearer ${store.get('token', '')}`, Accept: 'application/vnd.github+json', ...(opts.headers || {}) },
  });
  const b64 = str => { const bytes = new TextEncoder().encode(str); let bin = ''; bytes.forEach(b => bin += String.fromCharCode(b)); return btoa(bin); };
  const unb64 = s => new TextDecoder().decode(Uint8Array.from(atob(s.replace(/\n/g, '')), c => c.charCodeAt(0)));

  function needToken() {
    if (store.get('token', '')) return false;
    openSettings('To add, edit or delete recipes, connect the site to GitHub first.');
    return true;
  }

  async function putFile(path, contentB64, message, sha) {
    const res = await api(path, { method: 'PUT', body: JSON.stringify({ message, content: contentB64, sha, branch: 'main' }) });
    if (!res.ok) throw new Error(res.status === 401 || res.status === 403 ? 'GitHub refused the key. Check it in Settings.' : `GitHub said ${res.status}.`);
    return res.json();
  }

  // Read the latest edits.json from GitHub, change it, write it back (retrying once if someone saved in between)
  async function saveEdits(change, message) {
    for (let attempt = 0; attempt < 2; attempt++) {
      const cur = await api('data/edits.json?ref=main');
      let sha, data = normEdits(null);
      if (cur.ok) { const j = await cur.json(); sha = j.sha; data = normEdits(JSON.parse(unb64(j.content))); }
      else if (cur.status !== 404) throw new Error(cur.status === 401 ? 'GitHub refused the key. Check it in Settings.' : `GitHub said ${cur.status}.`);
      change(data);
      data.updated = new Date().toISOString();
      try {
        await putFile('data/edits.json', b64(JSON.stringify(data, null, 1)), message, sha);
        edits = data; store.set('edits', data);
        applyEdits();
        return;
      } catch (e) { if (attempt || !/409|422/.test(e.message)) throw e; }
    }
  }

  async function deleteRecipe(r) {
    if (needToken()) return;
    if (!confirm(`Delete “${r.title}” from the site? The file in Dropbox is not touched, and the recipe won’t come back when Dropbox is checked again.`)) return;
    try {
      await saveEdits(d => {
        d.added = d.added.filter(a => a.file !== r.file);
        delete d.changed[r.file];
        if (!r.file.startsWith('site:') && !d.deleted.includes(r.file)) d.deleted.push(r.file);
      }, `Delete recipe: ${r.title}`);
      toast('Deleted. Other devices will see it in about a minute.');
      location.hash = '#/';
      renderList();
    } catch (e) { alert('Couldn’t delete: ' + e.message); }
  }

  // ---------- editor ----------
  const toLines = items => (items || []).map(x => typeof x === 'object' ? `## ${x.h}` : x).join('\n');
  const fromLines = text => text.split('\n').map(l => l.trim()).filter(Boolean)
    .map(l => /^#+\s*/.test(l) ? { h: l.replace(/^#+\s*/, '') } : l.replace(/^(?:[-•*·]|\d+[.)])\s+/, ''));

  function openEditor(r) {
    if (needToken()) return;
    const isNew = !r;
    r = r || { title: '', categories: [] };
    const cats = [...new Set(recipes.flatMap(x => x.c))].sort();
    detailEl.innerHTML = `
      <form class="recipe editor" id="editor">
        <div class="toolbar">
          <a class="btn" href="${isNew ? '#/' : `#/r/${r.id}`}" id="cancelEdit">Cancel</a>
          <span class="spacer"></span>
          <button class="btn on" type="submit" id="saveEdit">Save</button>
        </div>
        <h1>${isNew ? 'New recipe' : 'Edit recipe'}</h1>
        <label>Title<input name="title" required value="${esc(r.title)}"></label>
        <label>Categories <span class="muted">(comma separated)</span><input name="categories" list="catlist" value="${esc((r.categories || []).join(', '))}"></label>
        <datalist id="catlist">${cats.map(c => `<option value="${esc(c)}">`).join('')}</datalist>
        <div class="row">
          <label>Serves<input name="servings" value="${esc(r.servings || '')}"></label>
          <label>Prep<input name="prep" value="${esc(r.prep || '')}"></label>
          <label>Cook<input name="cook" value="${esc(r.cook || '')}"></label>
          <label>Total<input name="total" value="${esc(r.total || '')}"></label>
        </div>
        <label>Description<textarea name="description" rows="3">${esc(r.description || '')}</textarea></label>
        <label>Ingredients <span class="muted">(one per line; start a line with ## for a heading)</span><textarea name="ingredients" rows="10">${esc(toLines(r.ingredients))}</textarea></label>
        <label>Directions <span class="muted">(one step per line; ## for a heading)</span><textarea name="directions" rows="10">${esc(toLines(r.directions) || (r.text && !r.ingredients?.length ? r.text : ''))}</textarea></label>
        <label>Notes<textarea name="notes" rows="3">${esc(r.notes || '')}</textarea></label>
        <label>Link to the original<input name="source" type="url" value="${esc(r.source || '')}"></label>
        <label>Photo<input name="photo" type="file" accept="image/*"></label>
        ${r.image ? `<img src="${esc(r.image)}" class="edit-thumb" alt="">` : ''}
      </form>`;
    app.dataset.view = 'detail';
    $('#cancelEdit').onclick = e => { e.preventDefault(); if (isNew) { location.hash = '#/'; route(); } else showRecipe(r.id); };
    $('#editor').onsubmit = async e => {
      e.preventDefault();
      const f = new FormData(e.target);
      const title = f.get('title').trim();
      const out = {
        title, categories: f.get('categories').split(',').map(x => x.trim()).filter(Boolean),
        servings: f.get('servings').trim(), prep: f.get('prep').trim(), cook: f.get('cook').trim(), total: f.get('total').trim(),
        description: f.get('description').trim(), ingredients: fromLines(f.get('ingredients')), directions: fromLines(f.get('directions')),
        notes: f.get('notes').trim(), source: f.get('source').trim(), image: r.image || null, thumb: r.thumb || null,
      };
      for (const k of Object.keys(out)) if (out[k] === '' || (Array.isArray(out[k]) && !out[k].length && k !== 'categories')) delete out[k];
      const btn = $('#saveEdit'); btn.disabled = true; btn.textContent = 'Saving…';
      try {
        const id = isNew ? 'u-' + slug(title) + '-' + Date.now().toString(36) : r.id;
        const file = isNew ? 'site:' + id : r.file;
        const photo = f.get('photo');
        if (photo && photo.size) {
          const [big, small] = await Promise.all([resize(photo, 1000), resize(photo, 160)]);
          const stamp = Date.now().toString(36);
          await putFile(`img/u/${id}-${stamp}.jpg`, big, `Photo for ${title}`);
          await putFile(`img/u/${id}-${stamp}-t.jpg`, small, `Thumbnail for ${title}`);
          out.image = `img/u/${id}-${stamp}.jpg`; out.thumb = `img/u/${id}-${stamp}-t.jpg`;
          // the new photo isn't on Pages yet; show it from this device meanwhile
          localPhotos[out.image] = URL.createObjectURL(photo); localPhotos[out.thumb] = localPhotos[out.image];
        }
        await saveEdits(d => {
          if (isNew) d.added.push({ ...out, id, file });
          else if (file.startsWith('site:')) d.added = d.added.map(a => a.file === file ? { ...out, id, file } : a);
          else d.changed[file] = out;
        }, `${isNew ? 'Add' : 'Edit'} recipe: ${title}`);
        toast('Saved. Other devices will see it in about a minute.');
        renderList();
        location.hash = `#/r/${id}`;
        if (!isNew) showRecipe(id);
      } catch (err) {
        alert('Couldn’t save: ' + err.message);
        btn.disabled = false; btn.textContent = 'Save';
      }
    };
  }

  const localPhotos = {};
  const slug = s => s.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 50) || 'recipe';
  function resize(file, max) {
    return new Promise((ok, bad) => {
      const im = new Image();
      im.onload = () => {
        const k = Math.min(1, max / Math.max(im.width, im.height));
        const c = document.createElement('canvas');
        c.width = Math.round(im.width * k); c.height = Math.round(im.height * k);
        c.getContext('2d').drawImage(im, 0, 0, c.width, c.height);
        ok(c.toDataURL('image/jpeg', 0.75).split(',')[1]);
      };
      im.onerror = () => bad(new Error('That photo couldn’t be read.'));
      im.src = URL.createObjectURL(file);
    });
  }

  function toast(msg) {
    const t = document.createElement('div');
    t.className = 'toast'; t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3500);
  }

  // ---------- settings ----------
  function openSettings(why) {
    const d = document.createElement('div');
    d.className = 'modal';
    const has = !!store.get('token', '');
    d.innerHTML = `<form class="sheet">
      <h2>Editing</h2>
      ${why ? `<p>${esc(why)}</p>` : ''}
      <p>Adding, editing and deleting saves to the site's GitHub repository, so this device needs a GitHub key.
      It stays on this device only. Make one at
      <a href="https://github.com/settings/personal-access-tokens/new" target="_blank" rel="noopener">GitHub → Fine-grained tokens</a>:
      under Repository access pick <b>Only select repositories</b> → <b>afooft-recipes-website</b>, and under
      Permissions set <b>Contents</b> to <b>Read and write</b>. Paste it below.</p>
      <label>GitHub key<input name="token" type="password" autocomplete="off" placeholder="${has ? 'Saved on this device' : 'github_pat_…'}"></label>
      <div class="row"><button class="btn on" type="submit">Save</button>
      ${has ? '<button class="btn" type="button" id="forget">Remove key</button>' : ''}
      <button class="btn" type="button" id="close">Close</button></div>
    </form>`;
    document.body.appendChild(d);
    const close = () => d.remove();
    d.querySelector('#close').onclick = close;
    d.querySelector('#forget')?.addEventListener('click', () => { store.set('token', ''); close(); });
    d.querySelector('form').onsubmit = async e => {
      e.preventDefault();
      const t = new FormData(e.target).get('token').trim();
      if (!t) return close();
      const res = await fetch(`https://api.github.com/repos/${REPO}`, { headers: { Authorization: `Bearer ${t}` } }).catch(() => null);
      const j = res?.ok ? await res.json() : null;
      if (!j?.permissions?.push) { alert('That key can’t write to afooft-recipes-website. Check the repository and the Contents permission.'); return; }
      store.set('token', t); close(); toast('This device can now add, edit and delete recipes.');
    };
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
  $('#addBtn').onclick = () => openEditor(null);
  $('#settingsBtn').onclick = () => { app.classList.remove('menu'); openSettings(); };
  $('#scrim').onclick = () => app.classList.remove('menu');

  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});

  load();
})();
