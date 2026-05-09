const API    = 'http://localhost:5000/api';
const WS_URL = `ws://${location.hostname}:5000/ws`;

const Token = {
  get:     ()  => localStorage.getItem('fw_token'),
  set:     (t) => localStorage.setItem('fw_token', t),
  clear:   ()  => localStorage.removeItem('fw_token'),
  headers: ()  => ({
    'Content-Type': 'application/json',
    'Authorization': `Bearer ${Token.get()}`,
  }),
};

const App = {
  showPage(name) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${name}`).classList.add('active');
    if (name === 'dashboard') Dashboard.init();
  },
  init() {
    const token = Token.get();
    if (token) {
      fetch(`${API}/auth/me`, { headers: Token.headers() })
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(data => { App.setUser(data.user); App.showPage('dashboard'); })
        .catch(() => { Token.clear(); App.showPage('onboarding'); });
    } else {
      App.showPage('onboarding');
    }
  },
  setUser(user) {
    document.getElementById('user-avatar').textContent = (user.name || user.email).slice(0,2).toUpperCase();
    document.getElementById('user-name').textContent   = user.name || user.email;
  },
};

const Auth = {
  async login() {
    const email    = document.getElementById('email').value.trim();
    const password = document.getElementById('password').value;
    const errEl    = document.getElementById('login-error');
    errEl.style.display = 'none';
    if (!email || !password) { errEl.textContent = 'Please enter email and password.'; errEl.style.display = 'block'; return; }

    const btn = document.getElementById('login-btn');
    btn.textContent = 'SIGNING IN...'; btn.disabled = true;
    try {
      const res  = await fetch(`${API}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email, password }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Login failed');
      Token.set(data.token); App.setUser(data.user); App.showPage('dashboard');
    } catch (err) {
      errEl.textContent = err.message; errEl.style.display = 'block';
    } finally {
      btn.textContent = 'SIGN IN →'; btn.disabled = false;
    }
  },

  async register() {
    const name = document.getElementById('reg-name').value.trim();
    const email = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-pass').value;
    const errEl = document.getElementById('reg-error');
    errEl.style.display = 'none';
    if (!name || !email || !password) { errEl.textContent = 'All fields required.'; errEl.style.display = 'block'; return; }
    try {
      const res  = await fetch(`${API}/auth/register`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, email, password }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Registration failed');
      Token.set(data.token); App.setUser(data.user); App.showPage('dashboard');
    } catch (err) { errEl.textContent = err.message; errEl.style.display = 'block'; }
  },

  logout() {
    Token.clear();
    if (wsClient) { wsClient.close(); wsClient = null; }
    App.showPage('login');
  },
};

let wsClient = null;
const WSManager = {
  connect() {
    if (wsClient && wsClient.readyState < 2) return;
    wsClient = new WebSocket(WS_URL);
    wsClient.onopen  = () => { const d = document.getElementById('ws-dot'); if(d){ d.className='ws-indicator connected'; d.title='WebSocket connected'; } };
    wsClient.onclose = () => { const d = document.getElementById('ws-dot'); if(d){ d.className='ws-indicator disconnected'; d.title='Disconnected'; } setTimeout(()=>WSManager.connect(), 3000); };
    wsClient.onmessage = ({ data }) => {
      try {
        const msg = JSON.parse(data);
        if (msg.type === 'event') { Events.prepend(msg.payload); if (msg.payload.severity !== 'info') Dashboard.loadStats(); }
        if (msg.type === 'scan_complete') { Dirs.load(); Dashboard.loadStats(); }
      } catch {}
    };
  },
};

const Dirs = {
  async load() {
    try {
      const res  = await fetch(`${API}/directories`, { headers: Token.headers() });
      const data = await res.json();
      Dirs.render(data.directories || []);
    } catch {}
  },
  render(dirs) {
    const list  = document.getElementById('dir-list');
    const badge = document.getElementById('dir-count-badge');
    badge.textContent = dirs.length;
    if (!dirs.length) { list.innerHTML = '<div class="empty-state">No directories monitored yet.</div>'; return; }
    list.innerHTML = dirs.map(d => {
      const alerts = d.alert_count || 0;
      const alertText  = alerts > 0 ? `${alerts} ALERT${alerts>1?'S':''}` : 'CLEAN';
      const badgeClass = alerts > 0 ? 'badge-alert' : 'badge-clean';
      return `<div class="dir-item" data-id="${d.id}">
        <div class="dir-path" title="${d.path}">${d.path}</div>
        <div class="dir-badge ${badgeClass}">${alertText}</div>
        <div class="dir-actions">
          <button class="dir-btn" onclick="Dirs.scan('${d.id}')">SCAN</button>
          <button class="dir-btn danger" onclick="Dirs.remove('${d.id}')">✕</button>
        </div>
      </div>`;
    }).join('');
  },
  async add() {
    const pathEl = document.getElementById('dir-path');
    const errEl  = document.getElementById('dir-error');
    const path   = pathEl.value.trim();
    errEl.style.display = 'none';
    if (!path) return;
    try {
      const res  = await fetch(`${API}/directories`, { method: 'POST', headers: Token.headers(), body: JSON.stringify({ path }) });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || 'Failed to add');
      pathEl.value = ''; Dirs.load(); Dashboard.loadStats();
    } catch (err) { errEl.textContent = err.message; errEl.style.display = 'block'; }
  },
  async remove(id) {
    if (!confirm('Stop monitoring this directory?')) return;
    try {
      const res = await fetch(`${API}/directories/${id}`, { method: 'DELETE', headers: Token.headers() });
      if (!res.ok) { const d = await res.json(); throw new Error(d.detail); }
      Dirs.load(); Dashboard.loadStats();
    } catch (err) { alert('Error: ' + err.message); }
  },
  async scan(id) {
    const item  = document.querySelector(`.dir-item[data-id="${id}"]`);
    const badge = item?.querySelector('.dir-badge');
    if (badge) { badge.textContent = 'SCANNING...'; badge.className = 'dir-badge badge-scanning'; }
    try { await fetch(`${API}/directories/${id}/scan`, { method: 'POST', headers: Token.headers() }); } catch {}
  },
};

const Events = {
  async load(severity = '') {
    try {
      const url  = `${API}/events?limit=50${severity ? '&severity=' + severity : ''}`;
      const res  = await fetch(url, { headers: Token.headers() });
      const data = await res.json();
      Events.render(data.events || []);
    } catch {}
  },
  render(events) {
    const list = document.getElementById('event-list');
    if (!events.length) { list.innerHTML = '<div class="empty-state">No events recorded yet.</div>'; return; }
    list.innerHTML = events.map(e => Events.rowHtml(e)).join('');
  },
  rowHtml(e) {
    const fname = (e.file_path||'').split('/').pop() || e.file_path;
    return `<div class="event-row">
      <div class="event-dot dot-${e.severity}"></div>
      <div class="event-body">
        <div class="event-file" title="${e.file_path}">${fname}</div>
        <div class="event-msg">${e.message}</div>
      </div>
      <div class="event-time">${Events.relTime(new Date(e.created_at))}</div>
    </div>`;
  },
  prepend(payload) {
    const list = document.getElementById('event-list');
    list.querySelector('.empty-state')?.remove();
    const w = document.createElement('div');
    w.innerHTML = Events.rowHtml({ file_path: payload.filePath, message: payload.message, severity: payload.severity, created_at: payload.timestamp });
    list.insertBefore(w.firstElementChild, list.firstChild);
    const rows = list.querySelectorAll('.event-row');
    if (rows.length > 60) rows[rows.length-1].remove();
  },
  relTime(date) {
    const s = Math.floor((Date.now() - date) / 1000);
    if (s < 60) return 'just now';
    if (s < 3600) return `${Math.floor(s/60)}m ago`;
    if (s < 86400) return `${Math.floor(s/3600)}h ago`;
    return `${Math.floor(s/86400)}d ago`;
  },
};

const Dashboard = {
  async init() {
    await Dashboard.loadStats();
    Dirs.load(); Events.load(); WSManager.connect();
  },
  async loadStats() {
    try {
      const res  = await fetch(`${API}/events/stats`, { headers: Token.headers() });
      const data = await res.json();
      document.getElementById('m-dirs').textContent   = data.directories    || 0;
      document.getElementById('m-files').textContent  = (data.files_tracked || 0).toLocaleString();
      document.getElementById('m-alerts').textContent = data.alerts_today   || 0;
      if (data.last_scan) document.getElementById('m-last-scan').textContent = `last scan ${Events.relTime(new Date(data.last_scan))}`;
      const n = data.directories || 0;
      document.getElementById('dash-sub').textContent = `Watching ${n} director${n===1?'y':'ies'} · ${(data.files_tracked||0).toLocaleString()} files indexed`;
    } catch {}
  },
  refreshAll() { Dashboard.loadStats(); Dirs.load(); Events.load(); },
};

document.addEventListener('keydown', e => {
  if (e.key !== 'Enter') return;
  const id = document.querySelector('.page.active')?.id;
  if (id === 'page-login') Auth.login();
  if (id === 'page-register') Auth.register();
  if (id === 'page-dashboard' && document.activeElement?.id === 'dir-path') Dirs.add();
});

App.init();