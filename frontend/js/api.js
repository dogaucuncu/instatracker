/**
 * api.js — Backend API wrapper
 * All fetch calls to the FastAPI backend go through here.
 */

const API_BASE = '';  // same origin

/** Pull a readable sentence out of whatever shape the error came back in. */
function messageFrom(data) {
  if (!data || typeof data !== 'object') return '';
  const { detail, message } = data;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((d) => (d && d.msg) || '').filter(Boolean).join(' ');
  }
  return typeof message === 'string' ? message : '';
}

const api = {
  async _fetch(path, options = {}) {
    const res = await fetch(API_BASE + path, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    // A FastAPI validation error arrives as {detail: [...]}; join it so the
    // caller shows a sentence rather than "[object Object]".
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(messageFrom(data) || `Sunucu ${res.status} döndü.`);
    }
    return data;
  },

  // ── Auth ──────────────────────────────────────────────────
  authStatus()           { return this._fetch('/api/auth/status'); },
  login(username, password) {
    return this._fetch('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    });
  },
  challengeRetry() {
    return this._fetch('/api/auth/challenge-retry', { method: 'POST' });
  },
  verify2fa(code) {
    return this._fetch('/api/auth/2fa', {
      method: 'POST',
      body: JSON.stringify({ code }),
    });
  },
  logout() {
    return this._fetch('/api/auth/logout', { method: 'POST' });
  },

  // ── Scan ──────────────────────────────────────────────────
  startScan()   { return this._fetch('/api/scan/start', { method: 'POST' }); },
  scanStatus()  { return this._fetch('/api/scan/status'); },
  scanHistory() { return this._fetch('/api/scan/history'); },

  // ── Dashboard ─────────────────────────────────────────────
  dashboardStats()  { return this._fetch('/api/dashboard/stats'); },
  getUnfollowers()  { return this._fetch('/api/events/unfollowers'); },
  getBlockers()     { return this._fetch('/api/events/blockers'); },
  getDeactivated()  { return this._fetch('/api/events/deactivated'); },
  getNewFollowers() { return this._fetch('/api/events/new-followers'); },

  // ── Actions ───────────────────────────────────────────────
  unfollowUser(user_pk, username) {
    return this._fetch('/api/actions/unfollow', {
      method: 'POST',
      body: JSON.stringify({ user_pk, username }),
    });
  },
};
