// Flujo — shared UI behaviour (vanilla ES2023, no dependencies)

// Auto-dismiss flash messages
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.flash').forEach((el) => {
    setTimeout(() => {
      el.style.transition = 'opacity .4s, transform .4s';
      el.style.opacity = '0';
      el.style.transform = 'translateX(30px)';
      setTimeout(() => el.remove(), 400);
    }, 4200);
  });

  // Mobile rail toggle
  const rail = document.querySelector('.rail');
  const scrim = document.querySelector('.rail-scrim');
  document.querySelector('.menu-btn')?.addEventListener('click', () => {
    rail?.classList.add('open');
    scrim?.classList.add('show');
  });
  scrim?.addEventListener('click', () => {
    rail?.classList.remove('open');
    scrim?.classList.remove('show');
  });

  // Keep the highlighted (active) menu item in view after navigating, so the
  // sidebar doesn't appear to "jump to the top" when you pick a lower item.
  const nav = document.querySelector('.nav');
  const active = nav?.querySelector('a.active');
  if (nav && active) {
    const target = active.offsetTop - nav.clientHeight / 2 + active.offsetHeight / 2;
    if (target > 0) nav.scrollTop = target;   // scrolls the nav only, never the page
  }
});

// ------------------------------------------------------------------
// Button loading state for any submit button marked with data-busy.
// On submit: shows a spinner + label, disables the button, and blocks
// repeat clicks — useful where the action has a delay (e.g. sending mail).
// ------------------------------------------------------------------
document.addEventListener('submit', (e) => {
  if (e.defaultPrevented) return;                 // a confirm() cancelled it
  const btn = e.submitter;
  if (!btn || !btn.hasAttribute('data-busy')) return;
  if (btn.dataset.sending) { e.preventDefault(); return; }  // already sending
  btn.dataset.sending = '1';
  const label = btn.getAttribute('data-busy') || 'Please wait…';
  btn.style.minWidth = btn.offsetWidth + 'px';    // keep width stable
  // defer so the button's name/value is still included in the POST
  setTimeout(() => {
    btn.disabled = true;
    btn.innerHTML = '<span class="btn-spin"></span>' + label;
  }, 0);
});

// Currency helper shared across pages
export function money(n, symbol = '$') {
  return symbol + Number(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}
window.fmtMoney = money;