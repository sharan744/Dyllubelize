// Flujo — Order builder (product cart + customer picker)
import { money } from './app.js';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const SYMBOL = window.CURRENCY_SYMBOL || '$';
const products = JSON.parse($('#products-data')?.textContent || '[]');
const productById = Object.fromEntries(products.map((p) => [p.id, p]));

// cart: { id, qty, discount, note, price, auto }
// price is the salesperson's unit price. auto=true means "follow the suggested
// price" (customer override > qty break > list); once the salesperson types a
// price it becomes manual (auto=false) and is kept.
let cart = [];
try {
  const seed = JSON.parse($('#items-data')?.textContent || '[]');
  cart = seed.map((i) => ({
    id: i.id, qty: Number(i.qty) || 1,
    discount: Number(i.discount) || 0, note: i.note || '',
    price: (i.price != null ? Number(i.price) : null), auto: (i.price == null),
  }));
} catch { cart = []; }

// customer-specific price overrides { productId: price }
let custPrices = {};

// guard against double-submit
let submitting = false;

// Suggested unit price: customer override > qty break > list price
function suggested(c) {
  const p = productById[c.id];
  if (!p) return 0;
  if (custPrices[c.id] != null) return custPrices[c.id];
  let price = p.price;
  let bestMin = -1;
  for (const [mn, pr] of (p.breaks || [])) {
    if (c.qty >= mn && mn > bestMin) { bestMin = mn; price = pr; }
  }
  return price;
}

// The price actually used — the salesperson's price, or the suggestion.
function unitPrice(c) {
  return c.auto ? suggested(c) : (Number(c.price) || 0);
}

// ---------------- Product picker ----------------
function renderPicker(filter = '') {
  const list = $('#pk-list');
  const f = filter.trim().toLowerCase();
  const shown = products.filter(
    (p) => !f || p.name.toLowerCase().includes(f) || p.sku.toLowerCase().includes(f),
  );
  if (!shown.length) {
    list.innerHTML = '<p class="muted small" style="padding:20px;text-align:center">No products match.</p>';
    return;
  }
  list.innerHTML = shown.map((p) => {
    let stock = '';
    if (p.track) {
      const cls = p.stock <= 0 ? 'color:#e03131' : (p.stock <= 10 ? 'color:#b8791b' : 'color:#97909f');
      stock = `<div class="sk" style="${cls}">${p.stock <= 0 ? 'Out of stock' : p.stock + ' in stock'}</div>`;
    }
    const thumb = p.image
      ? `<div class="pk-thumb"><img src="${p.image}" alt="" loading="lazy"></div>`
      : `<div class="pk-thumb pk-thumb-empty">${esc((p.name || '?').slice(0, 1))}</div>`;
    return `
    <div class="pk-card" data-add="${p.id}">
      <button type="button" class="pk-info" data-info="${p.id}" title="View details &amp; similar products">i</button>
      ${thumb}
      <div class="nm">${esc(p.name)}</div>
      <div class="sk">${esc(p.sku)} · ${esc(p.unit)}</div>
      <div class="pr">${money(p.price, SYMBOL)}</div>
      ${stock}
    </div>`;
  }).join('');
}

// ---------------- Cart ----------------
function addToCart(id) {
  const existing = cart.find((c) => c.id === id);
  if (existing) { existing.qty += 1; }
  else { cart.push({ id, qty: 1, discount: 0, note: '', price: null, auto: true }); }
  renderCart();
}

function renderCart() {
  const box = $('#cart-items');
  if (!cart.length) {
    box.innerHTML = '<div class="empty" style="padding:32px 10px"><p class="muted">No products added yet.<br>Click products on the left to build the order.</p></div>';
    updateTotals();
    return;
  }
  box.innerHTML = cart.map((c) => {
    const p = productById[c.id] || { name: '?', sku: '', unit: '', price: 0 };
    const up = unitPrice(c);
    const special = (custPrices[c.id] != null) || (up !== p.price);
    const priceHint = c.auto
      ? `list ${money(suggested(c), SYMBOL)}`
      : `list ${money(p.price, SYMBOL)}`;
    const cthumb = p.image
      ? `<div class="ci-thumb"><img src="${p.image}" alt="" loading="lazy"></div>`
      : `<div class="ci-thumb ci-thumb-empty">${esc((p.name || '?').slice(0, 1))}</div>`;
    return `
    <div class="ci" data-row="${c.id}">
      ${cthumb}
      <div>
        <div class="nm">${esc(p.name)}</div>
        <div class="sk">${esc(p.sku)} · /${esc(p.unit)}${special ? ' <b style="color:#0f8b86" title="Custom price">•</b>' : ''}</div>
      </div>
      <button class="rm" data-rm="${c.id}" title="Remove" type="button">✕</button>
      <div class="ctrls">
        <span class="qty-step">
          <button type="button" data-dec="${c.id}">−</button>
          <input type="number" min="0" step="1" value="${c.qty}" data-qty="${c.id}">
          <button type="button" data-inc="${c.id}">+</button>
        </span>
        <label class="price-cell" title="Unit price for this customer — change it to give your own price">
          <span class="pfx">${esc(SYMBOL)}</span>
          <input type="number" min="0" step="0.01" value="${fmt(up)}" data-price="${c.id}"
                 class="price-in${c.auto ? '' : ' manual'}" placeholder="price">
        </label>
        <input type="number" min="0" max="100" step="1" value="${c.discount}" data-disc="${c.id}"
               title="Line discount %" style="width:52px" placeholder="%">
        <span class="lt">${money(lineTotal(c), SYMBOL)}</span>
      </div>
    </div>`;
  }).join('');
  updateTotals();
}

function lineTotal(c) {
  const gross = unitPrice(c) * c.qty;
  return gross - (gross * (c.discount || 0)) / 100;
}

function updateTotals() {
  const subtotal = cart.reduce((s, c) => s + lineTotal(c), 0);
  const orderDisc = Number($('#discount_percent')?.value || 0);
  const discAmt = (subtotal * orderDisc) / 100;
  const grand = subtotal - discAmt;
  const items = cart.reduce((s, c) => s + Number(c.qty), 0);
  $('#t-subtotal').textContent = money(subtotal, SYMBOL);
  $('#t-disc').textContent = '−' + money(discAmt, SYMBOL);
  $('#t-grand').textContent = money(grand, SYMBOL);
  $('#t-items').textContent = items;
  $('#t-lines').textContent = cart.length;
}

// ---------------- Customer picker ----------------
let selectedCustomer = null;
let searchTimer = null;

async function searchCustomers(q) {
  const res = await fetch(`/orders/api/customers/?q=${encodeURIComponent(q)}`);
  const data = await res.json();
  const box = $('#cust-results');
  if (!data.results.length) {
    box.innerHTML = '<p class="muted small" style="padding:10px">No customers found. Use “+ New customer”.</p>';
    box.style.display = 'block';
    return;
  }
  box.innerHTML = data.results.map((c) => `
    <div class="sel-order" data-cust='${JSON.stringify(c).replace(/'/g, "&#39;")}'>
      <div style="flex:1">
        <b>${esc(c.company || c.name)}</b>
        <div class="small muted">${esc(c.name)} · ${esc(c.mobile)} · ${c.orders} order(s)</div>
      </div>
      <span class="btn btn-soft btn-sm">Select</span>
    </div>`).join('');
  box.style.display = 'block';
}

async function fetchPricing(customerId) {
  try {
    const res = await fetch(`/orders/api/pricing/?customer=${encodeURIComponent(customerId)}`);
    const d = await res.json();
    custPrices = d.prices || {};
  } catch { custPrices = {}; }
  renderCart();
}

function selectCustomer(c) {
  selectedCustomer = c;
  $('#customer_id').value = c.id;
  fetchPricing(c.id);
  $('#cust-selected').innerHTML = `
    <div class="flex" style="justify-content:space-between">
      <div>
        <b>${esc(c.company || c.name)}</b>
        <div class="small muted">${esc(c.name)} · ${esc(c.mobile)}</div>
      </div>
      <button type="button" class="btn btn-soft btn-sm" id="cust-change">Change</button>
    </div>`;
  $('#cust-selected').style.display = 'block';
  $('#cust-picker').style.display = 'none';
  $('#cust-results').style.display = 'none';
  $('#cust-change')?.addEventListener('click', () => {
    $('#cust-selected').style.display = 'none';
    $('#cust-picker').style.display = 'block';
    $('#cust-search').value = '';
    $('#cust-search').focus();
  });
}

// ---------------- Submit ----------------
function submitOrder(action) {
  if (submitting) return;                                   // already sending
  if (!$('#customer_id').value) { alert('Please select a customer first.'); return; }
  if (!cart.length) { alert('Add at least one product to the order.'); return; }

  const payload = cart.map((c) => ({
    id: c.id, qty: c.qty, price: unitPrice(c), discount: c.discount, note: c.note,
  }));
  $('#items_json').value = JSON.stringify(payload);
  $('#action-field').value = action;

  // lock the UI so a second click can't create a duplicate order
  submitting = true;
  const draftBtn = $('#btn-draft');
  const submitBtn = $('#btn-submit');
  [draftBtn, submitBtn].forEach((b) => { if (b) b.disabled = true; });
  const active = action === 'submit' ? submitBtn : draftBtn;
  if (active) active.textContent = 'Saving…';

  $('#order-form').submit();
}

// ---------------- Wire up ----------------
function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, (m) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[m]));
}

// plain 2-decimal number for input value="" (no currency symbol)
function fmt(n) {
  return (Math.round((Number(n) || 0) * 100) / 100).toFixed(2);
}

// ---------------- Product info modal (description + similar) ----------------
function closeInfo() {
  const m = document.getElementById('pk-modal');
  if (m) m.remove();
}

async function openInfo(id) {
  closeInfo();
  const overlay = document.createElement('div');
  overlay.id = 'pk-modal';
  overlay.className = 'pk-modal';
  overlay.innerHTML = '<div class="pk-modal-box"><div class="pk-modal-body">Loading…</div></div>';
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeInfo(); });
  document.body.appendChild(overlay);
  document.addEventListener('keydown', function esc(e) {
    if (e.key === 'Escape') { closeInfo(); document.removeEventListener('keydown', esc); }
  });

  let d;
  try {
    const res = await fetch(`/orders/api/product/${id}/`);
    d = await res.json();
  } catch {
    overlay.querySelector('.pk-modal-body').textContent = 'Could not load product details.';
    return;
  }

  const thumb = d.image
    ? `<div class="pk-modal-img"><img src="${d.image}" alt=""></div>`
    : `<div class="pk-modal-img pk-thumb-empty" style="border-radius:12px">${esc((d.name || '?').slice(0, 1))}</div>`;

  const specs = (d.specs || []).length
    ? `<table class="pk-modal-specs">${d.specs.map((s) =>
        `<tr><td>${esc(s.label)}</td><td>${esc(s.value)}</td></tr>`).join('')}</table>`
    : '';

  const desc = d.description
    ? `<p class="pk-modal-desc">${esc(d.description).replace(/\n/g, '<br>')}</p>`
    : '<p class="pk-modal-desc muted">No description added yet.</p>';

  const similar = (d.similar || []).length
    ? `<div class="pk-modal-sim">
         <div class="pk-modal-sub">Similar products</div>
         <div class="pk-sim-grid">${d.similar.map((s) => `
           <div class="pk-sim" data-simadd="${s.id}">
             <div class="pk-sim-thumb">${s.image
               ? `<img src="${s.image}" alt="">`
               : `<span>${esc((s.name || '?').slice(0, 1))}</span>`}</div>
             <div class="pk-sim-nm">${esc(s.name)}</div>
             <div class="pk-sim-pr">${money(s.price, SYMBOL)}</div>
             <button type="button" class="btn btn-soft btn-sm" data-simadd="${s.id}">+ Add</button>
           </div>`).join('')}</div>
       </div>`
    : '';

  overlay.querySelector('.pk-modal-box').innerHTML = `
    <button type="button" class="pk-modal-x" title="Close">✕</button>
    <div class="pk-modal-head">
      ${thumb}
      <div>
        ${d.brand ? `<span class="chip">${esc(d.brand)}</span>` : ''}
        ${d.category ? `<span class="chip">${esc(d.category)}</span>` : ''}
        <h3 style="margin:8px 0 2px">${esc(d.name)}</h3>
        <div class="mono muted small">${esc(d.sku)} · ${esc(d.unit)}</div>
        <div class="pk-modal-price">${money(d.price, SYMBOL)}</div>
        <button type="button" class="btn btn-primary btn-sm" data-addmain="${d.id}" style="margin-top:8px">+ Add to order</button>
      </div>
    </div>
    <div class="pk-modal-body">
      ${desc}
      ${specs}
      ${similar}
    </div>`;

  overlay.querySelector('.pk-modal-x').addEventListener('click', closeInfo);
  overlay.querySelector('[data-addmain]')?.addEventListener('click', () => {
    addToCart(Number(d.id)); closeInfo();
  });
  overlay.querySelectorAll('[data-simadd]').forEach((el) => {
    el.addEventListener('click', (e) => {
      e.stopPropagation();
      addToCart(Number(el.dataset.simadd));
      closeInfo();
    });
  });
}

document.addEventListener('DOMContentLoaded', () => {
  renderPicker();
  renderCart();

  $('#pk-search')?.addEventListener('input', (e) => renderPicker(e.target.value));

  let clickTimer = null;
  $('#pk-list')?.addEventListener('click', (e) => {
    // info button → open details modal (never adds to cart)
    const info = e.target.closest('[data-info]');
    if (info) { e.stopPropagation(); clearTimeout(clickTimer); openInfo(Number(info.dataset.info)); return; }
    const card = e.target.closest('[data-add]');
    if (!card) return;
    const id = Number(card.dataset.add);
    // wait briefly so a double-click (view) doesn't also add the item
    clearTimeout(clickTimer);
    clickTimer = setTimeout(() => addToCart(id), 200);
  });
  $('#pk-list')?.addEventListener('dblclick', (e) => {
    const card = e.target.closest('[data-add]');
    if (!card) return;
    clearTimeout(clickTimer);              // cancel the pending single-click add
    openInfo(Number(card.dataset.add));
  });

  $('#cart-items')?.addEventListener('click', (e) => {
    const t = e.target;
    if (t.dataset.rm) { cart = cart.filter((c) => c.id !== Number(t.dataset.rm)); renderCart(); }
    if (t.dataset.inc) { const c = cart.find((x) => x.id === Number(t.dataset.inc)); c.qty += 1; renderCart(); }
    if (t.dataset.dec) { const c = cart.find((x) => x.id === Number(t.dataset.dec)); c.qty = Math.max(0, c.qty - 1); if (c.qty === 0) cart = cart.filter((x) => x !== c); renderCart(); }
  });
  $('#cart-items')?.addEventListener('input', (e) => {
    const t = e.target;
    if (t.dataset.qty) { const c = cart.find((x) => x.id === Number(t.dataset.qty)); c.qty = Math.max(0, Number(t.value) || 0); updateRow(c); }
    if (t.dataset.disc) { const c = cart.find((x) => x.id === Number(t.dataset.disc)); c.discount = Math.min(100, Math.max(0, Number(t.value) || 0)); updateRow(c); }
    if (t.dataset.price) {
      const c = cart.find((x) => x.id === Number(t.dataset.price));
      c.price = Math.max(0, Number(t.value) || 0);   // salesperson's own price
      c.auto = false;                                 // stop following the suggestion
      t.classList.add('manual');
      updateRow(c, { skipPrice: true });
    }
  });

  function updateRow(c, opts = {}) {
    const rowEl = $(`[data-row="${c.id}"]`);
    if (rowEl) {
      const p = productById[c.id];
      const up = unitPrice(c);
      const special = (custPrices[c.id] != null) || (up !== p.price);
      const sk = rowEl.querySelector('.sk');
      if (sk) sk.innerHTML = `${esc(p.sku)} · /${esc(p.unit)}${special ? ' <b style="color:#0f8b86" title="Custom price">•</b>' : ''}`;
      // For auto lines a qty change can cross a price break, so refresh the field
      // (unless the user is the one typing in it right now).
      if (!opts.skipPrice && c.auto) {
        const pi = rowEl.querySelector('[data-price]');
        if (pi && document.activeElement !== pi) pi.value = fmt(up);
      }
      const lt = rowEl.querySelector('.lt');
      if (lt) lt.textContent = money(lineTotal(c), SYMBOL);
    }
    updateTotals();
  }

  $('#discount_percent')?.addEventListener('input', updateTotals);

  // customer search
  $('#cust-search')?.addEventListener('input', (e) => {
    clearTimeout(searchTimer);
    const q = e.target.value;
    searchTimer = setTimeout(() => searchCustomers(q), 220);
  });
  $('#cust-results')?.addEventListener('click', (e) => {
    const row = e.target.closest('[data-cust]');
    if (row) selectCustomer(JSON.parse(row.dataset.cust));
  });

  $('#btn-draft')?.addEventListener('click', () => submitOrder('draft'));
  $('#btn-submit')?.addEventListener('click', () => submitOrder('submit'));

  // preset customer (after creating a new one)
  const preset = $('#preset-customer')?.value;
  if (preset) {
    fetch(`/orders/api/customers/?id=${encodeURIComponent(preset)}`)
      .then((r) => r.json())
      .then((d) => { if (d.results[0]) selectCustomer(d.results[0]); });
  }
});