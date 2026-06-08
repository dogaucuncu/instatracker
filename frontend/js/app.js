/**
 * app.js — InstaTracker main application logic
 */

/* ══════════════════════════════════════════════════════════
   STATE
══════════════════════════════════════════════════════════ */
const state = {
  loggedIn: false,
  account: null,
  scanPolling: null,
  activeTab: 'unfollowers',
  // cached event data
  events: {
    unfollowers: [],
    blockers: [],
    deactivated: [],
    'new-followers': [],
    'scan-history': [],
  },
  // Pending unfollow action
  pendingUnfollow: null,
};

/* ══════════════════════════════════════════════════════════
   DOM REFS
══════════════════════════════════════════════════════════ */
const $ = id => document.getElementById(id);

const dom = {
  loginScreen:    $('login-screen'),
  app:            $('app'),

  // Login
  loginFormArea:  $('login-form-area'),
  twofaFormArea:  $('twofa-form-area'),
  challengeFormArea: $('challenge-form-area'),
  loginForm:      $('login-form'),
  twofaForm:      $('twofa-form'),
  inpUsername:    $('inp-username'),
  inpPassword:    $('inp-password'),
  inp2fa:         $('inp-2fa'),
  btnLogin:       $('btn-login'),
  btn2fa:         $('btn-2fa'),
  btnBackLogin:   $('btn-back-login'),
  btnDeviceApproved:    $('btn-device-approved'),
  btnChallengeContinue: $('btn-challenge-continue'),
  btnChallengeBack:     $('btn-challenge-back'),
  togglePw:       $('toggle-pw'),
  loginError:     $('login-error'),

  // Topbar
  accountAvatar:  $('account-avatar'),
  accountUsername:$('account-username'),
  accountFullname:$('account-fullname'),
  btnLogout:      $('btn-logout'),

  // Stats
  valFollowers:      $('val-followers'),
  valFollowing:      $('val-following'),
  valUnfollowed:     $('val-unfollowed'),
  valBlocked:        $('val-blocked'),
  valDeactivated:    $('val-deactivated'),
  valStillFollowing: $('val-still-following'),
  lastScanTime:      $('last-scan-time'),

  // Scan
  btnScan:         $('btn-scan'),
  btnScanText:     $('btn-scan-text'),
  scanProgress:    $('scan-progress'),
  scanProgressMsg: $('scan-progress-msg'),

  // Tabs
  tabBtns:  document.querySelectorAll('.tab-btn'),
  tabPanels:document.querySelectorAll('.tab-panel'),
  badgeUnfollowers:   $('badge-unfollowers'),
  badgeBlockers:      $('badge-blockers'),
  badgeDeactivated:   $('badge-deactivated'),
  badgeNewFollowers:  $('badge-new-followers'),

  // Modal
  confirmModal:   $('confirm-modal'),
  modalTitle:     $('modal-title'),
  modalMessage:   $('modal-message'),
  modalCancel:    $('modal-cancel'),
  modalConfirm:   $('modal-confirm'),

  // Toast
  toastContainer: $('toast-container'),
};

/* ══════════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════════ */
function toast(message, type = 'info', duration = 4000) {
  const icons = { success: '✓', error: '✗', warning: '⚠', info: 'ℹ' };
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.innerHTML = `
    <span class="toast-icon">${icons[type] || 'ℹ'}</span>
    <span class="toast-msg">${message}</span>
  `;
  dom.toastContainer.appendChild(el);
  setTimeout(() => {
    el.classList.add('hiding');
    setTimeout(() => el.remove(), 300);
  }, duration);
}

/* ══════════════════════════════════════════════════════════
   LOGIN
══════════════════════════════════════════════════════════ */
function showLoginScreen() {
  dom.loginScreen.classList.remove('hidden');
  dom.app.classList.add('hidden');
}

function showApp() {
  dom.loginScreen.classList.add('hidden');
  dom.app.classList.remove('hidden');
}

function setLoginLoading(loading) {
  const spinner = dom.btnLogin.querySelector('.btn-spinner');
  const text    = dom.btnLogin.querySelector('.btn-text');
  dom.btnLogin.disabled = loading;
  spinner.classList.toggle('hidden', !loading);
  text.classList.toggle('hidden',  loading);
}

function set2faLoading(loading) {
  const spinner = dom.btn2fa.querySelector('.btn-spinner');
  const text    = dom.btn2fa.querySelector('.btn-text');
  dom.btn2fa.disabled = loading;
  spinner.classList.toggle('hidden', !loading);
  text.classList.toggle('hidden',  loading);
}

function showLoginError(msg) {
  dom.loginError.textContent = msg;
  dom.loginError.classList.remove('hidden');
}

function hideLoginError() {
  dom.loginError.classList.add('hidden');
}

dom.togglePw.addEventListener('click', () => {
  const isPassword = dom.inpPassword.type === 'password';
  dom.inpPassword.type = isPassword ? 'text' : 'password';
  dom.togglePw.textContent = isPassword ? '🙈' : '👁';
});

dom.loginForm.addEventListener('submit', async e => {
  e.preventDefault();
  hideLoginError();
  const username = dom.inpUsername.value.trim();
  const password = dom.inpPassword.value;
  if (!username || !password) {
    showLoginError('Kullanıcı adı ve şifre gerekli.');
    return;
  }
  setLoginLoading(true);
  try {
    const res = await api.login(username, password);
    if (res.status === 'ok') {
      state.loggedIn = true;
      state.account  = res.account;
      updateAccountUI(res.account);
      showApp();
      loadDashboard();
    } else if (res.status === '2fa_required') {
      dom.loginFormArea.classList.add('hidden');
      dom.twofaFormArea.classList.remove('hidden');
    } else if (res.status === 'challenge_required') {
      // Device approval challenge
      dom.loginFormArea.classList.add('hidden');
      dom.challengeFormArea.classList.remove('hidden');
    }
  } catch (err) {
    showLoginError(err.message || 'Giriş başarısız.');
  } finally {
    setLoginLoading(false);
  }
});

dom.twofaForm.addEventListener('submit', async e => {
  e.preventDefault();
  hideLoginError();
  const code = dom.inp2fa.value.trim();
  if (!code) { showLoginError('Doğrulama kodu gerekli.'); return; }
  set2faLoading(true);
  try {
    const res = await api.verify2fa(code);
    if (res.status === 'ok') {
      state.loggedIn = true;
      state.account  = res.account;
      updateAccountUI(res.account);
      showApp();
      loadDashboard();
    }
  } catch (err) {
    showLoginError(err.message || '2FA doğrulama başarısız.');
  } finally {
    set2faLoading(false);
  }
});

dom.btnBackLogin.addEventListener('click', () => {
  dom.twofaFormArea.classList.add('hidden');
  dom.loginFormArea.classList.remove('hidden');
  hideLoginError();
});

// ── "Bildirimi Onayladım" button on the 2FA screen ────────
// Handles the case where Instagram sends a device push notification
// instead of (or in addition to) a code.
async function handleDeviceApproved(btn) {
  hideLoginError();
  const spinner = btn.querySelector('.btn-spinner');
  const text    = btn.querySelector('.btn-text');
  btn.disabled  = true;
  spinner.classList.remove('hidden');
  text.classList.add('hidden');
  try {
    const res = await api.challengeRetry();
    if (res.status === 'ok') {
      state.loggedIn = true;
      state.account  = res.account;
      updateAccountUI(res.account);
      showApp();
      loadDashboard();
    } else if (res.status === 'challenge_still_pending') {
      showLoginError((res.message || 'Henüz onaylanmadı.') + ' Tekrar deneyin.');
    } else if (res.status === '2fa_required') {
      // Still needs a code — stay on 2FA screen
      showLoginError('Lütfen SMS/uygulama kodunu girin.');
    }
  } catch (err) {
    showLoginError(err.message || 'Bağlantı hatası.');
  } finally {
    btn.disabled = false;
    spinner.classList.add('hidden');
    text.classList.remove('hidden');
  }
}

dom.btnDeviceApproved.addEventListener('click', () => handleDeviceApproved(dom.btnDeviceApproved));

// ── Device Challenge handlers ──────────────────────────────
dom.btnChallengeContinue.addEventListener('click', async () => {
  hideLoginError();
  const btn     = dom.btnChallengeContinue;
  const spinner = btn.querySelector('.btn-spinner');
  const text    = btn.querySelector('.btn-text');
  btn.disabled  = true;
  spinner.classList.remove('hidden');
  text.classList.add('hidden');

  try {
    const res = await api.challengeRetry();
    if (res.status === 'ok') {
      state.loggedIn = true;
      state.account  = res.account;
      updateAccountUI(res.account);
      showApp();
      loadDashboard();
    } else if (res.status === 'challenge_still_pending') {
      showLoginError(res.message || 'Henüz onaylanmadı. Lütfen telefonunuzu kontrol edin ve tekrar deneyin.');
    } else if (res.status === '2fa_required') {
      dom.challengeFormArea.classList.add('hidden');
      dom.twofaFormArea.classList.remove('hidden');
    }
  } catch (err) {
    showLoginError(err.message || 'Bağlantı hatası. Lütfen tekrar deneyin.');
  } finally {
    btn.disabled = false;
    spinner.classList.add('hidden');
    text.classList.remove('hidden');
  }
});

dom.btnChallengeBack.addEventListener('click', () => {
  dom.challengeFormArea.classList.add('hidden');
  dom.loginFormArea.classList.remove('hidden');
  hideLoginError();
});


dom.btnLogout.addEventListener('click', async () => {
  await api.logout().catch(() => {});
  state.loggedIn = false;
  state.account  = null;
  showLoginScreen();
  toast('Çıkış yapıldı.', 'info');
});

/* ══════════════════════════════════════════════════════════
   ACCOUNT UI
══════════════════════════════════════════════════════════ */
function updateAccountUI(account) {
  if (!account) return;
  dom.accountUsername.textContent = '@' + account.username;
  dom.accountFullname.textContent = account.full_name || '';
  if (account.profile_pic_url) {
    dom.accountAvatar.src = account.profile_pic_url;
  }
}

/* ══════════════════════════════════════════════════════════
   DASHBOARD
══════════════════════════════════════════════════════════ */
async function loadDashboard() {
  await Promise.all([
    loadStats(),
    loadTab(state.activeTab),
  ]);
}

async function loadStats() {
  try {
    const s = await api.dashboardStats();
    dom.valFollowers.textContent      = fmt(s.follower_count);
    dom.valFollowing.textContent      = fmt(s.following_count);
    dom.valUnfollowed.textContent     = fmt(s.unfollowed);
    dom.valBlocked.textContent        = fmt(s.blocked);
    dom.valDeactivated.textContent    = fmt(s.deactivated);
    dom.valStillFollowing.textContent = fmt(s.still_following_count);
    dom.lastScanTime.textContent      = s.last_scan
      ? formatDate(s.last_scan)
      : 'Henüz taranmadı';
    dom.badgeUnfollowers.textContent  = s.unfollowed;
    dom.badgeBlockers.textContent     = s.blocked;
    dom.badgeDeactivated.textContent  = s.deactivated;
    dom.badgeNewFollowers.textContent = s.new_followers;
  } catch (err) {
    console.warn('Stats load error:', err);
  }
}

function fmt(n) { return n === null || n === undefined ? '—' : n.toLocaleString('tr-TR'); }

function formatDate(iso) {
  if (!iso) return '—';
  // DB stores UTC times without timezone suffix.
  // Appending 'Z' tells the browser to treat it as UTC,
  // so toLocaleString() automatically converts to local time (e.g. UTC+3).
  let s = iso.replace(' ', 'T');
  if (!s.endsWith('Z') && !s.includes('+')) s += 'Z';
  const d = new Date(s);
  return d.toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}

/* ══════════════════════════════════════════════════════════
   TABS
══════════════════════════════════════════════════════════ */
dom.tabBtns.forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    switchTab(tab);
    loadTab(tab);
  });
});

function switchTab(tab) {
  state.activeTab = tab;
  dom.tabBtns.forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
  dom.tabPanels.forEach(p => p.classList.toggle('active', p.id === `panel-${tab}`));
}

async function loadTab(tab) {
  const panel = document.getElementById(`panel-${tab}`);
  if (!panel) return;

  if (tab === 'unfollowers') {
    const events = await api.getUnfollowers().catch(() => []);
    state.events.unfollowers = events;
    renderEventTable(panel, events, 'unfollowers');
  } else if (tab === 'blockers') {
    const events = await api.getBlockers().catch(() => []);
    state.events.blockers = events;
    renderEventTable(panel, events, 'blockers');
  } else if (tab === 'deactivated') {
    const events = await api.getDeactivated().catch(() => []);
    state.events.deactivated = events;
    renderEventTable(panel, events, 'deactivated');
  } else if (tab === 'new-followers') {
    const events = await api.getNewFollowers().catch(() => []);
    state.events['new-followers'] = events;
    renderEventTable(panel, events, 'new-followers');
  } else if (tab === 'scan-history') {
    const history = await api.scanHistory().catch(() => []);
    state.events['scan-history'] = history;
    renderScanHistory(panel, history);
  }
}

/* ══════════════════════════════════════════════════════════
   RENDER EVENT TABLE
══════════════════════════════════════════════════════════ */
const EVENT_LABELS = {
  unfollowed:   { label: '👋 Takipten Çıktı', cls: 'badge-unfollowed' },
  blocked:      { label: '🚫 Engelledi',       cls: 'badge-blocked' },
  deactivated:  { label: '⛔ Hesap Kapandı',   cls: 'badge-deactivated' },
  new_follower: { label: '🆕 Yeni Takipçi',    cls: 'badge-new_follower' },
};

function renderEventTable(panel, events, type) {
  if (!events || events.length === 0) {
    panel.innerHTML = `
      <div class="event-list-empty">
        <div class="empty-icon">🔍</div>
        <p>Henüz kayıtlı veri yok.</p>
        <p style="font-size:12px;margin-top:4px;color:var(--text-muted)">
          Tara butonuna basarak başlayın.
        </p>
      </div>`;
    return;
  }

  const showFollowingCol = ['unfollowers', 'blockers', 'deactivated'].includes(type);
  const showTypeCol      = type === 'all';

  let thead = `
    <thead>
      <tr>
        <th>Kullanıcı</th>
        <th>Tespit Tarihi</th>
        ${showFollowingCol ? '<th>Hala Takip Ediyor musun?</th><th>Aksiyon</th>' : ''}
        ${showTypeCol ? '<th>Olay</th>' : ''}
      </tr>
    </thead>`;

  let rows = events.map(ev => {
    const avatar = ev.profile_pic_url
      ? `<img src="${ev.profile_pic_url}" class="user-avatar" alt="avatar" onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 40 40%22><circle cx=%2220%22 cy=%2220%22 r=%2220%22 fill=%22%23444%22/><text x=%2250%25%22 y=%2255%25%22 dominant-baseline=%22middle%22 text-anchor=%22middle%22 fill=%22%23aaa%22 font-size=%2218%22>${ev.username[0].toUpperCase()}</text></svg>'" />`
      : `<div class="user-avatar" style="display:flex;align-items:center;justify-content:center;background:#333;color:#aaa;font-weight:700;font-size:16px">${ev.username[0].toUpperCase()}</div>`;

    const userCell = `
      <td>
        <div class="user-cell">
          ${avatar}
          <div class="user-info">
            <span class="user-username">
              <a href="https://instagram.com/${ev.username}" target="_blank" rel="noopener">@${ev.username}</a>
            </span>
            <span class="user-fullname">${ev.full_name || ''}</span>
          </div>
        </div>
      </td>`;

    const dateCell = `<td class="date-cell">${formatDate(ev.detected_at)}</td>`;

    let followingCell = '';
    let actionCell    = '';
    if (showFollowingCol) {
      if (ev.still_following) {
        followingCell = `<td><span class="badge-still">⚠️ Hala Takip Ediyorsunuz</span></td>`;
        actionCell    = `<td>
          <button class="btn-unfollow" data-pk="${ev.user_pk}" data-username="${ev.username}">
            Takipten Çık
          </button>
        </td>`;
      } else {
        followingCell = `<td><span class="badge-ok">✓ Takip Etmiyorsunuz</span></td>`;
        actionCell    = `<td></td>`;
      }
    }

    let typeCell = '';
    if (showTypeCol) {
      const t = EVENT_LABELS[ev.event_type] || { label: ev.event_type, cls: '' };
      typeCell = `<td><span class="event-type-badge ${t.cls}">${t.label}</span></td>`;
    }

    return `<tr>${userCell}${dateCell}${followingCell}${actionCell}${typeCell}</tr>`;
  }).join('');

  panel.innerHTML = `
    <div style="overflow-x:auto">
      <table class="event-table">
        ${thead}
        <tbody>${rows}</tbody>
      </table>
    </div>`;

  // Attach unfollow button listeners
  panel.querySelectorAll('.btn-unfollow').forEach(btn => {
    btn.addEventListener('click', () => {
      const pk       = btn.dataset.pk;
      const username = btn.dataset.username;
      openUnfollowModal(pk, username);
    });
  });
}

/* ══════════════════════════════════════════════════════════
   RENDER SCAN HISTORY
══════════════════════════════════════════════════════════ */
function renderScanHistory(panel, history) {
  if (!history || history.length === 0) {
    panel.innerHTML = `
      <div class="event-list-empty">
        <div class="empty-icon">🕐</div>
        <p>Henüz tarama yapılmadı.</p>
      </div>`;
    return;
  }

  const statusLabel = {
    completed:  '<span class="status-badge status-completed">✓ Tamamlandı</span>',
    running:    '<span class="status-badge status-running">⟳ Çalışıyor</span>',
    failed:     '<span class="status-badge status-failed">✗ Hata</span>',
    first_scan: '<span class="status-badge status-first_scan">★ İlk Tarama</span>',
  };

  const rows = history.map((h, i) => `
    <tr>
      <td style="color:var(--text-muted);font-weight:600">#${i + 1}</td>
      <td class="date-cell">${formatDate(h.started_at)}</td>
      <td class="date-cell">${h.completed_at ? formatDate(h.completed_at) : '—'}</td>
      <td>${statusLabel[h.status] || h.status}</td>
      <td style="color:var(--success);font-weight:700">${h.status !== 'first_scan' ? '+' + h.new_followers : '—'}</td>
      <td style="color:var(--danger);font-weight:700">${h.status !== 'first_scan' ? '-' + h.lost_followers : '—'}</td>
      ${h.error_message ? `<td style="color:var(--danger);font-size:12px">${h.error_message}</td>` : '<td></td>'}
    </tr>`).join('');

  panel.innerHTML = `
    <div style="overflow-x:auto">
      <table class="history-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Başlangıç</th>
            <th>Bitiş</th>
            <th>Durum</th>
            <th>Yeni Takipçi</th>
            <th>Kayıp</th>
            <th>Hata</th>
          </tr>
        </thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

/* ══════════════════════════════════════════════════════════
   SCAN
══════════════════════════════════════════════════════════ */
dom.btnScan.addEventListener('click', startScan);

async function startScan() {
  dom.btnScan.disabled = true;
  dom.btnScanText.textContent = 'Taranıyor...';
  dom.scanProgress.classList.remove('hidden');
  dom.scanProgressMsg.textContent = 'Tarama başlatılıyor...';

  try {
    await api.startScan();
    pollScanStatus();
  } catch (err) {
    toast(err.message || 'Tarama başlatılamadı.', 'error');
    resetScanUI();
  }
}

function pollScanStatus() {
  if (state.scanPolling) clearInterval(state.scanPolling);
  state.scanPolling = setInterval(async () => {
    try {
      const res = await api.scanStatus();
      if (res.status === 'running') {
        dom.scanProgressMsg.textContent = 'Takipçiler ve takip edilenler çekiliyor...';
        return;
      }
      clearInterval(state.scanPolling);
      state.scanPolling = null;

      if (res.status === 'completed') {
        const r = res.result;
        if (r.status === 'first_scan') {
          toast('İlk tarama tamamlandı! Baseline oluşturuldu. Sonraki taramada değişiklikler görünecek.', 'info', 6000);
        } else {
          toast(r.message || 'Tarama tamamlandı!', 'success', 5000);
        }
        await loadDashboard();
        await loadTab(state.activeTab);
      } else if (res.status === 'error') {
        toast('Tarama hatası: ' + res.message, 'error');
      }

      resetScanUI();
    } catch (err) {
      clearInterval(state.scanPolling);
      state.scanPolling = null;
      toast('Tarama durumu alınamadı.', 'error');
      resetScanUI();
    }
  }, 3000);
}

function resetScanUI() {
  dom.btnScan.disabled = false;
  dom.btnScanText.textContent = 'Şimdi Tara';
  dom.scanProgress.classList.add('hidden');
}

/* ══════════════════════════════════════════════════════════
   UNFOLLOW MODAL
══════════════════════════════════════════════════════════ */
function openUnfollowModal(pk, username) {
  state.pendingUnfollow = { pk, username };
  dom.modalTitle.textContent   = 'Takipten Çık';
  dom.modalMessage.textContent = `@${username} kullanıcısını takipten çıkmak istediğinizden emin misiniz?`;
  dom.confirmModal.classList.remove('hidden');
}

dom.modalCancel.addEventListener('click', () => {
  dom.confirmModal.classList.add('hidden');
  state.pendingUnfollow = null;
});

dom.confirmModal.addEventListener('click', e => {
  if (e.target === dom.confirmModal) {
    dom.confirmModal.classList.add('hidden');
    state.pendingUnfollow = null;
  }
});

dom.modalConfirm.addEventListener('click', async () => {
  if (!state.pendingUnfollow) return;
  const { pk, username } = state.pendingUnfollow;
  dom.modalConfirm.disabled = true;
  dom.modalConfirm.textContent = 'İşleniyor...';

  try {
    await api.unfollowUser(pk, username);
    toast(`@${username} takipten çıkarıldı.`, 'success');
    dom.confirmModal.classList.add('hidden');
    state.pendingUnfollow = null;
    await loadDashboard();
    await loadTab(state.activeTab);
  } catch (err) {
    toast(err.message || 'Takipten çıkarma başarısız.', 'error');
  } finally {
    dom.modalConfirm.disabled = false;
    dom.modalConfirm.textContent = 'Takipten Çık';
  }
});

/* ══════════════════════════════════════════════════════════
   INIT
══════════════════════════════════════════════════════════ */
async function init() {
  try {
    const res = await api.authStatus();
    if (res.logged_in && res.account) {
      state.loggedIn = true;
      state.account  = res.account;
      updateAccountUI(res.account);
      showApp();
      loadDashboard();
    } else {
      showLoginScreen();
    }
  } catch (err) {
    showLoginScreen();
  }
}

init();
