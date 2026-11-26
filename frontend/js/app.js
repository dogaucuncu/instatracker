/**
 * app.js — InstaTracker
 *
 * One rule governs every render in this file: text that came from Instagram is
 * written as a DOM text node, never as markup. A display name, a username or
 * an error message is arbitrary text chosen by someone else; building rows with
 * innerHTML let any of them inject script into this page, which runs on the
 * same origin as the API that can unfollow people. The el()/icon() helpers
 * below make the safe path the shortest one, so no row has to remember to
 * escape anything.
 */

/* ── State ──────────────────────────────────────────────────────────────── */
const state = {
  account: null,
  activeTab: 'unfollowers',
  scanPoll: null,
  pendingUnfollow: null,
  lastFocused: null,
  scannedAtLeastOnce: false,
};

const $ = (id) => document.getElementById(id);
const SVG_NS = 'http://www.w3.org/2000/svg';

/* ── DOM helpers ────────────────────────────────────────────────────────── */

/**
 * Build an element. Children that are strings become text nodes, so any value
 * passed in is inert by construction.
 */
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else node.setAttribute(key, value);
  }
  for (const child of [].concat(children)) {
    if (child === null || child === undefined || child === false) continue;
    node.append(typeof child === 'string' ? document.createTextNode(child) : child);
  }
  return node;
}

/** A decorative icon from the sprite in index.html. */
function icon(name) {
  const svg = document.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('class', 'icon');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  const use = document.createElementNS(SVG_NS, 'use');
  use.setAttribute('href', '#' + name);
  svg.append(use);
  return svg;
}

function clear(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function setBusy(button, busy, label) {
  button.disabled = busy;
  clear(button);
  if (busy) {
    button.append(el('span', { class: 'spinner', 'aria-hidden': 'true' }));
    button.append(document.createTextNode(' ' + label));
  } else {
    button.append(document.createTextNode(label));
  }
}

/* ── Formatting ─────────────────────────────────────────────────────────── */
const nf = new Intl.NumberFormat('tr-TR');

function num(value) {
  return value === null || value === undefined ? '—' : nf.format(value);
}

/**
 * The database stores UTC timestamps with no timezone suffix. Appending Z tells
 * the browser to read them as UTC so they display in local time.
 */
function when(iso, withTime = true) {
  if (!iso) return '—';
  let s = String(iso).replace(' ', 'T');
  if (!s.endsWith('Z') && !/[+-]\d\d:?\d\d$/.test(s)) s += 'Z';
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return '—';
  const opts = { day: '2-digit', month: 'short', year: 'numeric' };
  if (withTime) Object.assign(opts, { hour: '2-digit', minute: '2-digit' });
  return d.toLocaleString('tr-TR', opts);
}

function initial(name) {
  const s = (name || '').trim();
  return s ? s[0].toUpperCase() : '?';
}

/* ── Toasts ─────────────────────────────────────────────────────────────── */
const TOAST_ICON = { done: 'i-settled', problem: 'i-open', info: 'i-info' };

function toast(message, kind = 'info', ms = 5000) {
  const node = el('p', { class: 'toast toast--' + kind }, [
    icon(TOAST_ICON[kind] || 'i-info'),
    el('span', { text: message }),
  ]);
  $('toasts').append(node);
  window.setTimeout(() => node.remove(), ms);
}

/* ── Screens ────────────────────────────────────────────────────────────── */
function showGate() {
  $('gate').classList.remove('hidden');
  $('app').classList.add('hidden');
}

function showApp() {
  $('gate').classList.add('hidden');
  $('app').classList.remove('hidden');
}

function showStep(id) {
  for (const step of ['step-password', 'step-code', 'step-device']) {
    $(step).classList.toggle('hidden', step !== id);
  }
}

function showLoginError(message) {
  const box = $('login-error');
  box.textContent = message;
  box.classList.remove('hidden');
}

function clearLoginError() {
  $('login-error').classList.add('hidden');
  $('login-error').textContent = '';
}

/* ── Sign in ────────────────────────────────────────────────────────────── */
$('btn-reveal').addEventListener('click', () => {
  const input = $('inp-password');
  const button = $('btn-reveal');
  const reveal = input.type === 'password';
  input.type = reveal ? 'text' : 'password';
  button.setAttribute('aria-pressed', String(reveal));
  button.setAttribute('aria-label', reveal ? 'Şifreyi gizle' : 'Şifreyi göster');
  clear(button);
  button.append(icon(reveal ? 'i-eye-off' : 'i-eye'));
});

function adoptAccount(account) {
  state.account = account;
  if (!account) return;
  $('whoami-handle').textContent = '@' + (account.username || '');
  $('whoami-name').textContent = account.full_name || '';
  const avatar = $('whoami-avatar');
  if (account.profile_pic_url) {
    avatar.src = account.profile_pic_url;
    avatar.hidden = false;
    avatar.addEventListener('error', () => { avatar.hidden = true; }, { once: true });
  } else {
    avatar.hidden = true;
  }
}

function enterApp(account) {
  adoptAccount(account);
  showApp();
  selectTab(tabFromUrl());
  loadStats();
  loadTab(state.activeTab);
}

$('form-login').addEventListener('submit', async (event) => {
  event.preventDefault();
  clearLoginError();
  const username = $('inp-username').value.trim();
  const password = $('inp-password').value;
  if (!username || !password) {
    showLoginError('Kullanıcı adı ve şifre gerekli.');
    ($('inp-username').value ? $('inp-password') : $('inp-username')).focus();
    return;
  }
  setBusy($('btn-login'), true, 'Giriş yapılıyor');
  try {
    const res = await api.login(username, password);
    if (res.status === 'ok') enterApp(res.account);
    else if (res.status === '2fa_required') { showStep('step-code'); $('inp-code').focus(); }
    else if (res.status === 'challenge_required') { showStep('step-device'); $('btn-approved-device').focus(); }
  } catch (err) {
    showLoginError(err.message || 'Giriş yapılamadı.');
  } finally {
    setBusy($('btn-login'), false, 'Giriş yap');
  }
});

$('form-code').addEventListener('submit', async (event) => {
  event.preventDefault();
  clearLoginError();
  const code = $('inp-code').value.trim();
  if (!code) {
    showLoginError('Doğrulama kodu gerekli.');
    $('inp-code').focus();
    return;
  }
  setBusy($('btn-code'), true, 'Doğrulanıyor');
  try {
    const res = await api.verify2fa(code);
    if (res.status === 'ok') enterApp(res.account);
  } catch (err) {
    showLoginError(err.message || 'Kod doğrulanamadı.');
  } finally {
    setBusy($('btn-code'), false, 'Kodu doğrula');
  }
});

/** Both "I approved it" buttons ask the backend to retry the same challenge. */
async function retryChallenge(button, label) {
  clearLoginError();
  setBusy(button, true, 'Denetleniyor');
  try {
    const res = await api.challengeRetry();
    if (res.status === 'ok') {
      enterApp(res.account);
    } else if (res.status === 'challenge_still_pending') {
      showLoginError((res.message || 'Onay henüz görünmüyor.') + ' Telefonunu kontrol edip tekrar dene.');
    } else if (res.status === '2fa_required') {
      showStep('step-code');
      showLoginError('Bu hesap bir kod istiyor. Gelen 6 haneli kodu gir.');
      $('inp-code').focus();
    }
  } catch (err) {
    showLoginError(err.message || 'Bağlantı kurulamadı.');
  } finally {
    setBusy(button, false, label);
  }
}

$('btn-approved-device').addEventListener('click', (e) =>
  retryChallenge(e.currentTarget, 'Onayladım, devam et'));
$('btn-approved-code').addEventListener('click', (e) =>
  retryChallenge(e.currentTarget, 'Bildirimi onayladım, devam et'));

for (const id of ['btn-back-code', 'btn-back-device']) {
  $(id).addEventListener('click', () => {
    showStep('step-password');
    clearLoginError();
    $('inp-password').focus();
  });
}

$('btn-logout').addEventListener('click', async () => {
  await api.logout().catch(() => {});
  state.account = null;
  showGate();
  showStep('step-password');
  $('inp-username').focus();
  toast('Çıkış yapıldı.', 'info');
});

/* ── Headline and facts ─────────────────────────────────────────────────── */
function renderVerdict(stats) {
  const left = stats.unfollowed || 0;
  const scanned = Boolean(stats.last_scan);
  state.scannedAtLeastOnce = scanned;

  let count = num(left);
  let text;
  if (!scanned) {
    count = '—';
    text = 'Henüz tarama yapılmadı. Taramayı başlat, kayıt buradan dolsun.';
  } else if (left === 0) {
    text = 'kişi takibini bıraktı. Kayıtta ayrılan yok.';
  } else {
    text = left === 1 ? 'kişi takibini bıraktı.' : 'kişi takibini bıraktı.';
  }
  $('hero-count').textContent = count;
  $('hero-text').textContent = text;
  $('scanned-at').textContent = scanned ? when(stats.last_scan) : 'hiç';
}

async function loadStats() {
  try {
    const s = await api.dashboardStats();
    renderVerdict(s);
    $('fact-followers').textContent = num(s.follower_count);
    $('fact-following').textContent = num(s.following_count);
    $('fact-blocked').textContent = num(s.blocked);
    $('fact-deactivated').textContent = num(s.deactivated);
    $('fact-still-following').textContent = num(s.still_following_count);
    $('count-unfollowers').textContent = num(s.unfollowed);
    $('count-blockers').textContent = num(s.blocked);
    $('count-deactivated').textContent = num(s.deactivated);
    $('count-new-followers').textContent = num(s.new_followers);
  } catch (err) {
    toast('Özet yüklenemedi: ' + (err.message || 'bilinmeyen hata'), 'problem');
  }
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
const TABS = ['unfollowers', 'blockers', 'deactivated', 'new-followers', 'scan-history'];

/** Which list is open belongs in the URL, so a reload or a bookmark keeps it. */
function rememberTab(name) {
  const url = new URL(window.location.href);
  url.searchParams.set('liste', name);
  window.history.replaceState(null, '', url);
}

function tabFromUrl() {
  const asked = new URL(window.location.href).searchParams.get('liste');
  return TABS.includes(asked) ? asked : TABS[0];
}

function selectTab(name, { focus = false } = {}) {
  state.activeTab = name;
  rememberTab(name);
  for (const tab of TABS) {
    const button = $('tab-' + tab);
    const panel = $('panel-' + tab);
    const on = tab === name;
    button.setAttribute('aria-selected', String(on));
    button.tabIndex = on ? 0 : -1;
    panel.classList.toggle('hidden', !on);
  }
  if (focus) $('tab-' + name).focus();
}

for (const tab of TABS) {
  const button = $('tab-' + tab);
  button.addEventListener('click', () => {
    selectTab(tab);
    loadTab(tab);
  });
  // Arrow keys move between tabs, which is what a tablist is expected to do.
  button.addEventListener('keydown', (event) => {
    const i = TABS.indexOf(tab);
    let next = null;
    if (event.key === 'ArrowRight') next = TABS[(i + 1) % TABS.length];
    else if (event.key === 'ArrowLeft') next = TABS[(i - 1 + TABS.length) % TABS.length];
    else if (event.key === 'Home') next = TABS[0];
    else if (event.key === 'End') next = TABS[TABS.length - 1];
    if (!next) return;
    event.preventDefault();
    selectTab(next, { focus: true });
    loadTab(next);
  });
}

const LOADERS = {
  unfollowers: api.getUnfollowers.bind(api),
  blockers: api.getBlockers.bind(api),
  deactivated: api.getDeactivated.bind(api),
  'new-followers': api.getNewFollowers.bind(api),
  'scan-history': api.scanHistory.bind(api),
};

async function loadTab(name) {
  const panel = $('panel-' + name);
  if (!panel) return;
  clear(panel);
  panel.append(el('p', { class: 'note', text: 'Yükleniyor…' }));
  let rows;
  try {
    rows = await LOADERS[name]();
  } catch (err) {
    clear(panel);
    panel.append(emptyState('Kayıtlar okunamadı', err.message || 'Sunucuya ulaşılamadı.'));
    return;
  }
  clear(panel);
  panel.append(name === 'scan-history' ? renderHistory(rows) : renderPeople(rows, name));
}

/* ── Rendering ──────────────────────────────────────────────────────────── */
function emptyState(head, body) {
  return el('div', { class: 'empty' }, [
    el('p', { class: 'empty-head', text: head }),
    el('p', { class: 'empty-body', text: body }),
  ]);
}

/** Avatar with a letter fallback, built without any inline event handler. */
function avatarFor(person) {
  if (person.profile_pic_url) {
    const img = el('img', {
      class: 'person-avatar',
      alt: '',
      width: '34',
      height: '34',
      loading: 'lazy',
    });
    // The handler goes on before src, or a request that fails immediately (a
    // cached failure, an offline run) fires error before anyone is listening
    // and the row is left with an empty circle.
    img.addEventListener('error', () => img.replaceWith(letterAvatar(person)), { once: true });
    img.src = person.profile_pic_url;
    return img;
  }
  return letterAvatar(person);
}

function letterAvatar(person) {
  return el('span', {
    class: 'person-avatar person-initial',
    'aria-hidden': 'true',
    text: initial(person.username),
  });
}

function personCell(person) {
  const handle = el('a', {
    class: 'person-handle',
    href: 'https://instagram.com/' + encodeURIComponent(person.username || ''),
    target: '_blank',
    rel: 'noopener noreferrer',
    // A handle is an identifier, not prose: page translation must leave it be.
    translate: 'no',
  }, ['@' + (person.username || ''), ' ', icon('i-link')]);

  return el('td', {}, [
    el('span', { class: 'person' }, [
      avatarFor(person),
      el('span', {}, [
        handle,
        el('span', { class: 'person-name', text: person.full_name || '' }),
      ]),
    ]),
  ]);
}

const PEOPLE_COPY = {
  unfollowers: {
    caption: 'Takibini bırakanlar',
    emptyHead: 'Ayrılan yok',
    emptyBody: 'Son taramaya göre kimse takibini bırakmamış.',
  },
  blockers: {
    caption: 'Engelleyenler',
    emptyHead: 'Engelleyen yok',
    emptyBody: 'Takipçi listesinden çıkıp profiline erişimini kesen kimse bulunmadı.',
  },
  deactivated: {
    caption: 'Hesabını kapatanlar',
    emptyHead: 'Kapatan yok',
    emptyBody: 'Takipçilerinin hiçbiri hesabını kapatmamış ya da askıya alınmamış.',
  },
  'new-followers': {
    caption: 'Yeni takipçiler',
    emptyHead: 'Yeni takipçi yok',
    emptyBody: 'Son taramadan beri yeni takipçi eklenmemiş.',
  },
};

function renderPeople(rows, kind) {
  const copy = PEOPLE_COPY[kind];
  if (!Array.isArray(rows) || rows.length === 0) {
    const body = state.scannedAtLeastOnce
      ? copy.emptyBody
      : 'Henüz tarama yapılmadı. Sayfanın üstündeki tara düğmesiyle başla.';
    return emptyState(copy.emptyHead, body);
  }

  // Only these three carry a decision: you may still be following them.
  const actionable = ['unfollowers', 'blockers', 'deactivated'].includes(kind);

  const head = el('tr', {}, [
    el('th', { scope: 'col', text: 'Kişi' }),
    el('th', { scope: 'col', text: 'Kayıt tarihi' }),
    actionable && el('th', { scope: 'col', text: 'Senin durumun' }),
    actionable && el('th', { scope: 'col', class: 'col-action', text: 'İşlem' }),
  ].filter(Boolean));

  const body = el('tbody');
  for (const person of rows) {
    const cells = [personCell(person), el('td', { class: 'col-date', text: when(person.detected_at, false) })];

    if (actionable) {
      if (person.still_following) {
        cells.push(el('td', {}, [
          el('span', { class: 'status status--open' }, [icon('i-open'), el('span', { text: 'Hâlâ takip ediyorsun' })]),
        ]));
        const button = el('button', {
          type: 'button',
          class: 'btn btn-signal btn-sm',
          text: 'Takibi bırak',
        });
        button.addEventListener('click', () => askUnfollow(person.user_pk, person.username));
        cells.push(el('td', { class: 'col-action' }, [button]));
      } else {
        cells.push(el('td', {}, [
          el('span', { class: 'status status--settled' }, [icon('i-settled'), el('span', { text: 'Takip etmiyorsun' })]),
        ]));
        cells.push(el('td', { class: 'col-action' }));
      }
    }
    body.append(el('tr', {}, cells));
  }

  return el('div', { class: 'register-scroll' }, [
    el('table', { class: 'register' }, [
      el('caption', { class: 'sr-only', text: copy.caption }),
      el('thead', {}, [head]),
      body,
    ]),
  ]);
}

const SCAN_STATUS = {
  completed: 'Tamamlandı',
  running: 'Sürüyor',
  failed: 'Hata',
  first_scan: 'İlk tarama',
};

function renderHistory(rows) {
  if (!Array.isArray(rows) || rows.length === 0) {
    return emptyState('Tarama geçmişi boş', 'İlk taramadan sonra her tarama buraya tarihiyle işlenir.');
  }

  const body = el('tbody');
  rows.forEach((scan, index) => {
    const baseline = scan.status === 'first_scan';
    body.append(el('tr', {}, [
      el('td', { class: 'col-num', text: String(rows.length - index) }),
      el('td', { class: 'col-date', text: when(scan.started_at) }),
      el('td', { class: 'col-date', text: scan.completed_at ? when(scan.completed_at) : '—' }),
      el('td', { text: SCAN_STATUS[scan.status] || scan.status || '—' }),
      el('td', { class: 'col-num outcome-gain', text: baseline ? '—' : '+' + num(scan.new_followers) }),
      el('td', { class: 'col-num outcome-loss', text: baseline ? '—' : '-' + num(scan.lost_followers) }),
      el('td', { class: 'note', text: scan.error_message || '' }),
    ]));
  });

  return el('div', { class: 'register-scroll' }, [
    el('table', { class: 'register' }, [
      el('caption', { class: 'sr-only', text: 'Tarama geçmişi' }),
      el('thead', {}, [
        el('tr', {}, [
          el('th', { scope: 'col', class: 'col-num', text: '#' }),
          el('th', { scope: 'col', text: 'Başlangıç' }),
          el('th', { scope: 'col', text: 'Bitiş' }),
          el('th', { scope: 'col', text: 'Durum' }),
          el('th', { scope: 'col', class: 'col-num', text: 'Yeni' }),
          el('th', { scope: 'col', class: 'col-num', text: 'Kayıp' }),
          el('th', { scope: 'col', text: 'Not' }),
        ]),
      ]),
      body,
    ]),
  ]);
}

/* ── Scan ───────────────────────────────────────────────────────────────── */
function scanUI(running) {
  $('btn-scan').disabled = running;
  $('btn-scan-label').textContent = running ? 'Taranıyor' : 'Şimdi tara';
  $('scan-state').classList.toggle('hidden', !running);
}

$('btn-scan').addEventListener('click', async () => {
  scanUI(true);
  $('scan-msg').textContent = 'Tarama başlatılıyor.';
  try {
    await api.startScan();
    pollScan();
  } catch (err) {
    toast(err.message || 'Tarama başlatılamadı.', 'problem');
    scanUI(false);
  }
});

function pollScan() {
  if (state.scanPoll) window.clearInterval(state.scanPoll);
  state.scanPoll = window.setInterval(async () => {
    let res;
    try {
      res = await api.scanStatus();
    } catch (err) {
      stopPolling();
      toast('Tarama durumu alınamadı.', 'problem');
      return;
    }
    if (res.status === 'running') {
      $('scan-msg').textContent = 'Takipçi ve takip listeleri çekiliyor.';
      return;
    }
    stopPolling();
    if (res.status === 'completed') {
      const result = res.result || {};
      if (result.status === 'first_scan') {
        toast('İlk tarama tamamlandı. Bu liste karşılaştırma zemini oldu; değişiklikler sonraki taramada görünür.', 'done', 8000);
      } else {
        toast(result.message || 'Tarama tamamlandı.', 'done');
      }
      await loadStats();
      await loadTab(state.activeTab);
    } else if (res.status === 'error') {
      toast('Tarama hatası: ' + (res.message || 'bilinmeyen'), 'problem', 8000);
    }
  }, 3000);
}

function stopPolling() {
  if (state.scanPoll) window.clearInterval(state.scanPoll);
  state.scanPoll = null;
  scanUI(false);
}

/* ── Confirmation dialog ────────────────────────────────────────────────── */
const FOCUSABLE = 'button:not(:disabled), [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

function askUnfollow(pk, username) {
  state.pendingUnfollow = { pk, username };
  $('dialog-body').textContent =
    '@' + username + ' hesabını takip etmeyi bırakacaksın. Bu işlem Instagram üzerinde gerçekleşir ve geri alınması için yeniden takip etmen gerekir.';
  openDialog();
}

function openDialog() {
  state.lastFocused = document.activeElement;
  $('scrim').classList.remove('hidden');
  $('btn-dialog-confirm').focus();
  document.addEventListener('keydown', dialogKeys, true);
}

function closeDialog() {
  $('scrim').classList.add('hidden');
  state.pendingUnfollow = null;
  document.removeEventListener('keydown', dialogKeys, true);
  // Focus goes back where it came from, so the keyboard does not jump to the top.
  if (state.lastFocused && state.lastFocused.isConnected) state.lastFocused.focus();
}

/** Escape closes; Tab cycles inside the dialog instead of escaping behind it. */
function dialogKeys(event) {
  if (event.key === 'Escape') {
    event.preventDefault();
    closeDialog();
    return;
  }
  if (event.key !== 'Tab') return;
  const items = Array.from($('scrim').querySelectorAll(FOCUSABLE));
  if (items.length === 0) return;
  const first = items[0];
  const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

$('btn-dialog-cancel').addEventListener('click', closeDialog);
$('scrim').addEventListener('click', (event) => {
  if (event.target === $('scrim')) closeDialog();
});

$('btn-dialog-confirm').addEventListener('click', async () => {
  if (!state.pendingUnfollow) return;
  const { pk, username } = state.pendingUnfollow;
  const button = $('btn-dialog-confirm');
  setBusy(button, true, 'Bırakılıyor');
  try {
    await api.unfollowUser(pk, username);
    closeDialog();
    toast('@' + username + ' artık takip edilmiyor.', 'done');
    await loadStats();
    await loadTab(state.activeTab);
  } catch (err) {
    toast(err.message || 'Takip bırakılamadı.', 'problem');
  } finally {
    setBusy(button, false, 'Takibi bırak');
  }
});

/* ── Start ──────────────────────────────────────────────────────────────── */
(async function init() {
  try {
    const res = await api.authStatus();
    if (res.logged_in && res.account) {
      enterApp(res.account);
      return;
    }
  } catch (err) {
    /* Fall through to the sign-in screen: it is the right place to retry. */
  }
  showGate();
})();
