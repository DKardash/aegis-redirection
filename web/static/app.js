const $ = (id) => document.getElementById(id);

let token = localStorage.getItem("xgw_token") || "";

async function api(path, method = "GET", body) {
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = "Bearer " + token;
  const res = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401) {
    showLogin();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = j.detail || detail;
    } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }
  if (res.status === 204) return null;
  return res.json();
}

function toast(msg, isError = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("toast-error", isError);
  t.classList.toggle("toast-success", !isError);
  t.setAttribute("role", isError ? "alert" : "status");
  t.classList.remove("hidden");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.add("hidden"), 3500);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

/* ===== Country flags ===== */
const COUNTRY_CC = {
  Netherlands: "NL", Italy: "IT", Germany: "DE", "United States": "US",
  "United Kingdom": "GB", France: "FR", Sweden: "SE", Finland: "FI",
  Poland: "PL", Turkey: "TR", Ukraine: "UA", Japan: "JP", Singapore: "SG",
  "Hong Kong": "HK", Canada: "CA", Australia: "AU", Spain: "ES",
  Switzerland: "CH", Austria: "AT", Norway: "NO", Denmark: "DK", Belgium: "BE",
  Ireland: "IE", Czechia: "CZ", "Czech Republic": "CZ", Estonia: "EE",
  Latvia: "LV", Lithuania: "LT", Romania: "RO", Bulgaria: "BG", Greece: "GR",
  Portugal: "PT", Mexico: "MX", Brazil: "BR", India: "IN", Korea: "KR",
  Taiwan: "TW", Russia: "RU", Kazakhstan: "KZ", Georgia: "GE", Armenia: "AM",
  "UAE": "AE", "Saudi Arabia": "SA", Israel: "IL", "South Africa": "ZA",
};

function ccFlag(cc) {
  const c = String(cc || "").toUpperCase().replace(/[^A-Z]/g, "");
  if (c.length !== 2) return "";
  return String.fromCodePoint(0x1f1e6 + c.charCodeAt(0) - 65, 0x1f1e6 + c.charCodeAt(1) - 65);
}

function emojiToCC(flag) {
  const cps = [...String(flag || "")];
  if (cps.length !== 2) return "";
  return String.fromCharCode(
    cps[0].codePointAt(0) - 0x1f1e6 + 65,
    cps[1].codePointAt(0) - 0x1f1e6 + 65
  );
}

function flagInfo(name) {
  const s = String(name || "").trim();
  const ri = s.match(/^(\p{Regional_Indicator}\p{Regional_Indicator})/u);
  if (ri) {
    const cc = emojiToCC(ri[1]);
    return { cc, flag: ri[1], drop: ri[1].length };
  }
  for (const [cname, cc] of Object.entries(COUNTRY_CC)) {
    const m = s.match(new RegExp("^" + cname + "(?=_|\\s|$)", "i"));
    if (m) return { cc, flag: ccFlag(cc), drop: m[0].length };
  }
  return { cc: "", flag: "", drop: 0 };
}

function flagHtml(cc, fallbackEmoji) {
  if (!cc) return "";
  return `<img class="flag-img" src="https://flagcdn.com/w40/${cc.toLowerCase()}.png" alt="${cc}" title="${cc}" data-flag="${fallbackEmoji}" onerror="const el=document.createElement('span');el.className='flag-emoji';el.textContent=this.dataset.flag;this.replaceWith(el)">`;
}

function prettyName(s) {
  const raw = String(s || "").trim();
  const { cc, flag, drop } = flagInfo(raw);
  let rest = raw.slice(drop).replace(/^[\s_]+/, "");
  if (!rest) rest = raw;
  return (cc ? flagHtml(cc, flag) : "") + escapeHtml(rest);
}

/* ===== Row action icons ===== */
const ICONS = {
  pulse: '<svg viewBox="0 0 24 24"><path d="M2 12h4l3-8 4 16 3-8h6"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm-1.2 14.6-4.5-4.5 1.4-1.4 3.1 3.1 6.3-6.3 1.4 1.4-7.7 7.7z"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M3 17.3V21h3.7L17.8 9.9l-3.7-3.7L3 17.3zM20.7 7.1a1 1 0 0 0 0-1.4l-2.4-2.4a1 1 0 0 0-1.4 0l-1.9 1.9 3.7 3.7 2-1.8z"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>',
  pause: '<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>',
  eye: '<svg viewBox="0 0 24 24"><path d="M12 4.5C7 4.5 2.7 7.6 1 12c1.7 4.4 6 7.5 11 7.5s9.3-3.1 11-7.5c-1.7-4.4-6-7.5-11-7.5zm0 12.5a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M17.65 6.35A7.95 7.95 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>',
};

function actionIcons(id) {
  const a = (act, icon, title, cls) =>
    `<button class="icon-btn-sm ${cls || ""}" data-act="${act}" data-id="${id}" title="${title}">${ICONS[icon]}</button>`;
  return a("health", "pulse", "Проверить health", "ic-health") +
    a("test", "check", "Тест конфига", "ic-test") +
    a("edit", "edit", "Изменить", "ic-edit") +
    a("del", "trash", "Удалить", "ic-del");
}

function bytesStr(n) {
  if (!n) return "0 B";
  if (n >= 1073741824) return (n / 1073741824).toFixed(2) + " GB";
  if (n >= 1048576) return (n / 1048576).toFixed(2) + " MB";
  if (n >= 1024) return (n / 1024).toFixed(1) + " KB";
  return String(n) + " B";
}

function handshakeStr(sec) {
  if (!sec) return "—";
  if (sec < 60) return sec + "s";
  if (sec < 3600) return Math.floor(sec / 60) + "m" + (sec % 60) + "s";
  return Math.floor(sec / 3600) + "h";
}

function chip(ok, yesText = "ok", noText = "fail") {
  return ok
    ? `<span class="chip chip-success">${yesText}</span>`
    : `<span class="chip chip-error">${noText}</span>`;
}

function svcBadge(state) {
  if (state === "active") return '<span class="chip chip-success">active</span>';
  return '<span class="chip chip-muted">' + escapeHtml(state || "—") + "</span>";
}

/* ===== Views / navigation ===== */
const VIEW_TITLES = { overview: "Обзор", servers: "Серверы", interfaces: "Интерфейсы", password: "Смена пароля", docs: "Документация", addresslists: "Адрес Лист", audit: "Журнал", monitor: "Мониторинг", alerts: "Алерты" };
VIEW_TITLES.updates = "Проверить обновление";
VIEW_TITLES.zerotier = "ZeroTier";

function closeNav() {
  $("side-nav").classList.remove("open");
  $("nav-backdrop").classList.remove("show");
}

function switchView(name) {
  // Keep old links/bookmarks working after merging L2TP into Interfaces.
  if (name === "l2tp") name = "interfaces";
  document.querySelectorAll(".view").forEach((v) => v.classList.add("hidden"));
  const view = $("view-" + name);
  if (view) view.classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $("page-title").textContent = VIEW_TITLES[name] || name;
  closeNav();
  if (name === "servers") loadServers();
  if (name === "interfaces") loadProfiles().then(loadL2tp);
  if (name === "addresslists") { loadAddressLists(); loadAlMtLists(); loadAutoSync(); loadClientVpn(); }
  if (name === "audit") loadAudit();
  if (name === "monitor") { loadMonitor(); loadTrafficChart(); loadMikrotik(); loadRouterBackup(); }
  if (name === "alerts") loadAlerts();
  if (name === "updates") { loadUpdateStatus(); checkPanelUpdate(); }
  if (name === "zerotier") loadZeroTierStatus();
}

/* ===== ZeroTier remote access ===== */
let zeroTierBusy = false, zeroTierTimer = null;
async function loadZeroTierStatus() {
  if (!token) return;
  try {
    const data = await api('/api/zerotier/status');
    $('zt-network-id').value = data.network_id || '';
    $('zt-cidr').value = data.cidr || '10.241.0.0/16';
    const active = data.network_status === 'OK';
    const badge = $('zt-badge');
    const labels = { OK: 'Подключено', ACCESS_DENIED: 'Ожидает подтверждения', REQUESTING_CONFIGURATION: 'Получение адреса', NOT_JOINED: 'Не подключено' };
    badge.textContent = zeroTierBusy ? 'Подключаем…' : labels[data.network_status] || data.network_status || 'Не подключено';
    badge.className = 'chip ' + (active ? 'chip-success' : zeroTierBusy || data.network_status === 'ACCESS_DENIED' ? 'chip-warning' : 'chip-muted');
    $('zt-service').textContent = data.service === 'active' ? 'Работает' : data.installed ? (data.service || 'Остановлена') : 'Не установлена';
    $('zt-node-id').textContent = data.node_id || '—';
    const address = (data.assigned_ips || []).find(value => /^\d{1,3}(?:\.\d{1,3}){3}\//.test(value));
    const ip = address ? address.split('/')[0] : '';
    $('zt-address').textContent = ip || '—';
    const link = $('zt-panel-link');
    if (ip && ip.split('.').every(part => Number(part) >= 0 && Number(part) <= 255)) { link.href = 'http://' + ip + ':8790'; link.classList.remove('hidden'); }
    else link.classList.add('hidden');
    const job = data.job;
    zeroTierBusy = job?.status === 'running';
    const message = job?.status === 'failed' ? job.message : data.network_status === 'ACCESS_DENIED' ? 'Откройте ZeroTier Central и подтвердите это устройство по его Node ID.' : job?.status === 'complete' && !active ? job.message : '';
    $('zt-message').textContent = message;
    $('zt-message').classList.toggle('hidden', !message);
    $('btn-zt-connect').disabled = zeroTierBusy || active || !data.network_id;
    if (zeroTierBusy || !$('view-zerotier').classList.contains('hidden')) {
      clearTimeout(zeroTierTimer); zeroTierTimer = setTimeout(loadZeroTierStatus, 5000);
    }
  } catch (e) {
    $('zt-message').textContent = e.message;
    $('zt-message').classList.remove('hidden');
  }
}
async function saveZeroTierConfig() {
  try {
    const result = await api('/api/zerotier/config', 'POST', { network_id: $('zt-network-id').value, cidr: $('zt-cidr').value });
    $('zt-network-id').value = result.network_id; $('zt-cidr').value = result.cidr;
    toast('Параметры сети сохранены'); await loadZeroTierStatus();
  } catch (e) { toast('ZeroTier: ' + e.message, true); }
}
async function connectZeroTier() {
  if (zeroTierBusy) return;
  try {
    await api('/api/zerotier/config', 'POST', { network_id: $('zt-network-id').value, cidr: $('zt-cidr').value });
    zeroTierBusy = true; $('btn-zt-connect').disabled = true;
    $('zt-message').textContent = 'Подключаем ZeroTier. Панель останется доступной.';
    $('zt-message').classList.remove('hidden');
    await api('/api/zerotier/connect', 'POST');
    clearTimeout(zeroTierTimer); zeroTierTimer = setTimeout(loadZeroTierStatus, 1500);
  } catch (e) { zeroTierBusy = false; toast('ZeroTier: ' + e.message, true); await loadZeroTierStatus(); }
}

/* ===== Panel releases ===== */
let updateRelease = null, updateBusy = false, updateChecking = false, updateTimer = null;
function setUpdateMessage(message = '') {
  $('update-message').textContent = message;
  $('update-message').classList.toggle('hidden', !message);
}
function renderUpdateStatus(data) {
  $("sidebar-version").textContent = 'v' + data.current_version;
  $("update-current").textContent = 'v' + data.current_version;
  const job = data.job;
  updateBusy = !!job && ['starting', 'running'].includes(job.status);
  if (data.release) updateRelease = data.release;
  const r = updateRelease;
  $("btn-update-install").disabled = updateBusy || !r?.available || updateChecking;
  $("btn-update-check").disabled = updateBusy || updateChecking;
  const badge = $("update-badge");
  badge.textContent = updateBusy ? "Обновление выполняется" : updateChecking ? "Проверяем версию…" : r ? (r.available ? "Доступно обновление" : "Установлена актуальная версия") : "Версия не проверена";
  badge.className = 'chip ' + (updateBusy || r?.available ? 'chip-warning' : r ? 'chip-success' : 'chip-muted');
  if (r) {
    $("update-latest").textContent = 'v' + r.latest_version;
  }
  setUpdateMessage(job?.status === 'failed' ? 'Не удалось обновить панель. Повторите попытку.' : '');
  if (job?.status === 'complete' && sessionStorage.getItem('aegis-update-request') === job.id) {
    sessionStorage.removeItem('aegis-update-request');
    location.reload();
  }
  if (updateBusy || !$('view-updates').classList.contains('hidden')) {
    clearTimeout(updateTimer); updateTimer = setTimeout(loadUpdateStatus, 4000);
  }
}
async function loadUpdateStatus() {
  if (!token) return;
  try { renderUpdateStatus(await api('/api/updates/status')); }
  catch (e) {
    if (e.status === 401 || e.status === 403) { clearTimeout(updateTimer); return; }
    setUpdateMessage(updateBusy ? 'Панель перезапускается…' : 'Не удалось получить состояние обновлений: ' + e.message);
    if (updateBusy || !$('view-updates').classList.contains('hidden')) updateTimer = setTimeout(loadUpdateStatus, 5000);
  }
}
async function checkPanelUpdate() {
  if (updateChecking || updateBusy) return;
  updateChecking = true;
  $('btn-update-check').disabled = true;
  $('btn-update-install').disabled = true;
  setUpdateMessage();
  $('update-badge').textContent = 'Проверяем версию…';
  try { const data = await api('/api/updates/check', 'POST'); updateChecking = false; renderUpdateStatus(data); }
  catch (e) {
    updateRelease = null;
    setUpdateMessage(e.message);
    $('update-badge').textContent = 'Проверка недоступна';
    $('update-badge').className = 'chip chip-warning';
  } finally { updateChecking = false; $('btn-update-check').disabled = updateBusy; }
}
async function installPanelUpdate() {
  if (updateBusy || !updateRelease?.available) return;
  if (!confirm('Обновить панель до v' + updateRelease.latest_version + '? Будет создана резервная копия. Возможно кратковременное прерывание подключений.')) return;
  updateBusy = true; $('btn-update-install').disabled = true; $('btn-update-check').disabled = true;
  try {
    const job = await api('/api/updates/install', 'POST', { tag: updateRelease.tag });
    sessionStorage.setItem('aegis-update-request', job.id);
    setUpdateMessage();
    $('update-badge').textContent = 'Обновление выполняется';
    clearTimeout(updateTimer); updateTimer = setTimeout(loadUpdateStatus, 1500);
  } catch (e) {
    updateBusy = false;
    await loadUpdateStatus();
    setUpdateMessage(e.message);
  }
}

/* ===== Status / Overview ===== */
async function loadStatus() {
  try {
    const s = await api("/api/status");
    const badge = $("status-badge");
    const enabled = s.enabled_count || 0, healthy = s.healthy_count || 0;
    const ok = enabled > 0 && enabled === healthy && s.xray_process;
    badge.textContent = !enabled ? "Нет интерфейсов" : ok ? "Работает" : "Требует внимания";
    badge.className = "chip " + (ok ? "chip-success" : "chip-warning");
    $("stat-active").textContent = enabled;
    $("stat-active-sub").textContent = "включённых интерфейсов";

    $("stat-xray").textContent = s.xray_process ? "Running" : "Stopped";
    $("stat-xray-sub").textContent = s.xray_config_valid ? "конфиг валиден" : "конфиг невалиден";
    $("stat-xray-sub").className = "stat-sub" + (s.xray_config_valid ? "" : " err");

    $("stat-health").textContent = `${healthy} / ${enabled}`;
    $("stat-health-sub").textContent = "рабочих интерфейсов по последней проверке";
    $("stat-best").textContent = s.backup_count || 0;
    $("stat-best-sub").textContent = "интерфейсов используют резерв";
    $("overview-routes").innerHTML = (s.profiles || []).map((p) =>
      `<div class="row-line"><span>${escapeHtml(p.local_ip)}/${p.prefix}</span><b>${escapeHtml(p.active_server_name || "Выход заблокирован")}${p.on_backup ? " · резерв" : ""}</b></div>`
    ).join("") || '<p class="muted">Добавьте интерфейс и выберите сервер для него.</p>';
  } catch (e) {
    toast("status: " + e.message, true);
  }
}

/* ===== Traffic ===== */
let trafficTimer = null;

async function loadTraffic() {
  try {
    const m = await api("/api/monitor/status");
    const sys = m.system || {};
    const mem = sys.memory || {};
    const disk = sys.disk || {};
    const sessions = (m.l2tp && m.l2tp.sessions) || [];
    const services = m.services || {};
    const activeServices = Object.values(services).filter((state) => state === "active").length;
    const totalServices = Object.keys(services).length;
    const memPct = mem.total ? Math.round(mem.used / mem.total * 100) : 0;
    const diskPct = disk.total ? Math.round(disk.used / disk.total * 100) : 0;
    $("stat-l2tp").textContent = sessions.length;
    $("stat-public-ip").textContent = m.public_ip || "—";
    $("stat-resources").textContent = `${sys.cpu || 0}% · ${memPct}%`;
    $("stat-resources-sub").textContent = `CPU · RAM · диск ${diskPct}%`;
    $("traffic-info").innerHTML =
      `<div class="row-line"><span>Сервисы</span><b>${activeServices} из ${totalServices} активны</b></div>` +
      `<div class="row-line"><span>Активные L2TP-сессии</span><b>${sessions.length}</b></div>` +
      `<div class="row-line"><span>Время работы ВМ</span><b>${uptimeStr(sys.uptime)}</b></div>` +
      `<div class="row-line"><span>Использование диска</span><b>${diskPct}%</b></div>`;
  } catch (e) {
    $("traffic-info").innerHTML = `<div class="row-line"><span>Данные узла недоступны</span><b>${escapeHtml(e.message)}</b></div>`;
  }
}

function startTrafficPoll() {
  if (trafficTimer) return;
  trafficTimer = setInterval(loadTraffic, 30000);
}

/* ===== Monitor ===== */
let monitorTimer = null;

function uptimeStr(sec) {
  if (!sec) return "—";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return (d > 0 ? d + "д " : "") + h + "ч " + m + "м";
}

function pctHtml(used, total) {
  if (!total) return "—";
  const pct = Math.round((used / total) * 100);
  const bar = `<div class="bar"><i style="width:${Math.min(pct, 100)}%"></i></div>`;
  return `${pct}% <span class="bar-wrap">${bar}</span>`;
}

async function loadTunnelCheck() {
  try {
    const t = await api("/api/monitor/tunnel/check");
    const lat = t.latency_ms != null ? ` · ${t.latency_ms}ms` : "";
    const info = `${(t.profiles || []).length} интерфейсов` + lat;
    $("mon-tunnel").innerHTML =
      (t.ok
        ? `<span class="chip chip-success">OK</span> ${info}`
        : `<span class="chip chip-error">FAIL</span> ${info} ${escapeHtml(t.error || "")}`.trim());
  } catch (e) {
    $("mon-tunnel").innerHTML = `<span class="chip chip-error">—</span> ${escapeHtml(e.message)}`;
  }
}

async function loadMonitor() {
  try {
    const m = await api("/api/monitor/status");
    const sys = m.system || {};
    const mem = sys.memory || {};
    const disk = sys.disk || {};
    const svc = m.services || {};

    $("mon-cpu").textContent = sys.cpu != null ? sys.cpu + "%" : "—";
    $("mon-cpu-sub").textContent = sys.loadavg ? "load " + sys.loadavg : "";

    $("mon-ram").innerHTML = pctHtml(mem.used, mem.total);
    $("mon-ram-sub").textContent = mem.total ? `${bytesStr(mem.used)} / ${bytesStr(mem.total)}` : "";

    $("mon-disk").innerHTML = pctHtml(disk.used, disk.total);
    $("mon-disk-sub").textContent = disk.total ? `${bytesStr(disk.used)} / ${bytesStr(disk.total)}` : "";

    $("mon-uptime").textContent = uptimeStr(sys.uptime);
    $("mon-uptime-sub").textContent = sys.hostname || "";

    $("mon-ip").textContent = m.public_ip || "— (нет туннеля)";
    $("mon-ppp").textContent = m.tunnel ? m.tunnel.ppp_count : 0;

    const badges = ["xray", "strongswan-starter", "xl2tpd", "manager"]
      .map((u) => `<span class="chip ${svc[u] === "active" ? "chip-success" : "chip-error"}">${u}</span>`)
      .join(" ");
    $("mon-services").innerHTML = badges;

    const srv = (m.l2tp && m.l2tp.services) || {};
    const sess = (m.l2tp && m.l2tp.sessions) || [];
    const rows = sess.map((s) =>
      `<div class="row-line"><span>${escapeHtml(s.interface)} (${escapeHtml(s.state)}) · ${escapeHtml(s.address || "—")}</span><b>↓ ${bytesStr(s.rx_bytes)} · ↑ ${bytesStr(s.tx_bytes)}</b></div>`
    ).join("");
    $("mon-l2tp-sessions").innerHTML = rows
      ? `<div class="row-line" style="color:var(--text-secondary);font-size:12px;">L2TP-сессии: ${srv.strongswan} / ${srv.xl2tpd}</div>` + rows
      : `<div class="row-line" style="color:var(--text-secondary);font-size:12px;">Активных L2TP-сессий нет (strongswan ${srv.strongswan} / xl2tpd ${srv.xl2tpd})</div>`;
    loadTunnelCheck();
  } catch (e) {
    toast("monitor: " + e.message, true);
  }
}

function startMonitorPoll() {
  if (monitorTimer) return;
  monitorTimer = setInterval(loadMonitor, 15000);
}

let mikrotikPoll = null;

function startMikrotikPoll() {
  if (mikrotikPoll) return;
  mikrotikPoll = setInterval(() => {
    if (!token || document.hidden) return;
    const cur = document.querySelector(".view:not(.hidden)");
    if (!cur) return;
    if (cur.id === "view-monitor") loadMikrotikStatus().catch(() => {});
    if (cur.id === "view-addresslists") loadAlMtEntries();
  }, 20000);
}

let trafficChartTimer = null;

function trafficRate(samples) {
  const rates = [];
  for (let i = 1; i < samples.length; i++) {
    const a = samples[i - 1], b = samples[i];
    let dt = (new Date(b.ts) - new Date(a.ts)) / 1000;
    if (dt <= 0) dt = 1;
    rates.push({ ts: b.ts, rx: Math.max(0, (b.rx - a.rx) / dt), tx: Math.max(0, (b.tx - a.tx) / dt) });
  }
  return rates;
}

function drawTrafficChart(canvas, series, label) {
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.clientWidth, H = canvas.clientHeight;
  canvas.width = W * dpr; canvas.height = H * dpr;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, W, H);

  const pad = { l: 52, r: 12, t: 12, b: 22 };
  const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;

  const data = series.filter((s) => s.length > 1);
  let max = 0;
  data.forEach((arr) => arr.forEach((p) => { max = Math.max(max, p.rx, p.tx); }));
  if (max <= 0) max = 1;
  max = max * 1.15;

  const colors = {
    "wg0.rx": "rgba(56,150,246,0.9)",
    "wg0.tx": "rgba(56,150,246,0.35)",
    "ppp.rx": "rgba(16,185,129,0.9)",
    "ppp.tx": "rgba(16,185,129,0.35)",
  };

  function y(v) { return pad.t + ch - (v / max) * ch; }

  ctx.strokeStyle = "rgba(128,128,128,0.15)";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const yy = pad.t + (ch / 4) * i;
    ctx.beginPath(); ctx.moveTo(pad.l, yy); ctx.lineTo(pad.l + cw, yy); ctx.stroke();
    ctx.fillStyle = "rgba(128,128,128,0.7)";
    ctx.font = "11px Inter, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText(fmtRate(max - (max / 4) * i), pad.l - 6, yy + 4);
  }

  data.forEach((arr) => {
    Object.entries({ rx: "rx", tx: "tx" }).forEach(([field]) => {
      const key = label + "." + field;
      ctx.strokeStyle = colors[key];
      ctx.lineWidth = 1.6;
      ctx.beginPath();
      arr.forEach((p, i) => {
        const x = pad.l + (cw * i) / (arr.length - 1);
        const yy = y(p[field]);
        if (i === 0) ctx.moveTo(x, yy); else ctx.lineTo(x, yy);
      });
      ctx.stroke();
    });
  });
}

function fmtRate(bps) {
  if (bps >= 1e9) return (bps / 1e9).toFixed(1) + " Gb/s";
  if (bps >= 1e6) return (bps / 1e6).toFixed(1) + " Mb/s";
  if (bps >= 1e3) return (bps / 1e3).toFixed(0) + " Kb/s";
  return Math.round(bps) + " b/s";
}

async function loadTrafficChart() {
  const canvas = $("traffic-canvas");
  if (!canvas) return;
  try {
    const r = await api("/api/monitor/traffic?minutes=60");
    const ppp = trafficRate(r.ppp || []);
    drawTrafficChart(canvas, [ppp], "ppp");
    const last = ppp.length ? ppp[ppp.length - 1] : null;
    $("traffic-now").textContent = last ? `сейчас: RX ${fmtRate(last.rx)} · TX ${fmtRate(last.tx)}` : "";
  } catch (e) {
    $("traffic-now").textContent = "traffic: " + e.message;
  }
}

function startTrafficPoll() {
  if (trafficChartTimer) return;
  let busy = false;
  trafficChartTimer = setInterval(async () => {
    if (busy || !token || document.hidden) return;
    busy = true;
    try {
      const view = document.querySelector(".view:not(.hidden)")?.id;
      if (view === "view-overview") await Promise.all([loadStatus(), loadServers(), loadTraffic()]);
      if (view === "view-interfaces") await loadProfiles();
      if (view === "view-servers") await loadServers();
      if (view === "view-monitor") await loadTrafficChart();
    } finally { busy = false; }
  }, 15000);
}

/* ===== MikroTik ===== */
async function loadMikrotikStatus() {
  try {
    renderMikrotikResult(await api("/api/mikrotik/status"));
    await loadTunnelMode();
  } catch (e) {
    renderMikrotikResult({ ok: false, error: e.message });
  }
}

async function loadMikrotik() {
  try {
    const cfg = await api("/api/mikrotik/config");
    $("mt-host").value = cfg.host || "";
    $("mt-port").value = cfg.port || 8728;
    $("mt-user").value = cfg.username || "";
    $("mt-pass").value = cfg.password || "";
    $("mt-ssl").checked = cfg.use_ssl;
    $("mt-af").checked = !!cfg.auto_failover;
    $("mt-af-interval").value = cfg.failover_interval || 30;
    await loadMikrotikStatus();
  } catch (e) {
    renderMikrotikResult({ ok: false, error: e.message });
  }
}

function renderMikrotikResult(s) {
  const box = $("mt-result");
  if (!s.configured) {
    box.innerHTML = '<div class="row-line muted">Роутер не настроен. Укажите IP/логин/пароль выше.</div>';
    return;
  }
  if (!s.ok) {
    box.innerHTML = `<div class="row-line"><span>Статус</span><b>${chip(false, "недоступен", "ok")} ${escapeHtml(s.error || "")}</b></div>`;
    return;
  }
  const rows = [];
  rows.push(`<div class="row-line"><span>Статус</span><b>${chip(true, "доступен", "нет")}</b></div>`);
  rows.push(`<div class="row-line"><span>Туннель</span><b id="mt-mode-line">…</b></div>`);
  rows.push(`<div class="row-line"><span>Модель</span><b>${escapeHtml(s.board || "—")}</b></div>`);
  rows.push(`<div class="row-line"><span>RouterOS</span><b>${escapeHtml(s.version || "—")}</b></div>`);
  rows.push(`<div class="row-line"><span>Uptime</span><b>${uptimeStr(s.uptime_sec)} ${s.uptime_raw ? "(" + escapeHtml(s.uptime_raw) + ")" : ""}</b></div>`);
  rows.push(`<div class="row-line"><span>CPU load</span><b>${s.cpu_load != null ? s.cpu_load + "%" : "—"}</b></div>`);
  rows.push(`<div class="row-line"><span>Память</span><b>${s.total_memory ? `${bytesStr((s.total_memory - (s.free_memory || 0)))} / ${bytesStr(s.total_memory)}` : "—"}</b></div>`);
  rows.push(`<div class="row-line"><span>Температура</span><b>${s.temperature != null ? s.temperature + "°C" : "—"}</b></div>`);
  rows.push(`<div class="row-line"><span>Вольтаж</span><b>${s.voltage != null ? s.voltage + "V" : "—"}</b></div>`);
  const al = s.address_lists || {};
  rows.push(`<div class="row-line"><span>Address-list VPN</span><b>${al.total ?? "—"} записей (${al.dynamic ?? 0} динамич.)</b></div>`);
  if (s.mangle && s.mangle.length) {
    const acts = s.mangle.map((m) => `${escapeHtml(m.chain)}→${escapeHtml(m.action)}${m.comment ? " (" + escapeHtml(m.comment) + ")" : ""}`).join("<br>");
    rows.push(`<div class="row-line"><span>mangle (${s.mangle.length})</span><b class="mono">${acts}</b></div>`);
  }
  box.innerHTML = rows.join("");
}

async function saveMikrotik(e) {
  e.preventDefault();
  try {
    await api("/api/mikrotik/config", "POST", {
      host: $("mt-host").value.trim(),
      port: +$("mt-port").value || 8728,
      username: $("mt-user").value.trim(),
      password: $("mt-pass").value,
      use_ssl: $("mt-ssl").checked,
      auto_failover: $("mt-af").checked,
      failover_interval: Math.max(15, +$("mt-af-interval").value || 30),
    });
    toast("Настройки MikroTik сохранены");
    await loadMikrotik();
  } catch (e2) {
    toast("save mikrotik: " + e2.message, true);
  }
}

async function testMikrotik() {
  const btn = $("btn-mt-test");
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/test", "POST");
    if (r.ok) {
      toast("Подключение к роутеру OK: " + (r.details && (r.details["board-name"] || r.details["version"]) || ""));
    } else {
      toast("Подключение не удалось: " + r.error, true);
    }
  } catch (e) {
    toast("test mikrotik: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ===== Бэкап конфига роутера ===== */
async function loadRouterBackup() {
  try {
    const cfg = await api("/api/mikrotik/config-backups/schedule");
    $("rb-enabled").checked = !!cfg.enabled;
    $("rb-time").value = cfg.time || "03:00";
    $("rb-last").textContent = cfg.last_run ? cfg.last_run : "—";
    await loadRouterBackups();
  } catch (e) {
    toast("router backup cfg: " + e.message, true);
  }
}

async function loadRouterBackups() {
  const body = $("rb-body");
  try {
    const r = await api("/api/mikrotik/config-backups");
    const bs = r || [];
    if (!bs.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted">Бэкапов пока нет. Создаются вручную или по расписанию.</td></tr>';
      return;
    }
    body.innerHTML = bs.slice(0, 8).map((b) => `
      <tr>
        <td class="mono">${escapeHtml(b.name)}</td>
        <td class="mono">${fmtSize(b.size)}</td>
        <td class="mono">${escapeHtml(b.mtime)}</td>
        <td class="ta-r">
          <button class="icon-btn-sm" data-rbact="view" data-name="${escapeHtml(b.name)}" title="Просмотр">${ICONS.eye}</button>
        </td>
      </tr>`).join("");
    body.querySelectorAll("[data-rbact]").forEach((btn) => {
      btn.addEventListener("click", () => viewRouterBackup(btn.dataset.name));
    });
  } catch (e) {
    body.innerHTML = `<tr><td colspan="4" class="muted">${escapeHtml(e.message)}</td></tr>`;
  }
}

async function saveRouterBackup() {
  const btn = $("btn-rb-save");
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/config-backups/schedule", "POST", {
      enabled: $("rb-enabled").checked,
      time: $("rb-time").value || "03:00",
    });
    toast("Настройки бэкапа сохранены");
    $("rb-result").textContent = "";
    await loadRouterBackup();
  } catch (e) {
    toast("router backup save: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function runRouterBackup() {
  const btn = $("btn-rb-now");
  const box = $("rb-result");
  btn.disabled = true;
  box.textContent = "Снимаем бэкап…";
  try {
    const r = await api("/api/mikrotik/config-backups/now", "POST");
    box.textContent = "Бэкап: " + (r.message || "готов");
    toast("Бэкап конфига: " + (r.message || "готов"));
    await loadRouterBackups();
    await loadRouterBackup();
  } catch (e) {
    box.textContent = e.message;
    toast("router backup: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function viewRouterBackup(name) {
  try {
    const r = await api("/api/mikrotik/config-backups/" + encodeURIComponent(name));
    const text = r.text || "";
    const win = window.open("", "_blank");
    if (!win) return;
    win.document.write("<pre style='font:12px monospace;white-space:pre-wrap;padding:12px'>" +
      escapeHtml(text) + "</pre>");
    win.document.close();
  } catch (e) {
    toast("view backup: " + e.message, true);
  }
}

async function exportRouterRsc() {
  const btn = $("btn-rb-export");
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/config-backups/export");
    const name = r.name || "router-config.rsc";
    const blob = new Blob([r.text], { type: "text/plain;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast("Экспорт .rsc: " + name);
  } catch (e) {
    toast("router rsc export: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function loadTunnelMode() {
  const btn = $("btn-mt-mode");
  const line = $("mt-mode-line");
  if (!btn) return;
  try {
    const r = await api("/api/mikrotik/mode");
    if (!r.ok) {
      btn.disabled = true;
      btn.textContent = "Режим: недоступен";
      if (line) line.textContent = "—";
      return;
    }
    btn.disabled = false;
    const label = r.mode === "l2tp" ? "L2TP" : r.mode === "wg" ? "WG" : "none";
    const target = r.mode === "l2tp" ? "WG" : "L2TP";
    btn.textContent = "Режим: " + label + " → " + target;
    if (line) {
      const t = r.tunnels || {};
      const parts = [];
      const fmtTun = (k, name) => {
        const v = t[k];
        if (!v) return name + ": —";
        const hs = v.handshake_sec != null ? `, handshake ${handshakeStr(v.handshake_sec)}` : "";
        const tr = v.rx != null ? `, ${bytesStr(v.rx)}/↓ ${bytesStr(v.tx)}↑` : "";
        return `${name}: ${v.up ? '<span class="chip chip-success">UP</span>' : '<span class="chip chip-error">DOWN</span>'}${hs}${tr}`;
      };
      parts.push(fmtTun("wg", "WG"));
      parts.push(fmtTun("l2tp", "L2TP"));
      const routes = (r.routes || []).filter((x) => x.gateway);
      if (routes.length) {
        parts.push("Маршрут: " + routes.map((x) => `${escapeHtml(x.table)} → ${escapeHtml(x.gateway)}${x.active ? "" : " (неактив)"}`).join(" · "));
      }
      const cv = r.client_vpn_count || 0;
      if (cv) {
        const cvTbl = r.client_vpn_table || "";
        const match = (r.mode === "l2tp" && cvTbl.includes("mark_table_L2TP")) || (r.mode === "wg" && cvTbl.includes("mark_table_VPN"));
        parts.push(`Клиенты VPN: ${cv} ${match ? `→ ${escapeHtml(cvTbl)}` : `<span class="chip chip-warning">через другой туннель (${escapeHtml(cvTbl)})</span>`}`);
      }
      line.innerHTML = `<b>${label}</b> (mangle WG: ${r.wg_rules}, L2TP: ${r.l2tp_rules})` +
        `<br><span class="muted" style="font-size:12px">${parts.join(" · ")}</span>`;
    }
  } catch (e) {
    btn.disabled = true;
    btn.textContent = "Режим: …";
    if (line) line.textContent = "—";
  }
}

async function toggleTunnelMode() {
  const btn = $("btn-mt-mode");
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/mode");
    if (!r.ok) throw new Error(r.error || "mode unavailable");
    const target = r.mode === "l2tp" ? "wg" : "l2tp";
    try {
      const res = await api("/api/mikrotik/mode", "POST", { mode: target });
      toast(res.message || "Режим переключён");
    } catch (e2) {
      if (e2.status === 409 && await showConfirm({ message: "Целевой туннель не отвечает. Переключить принудительно?", okText: "Переключить", danger: false })) {
        const res = await api("/api/mikrotik/mode", "POST", { mode: target, force: true });
        toast(res.message || "Режим переключён принудительно");
      } else {
        throw e2;
      }
    }
    await loadTunnelMode();
  } catch (e) {
    toast("mode: " + e.message, true);
    btn.disabled = false;
  }
}

async function loadMonitorServers() {
  const body = $("mon-servers-body");
  const btn = $("btn-mon-servers");
  if (btn) btn.disabled = true;
  body.innerHTML = '<tr><td colspan="6" class="muted">Проверка…</td></tr>';
  try {
    const list = await api("/api/monitor/servers");
    body.innerHTML = "";
    if (!list.length) {
      body.innerHTML = '<tr><td colspan="6" class="muted">Нет включённых серверов</td></tr>';
      return;
    }
    for (const s of list) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${s.id}</td>
        <td class="name-cell"><b>${prettyName(s.name)}</b></td>
        <td class="mono">${escapeHtml(s.address)}</td>
        <td>${chip(s.ok, "OK", "FAIL")}</td>
        <td>${s.latency_ms != null ? s.latency_ms + "ms" : "—"}</td>
        <td>${s.best_latency_ms != null ? s.best_latency_ms + "ms" : "—"}</td>`;
      body.appendChild(tr);
    }
  } catch (e) {
    body.innerHTML = `<tr><td colspan="6" class="muted">${escapeHtml(e.message)}</td></tr>`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

/* ===== WireGuard ===== */
async function loadWg() {
  try {
    const s = await api("/api/wg/status");
    const svc = s.services || {};
    const iface = s.interface || {};
    const summary = [
      `<span>wg-quick: ${svcBadge(svc.wg_quick)}</span>`,
      `<span>tproxy: ${svcBadge(svc.tproxy)}</span>`,
      `<span>Интерфейс: ${s.interface_up ? '<span class="chip chip-success">поднят</span>' : '<span class="chip chip-error">не поднят</span>'}</span>`,
      `<span>Address: <b class="mono">${escapeHtml(iface.address || "—")}</b></span>`,
      `<span>Listen port: <b>${escapeHtml(iface.listen_port || "—")}</b></span>`,
      `<span>Public key: <b class="mono">${escapeHtml(iface.public_key || "—")}</b></span>`,
    ];
    $("wg-info").innerHTML = summary.join("");

    const body = $("wg-body");
    body.innerHTML = "";
    for (const p of s.peers || []) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(p.public_key)}</td>
        <td>${escapeHtml(p.endpoint || "—")}</td>
        <td class="mono">${escapeHtml(p.allowed_ips || "—")}</td>
        <td>${escapeHtml(p.persistent_keepalive || "—")}</td>
        <td>${handshakeStr(p.last_handshake_sec)}</td>
        <td class="mono">${bytesStr(p.rx_bytes)} / ${bytesStr(p.tx_bytes)}</td>
        <td class="ta-r">
          <div class="actions" style="justify-content:flex-end">
            <button class="icon-btn-sm ic-edit" data-wgact="edit" data-pk="${escapeHtml(p.public_key)}" title="Изменить">${ICONS.edit}</button>
            <button class="icon-btn-sm ic-del" data-wgact="del" data-pk="${escapeHtml(p.public_key)}" title="Удалить">${ICONS.trash}</button>
          </div>
        </td>`;
      body.appendChild(tr);
    }
  } catch (e) {
    $("wg-info").textContent = "wg: " + e.message;
  }
}

function openWgPeerModal(peer) {
  $("wg-pk-orig").value = peer ? peer.public_key : "";
  $("wg-pk").value = peer ? peer.public_key : "";
  $("wg-endpoint").value = peer ? peer.endpoint || "" : "";
  $("wg-allowed").value = peer ? peer.allowed_ips || "" : "";
  $("wg-keepalive").value = peer ? peer.persistent_keepalive || "" : "";
  $("wg-peer-title").textContent = peer ? "Изменить peer" : "Добавить peer";
  $("wg-peer-modal").classList.remove("hidden");
}

async function saveWgPeer(e) {
  e.preventDefault();
  try {
    const payload = {
      public_key: $("wg-pk").value.trim(),
      endpoint: $("wg-endpoint").value.trim(),
      allowed_ips: $("wg-allowed").value.trim(),
      persistent_keepalive: $("wg-keepalive").value.trim(),
    };
    await api("/api/wg/peer", "POST", payload);
    $("wg-peer-modal").classList.add("hidden");
    toast("Peer сохранён");
    await loadWg();
  } catch (e2) {
    toast("wg peer: " + e2.message, true);
  }
}

function openWgIfaceModal(status) {
  const iface = status ? status.interface : null;
  $("wg-address").value = iface ? iface.address || "" : "10.200.0.2/24";
  $("wg-port").value = iface ? iface.listen_port || "" : "51820";
  $("wg-iface-modal").classList.remove("hidden");
}

/* ===== Servers ===== */
let serverCache = [];

function renderServers(servers, bestId = null) {
  const body = $("servers-body");
  body.innerHTML = "";
  $("servers-empty").classList.toggle("hidden", servers.length > 0);
  const enabled = servers.filter((s) => s.enabled);
  const healthy = enabled.filter((s) => s.last_health === "ok").length;
  $("stat-servers").textContent = `${healthy} / ${enabled.length}`;
  $("stat-servers-sub").textContent = `${servers.length} всего · ${enabled.length} включено`;

  for (const s of servers) {
    const tr = document.createElement("tr");
    const status = s.last_health
      ? chip(s.last_health === "ok")
      : '<span class="chip chip-muted">—</span>';
    const lat = s.best_latency_ms != null ? s.best_latency_ms + "ms" : "—";
    const isBest = s.id === bestId;
    if (isBest) tr.className = "best-row";
    const bestBadge = isBest
      ? ' <span class="chip chip-star">★ Лучший</span>'
      : "";
    const enabledBadge = s.enabled
      ? '<span class="chip chip-success">да</span>'
      : '<span class="chip chip-muted">нет</span>';
    tr.innerHTML = `
      <td class="mono">${s.id}</td>
      <td class="name-cell"><b>${prettyName(s.name)}</b>${bestBadge}</td>
      <td>${escapeHtml(s.protocol || "vless")}</td>
      <td class="mono">${escapeHtml(s.address)}</td>
      <td>${s.port}</td>
      <td class="mono">${escapeHtml(s.sni || "")}</td>
      <td>${enabledBadge}</td>
      <td>${status}</td>
      <td>${lat}</td>
      <td class="ta-r">
        <div class="actions" style="justify-content:flex-end">
          ${actionIcons(s.id)}
        </div>
      </td>`;
    body.appendChild(tr);
  }
}

async function loadServers() {
  try {
    serverCache = await api("/api/servers");
  } catch (e) {
    toast("servers: " + e.message, true);
    return;
  }
  // Отрисовываем данные из БД сразу. Сетевая проверка не блокирует таблицу.
  const snapshot = serverCache.slice();
  renderServers(snapshot);
}

/* ===== Bulk check ===== */
async function runBulkCheck() {
  const btn = $("btn-bulk-check");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Проверка…";
  try {
    const results = await api("/api/servers/check", "POST", { test: true, health: true });
    const tbody = $("check-body");
    tbody.innerHTML = "";
    let okConfig = 0;
    let okHealth = 0;
    for (const r of results) {
      const cfg = r.config_ok !== undefined
        ? chip(r.config_ok, "OK", "FAIL")
        : '<span class="chip chip-muted">—</span>';
      const h = r.health_ok !== undefined
        ? chip(r.health_ok, "OK", "FAIL")
        : '<span class="chip chip-muted">—</span>';
      if (r.config_ok) okConfig++;
      if (r.health_ok) okHealth++;
      const err = r.config_error || r.health_error || "";
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="name-cell"><b>${prettyName(r.name)}</b></td>
        <td>${cfg}</td>
        <td>${h}</td>
        <td>${r.health_latency_ms != null ? r.health_latency_ms + "ms" : "—"}</td>
        <td class="mono">${escapeHtml(err || "")}</td>`;
      tbody.appendChild(tr);
    }
    $("check-modal").classList.remove("hidden");
    toast(`Проверено ${results.length}: конфиг OK ${okConfig}, health OK ${okHealth}`);
    await loadServers();
  } catch (e) {
    toast("bulk check: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

/* ===== Audit ===== */
async function loadAudit() {
  const filter = $("audit-filter") ? $("audit-filter").value : "";
  const body = $("audit-body");
  body.innerHTML = '<tr><td colspan="3" class="muted">Загрузка…</td></tr>';
  try {
    const q = filter ? "&action=" + encodeURIComponent(filter) : "";
    const rows = await api("/api/audit?limit=100" + q);
    body.innerHTML = "";
    if (!rows.length) {
      body.innerHTML = '<tr><td colspan="3" class="muted">Записей нет.</td></tr>';
      return;
    }
    for (const r of rows) {
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(r.ts.replace("T", " "))}</td>
        <td><span class="chip chip-muted">${escapeHtml(r.action)}</span></td>
        <td class="mono">${escapeHtml(r.detail || "")}</td>`;
      body.appendChild(tr);
    }
  } catch (e) {
    body.innerHTML = `<tr><td colspan="3" class="muted">${escapeHtml(e.message)}</td></tr>`;
  }
}

/* ===== Confirm dialog ===== */
let confirmResolve = null;

function showConfirm({ title = "Удалить безвозвратно", message = "", okText = "Ок", cancelText = "Отмена", danger = true } = {}) {
  $("confirm-title").textContent = title;
  $("confirm-message").textContent = message;
  const ok = $("btn-confirm-ok");
  ok.textContent = okText;
  ok.classList.toggle("btn-danger", danger);
  ok.classList.toggle("btn-primary", !danger);
  $("btn-confirm-cancel").textContent = cancelText;
  $("confirm-modal").classList.remove("hidden");
  ok.focus();
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function closeConfirm(result) {
  $("confirm-modal").classList.add("hidden");
  if (confirmResolve) { confirmResolve(result); confirmResolve = null; }
}

/* ===== Clear data ===== */
async function openClearData() {
  $("clear-data-result").textContent = "";
  $("btn-clear-data-confirm").disabled = false;
  try {
    const opts = await api("/api/admin/data-options");
    const ret = await api("/api/admin/backup-retention");
    $("clear-retention-days").value = ret.days;
    $("clear-data-sections").innerHTML = (opts.sections || []).map((s) => `
      <label class="clear-section">
        <input type="checkbox" data-section="${s.name}">
        <span>
          <span class="cs-title">${escapeHtml(s.label)}</span><br>
          <span class="cs-desc">${escapeHtml(s.desc || "")}</span>
        </span>
        <span class="cs-tag ${s.danger ? "cs-danger" : "cs-safe"}">${s.danger ? "опасно" : "безопасно"}</span>
      </label>`).join("");
    $("clear-data-modal").classList.remove("hidden");
  } catch (e) {
    toast("clear-data: " + e.message, true);
  }
}

function closeClearData() { $("clear-data-modal").classList.add("hidden"); }

function clearSectionLabel(name) {
  const lbl = document.querySelector(`#clear-data-sections input[data-section="${name}"]`);
  return lbl ? lbl.closest(".clear-section").querySelector(".cs-title").textContent : name;
}

async function submitClearData() {
  const sections = Array.from(document.querySelectorAll("#clear-data-sections input:checked"))
    .map((i) => i.dataset.section);
  if (!sections.length) { toast("Выберите хотя бы один раздел", true); return; }
  const names = sections.map(clearSectionLabel).join(", ");
  const go = await showConfirm({
    title: "Удалить безвозвратно",
    message: names + "\n\nПродолжить?",
    okText: "Ок",
    cancelText: "Отмена",
    danger: true,
  });
  if (!go) return;
  const btn = $("btn-clear-data-confirm");
  btn.disabled = true;
  $("clear-data-result").textContent = "Удаляем…";
  try {
    const r = await api("/api/admin/clear-data", "POST", { sections });
    const lines = Object.entries(r.results || {}).map(([k, v]) => {
      const name = clearSectionLabel(k);
      if (v.skipped) return `${name}: пропущено (${v.skipped})`;
      if (!v.ok) return `${name}: ошибка — ${v.error || "?"}`;
      const extra = [v.removed !== undefined ? `файлов ${v.removed}` : null,
                     v.servers !== undefined ? `серверов ${v.servers}` : null,
                     v.users !== undefined ? `пользователей ${v.users}` : null,
                     v.peers !== undefined ? `пиров ${v.peers}` : null]
        .filter(Boolean).join(", ");
      return `${name}: удалено${extra ? " (" + extra + ")" : ""}`;
    });
    $("clear-data-result").textContent = lines.join("\n");
    toast("Данные удалены");
    await loadAudit();
  } catch (e) {
    $("clear-data-result").textContent = e.message;
    toast("clear-data: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function saveRetention() {
  const days = parseInt($("clear-retention-days").value, 10);
  if (!days || days < 1 || days > 365) { toast("Дней: 1..365", true); return; }
  try {
    await api("/api/admin/backup-retention", "POST", { days });
    toast(`Хранение бэкапов: ${days} дн.`);
  } catch (e) { toast("retention: " + e.message, true); }
}

async function applyRetention() {
  try {
    const r = await api("/api/admin/backup-retention/apply", "POST");
    $("clear-data-result").textContent = `Удалено бэкапов старше ${r.days} дн.: ${r.removed || 0}`;
    toast(`Удалено старых бэкапов: ${r.removed || 0}`);
  } catch (e) { toast("retention: " + e.message, true); }
}

/* ===== Alerts ===== */
async function loadAlerts() {
  try {
    const cfg = await api("/api/alerts/config");
    $("al-enabled").checked = cfg.enabled;
    $("al-autorestart").checked = cfg.auto_restart;
    $("al-interval").value = cfg.interval;
    $("al-disk").value = cfg.disk_threshold;
    $("al-router-cpu").value = cfg.router_cpu_threshold;
    const ips = [...new Set([...(cfg.source_ips || []), cfg.source_ip].filter(Boolean))];
    $("al-source-ip").innerHTML = '<option value="">Автоматически</option>' + ips.map(ip => `<option value="${escapeHtml(ip)}">${escapeHtml(ip)}</option>`).join("");
    $("al-source-ip").value = cfg.source_ip || "";
    $("al-tg-token").value = cfg.tg_token || "";
    $("al-tg-chat").value = cfg.tg_chat || "";
    $("al-status").textContent = cfg.enabled ? "Включён" : "Выключен";
    $("al-status").className = "chip " + (cfg.enabled ? "chip-success" : "chip-muted");
  } catch (e) {
    toast("load alerts: " + e.message, true);
  }
}

async function saveAlerts(e) {
  e.preventDefault();
  const btn = $("btn-al-save");
  btn.disabled = true;
  try {
    await api("/api/alerts/config", "POST", {
      enabled: $("al-enabled").checked,
      auto_restart: $("al-autorestart").checked,
      interval: +$("al-interval").value || 60,
      disk_threshold: +$("al-disk").value || 90,
      router_cpu_threshold: +$("al-router-cpu").value || 90,
      source_ip: $("al-source-ip").value,
      tg_token: $("al-tg-token").value.trim(),
      tg_chat: $("al-tg-chat").value.trim(),
    });
    toast("Настройки алертов сохранены");
    await loadAlerts();
  } catch (e2) {
    toast("save alerts: " + e2.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function testAlerts() {
  try {
    await api("/api/alerts/test", "POST");
    toast("Тест отправлен в Telegram");
  } catch (e) {
    toast("test alert: " + e.message, true);
  }
}

async function runAlertsCheck() {
  const box = $("al-check-result");
  box.textContent = "Проверка…";
  try {
    const r = await api("/api/alerts/check", "POST");
    box.innerHTML = (r.checks || []).map((c) => escapeHtml(c)).join("<br>");
  } catch (e) {
    box.textContent = "check: " + e.message;
  }
}

async function checkTgBot() {
  const box = $("al-tg-result");
  const btn = $("btn-al-tg-status");
  btn.disabled = true;
  box.textContent = "Проверка бота…";
  try {
    const r = await api("/api/alerts/tg-status");
    if (!r.configured) {
      box.textContent = "Telegram не настроен: сохраните token бота.";
      return;
    }
    if (r.ok) {
      box.textContent = `Бот OK (${r.bot_username}) · получатель ${r.chat_configured ? `настроен (${r.chat_masked})` : "НЕ настроен"}`;
    } else {
      box.textContent = "Бот не отвечает: " + (r.error || "ошибка токена");
    }
  } catch (e) {
    box.textContent = "tg-status: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function resolveTgChat() {
  const box = $("al-tg-result");
  const btn = $("btn-al-tg-resolve");
  btn.disabled = true;
  box.textContent = "Спрашиваем чаты…";
  try {
    const r = await api("/api/alerts/tg-resolve", "POST");
    const chats = r.chats || [];
    if (!chats.length) {
      box.textContent = "Нет чатов. Напишите боту в Telegram любое сообщение и повторите.";
      return;
    }
    box.innerHTML = chats.map((c) =>
      `<span style="cursor:pointer;color:var(--primary);" data-fill-chat="${escapeHtml(c.chat_id)}">${escapeHtml(c.chat_id)} — ${escapeHtml(c.name || c.type)}</span>`
    ).join("<br>") + "<br><span class='muted' style='font-size:12px'>Кликните ID — подставится в поле получателя.</span>";
  } catch (e) {
    box.textContent = "tg-resolve: " + e.message;
  } finally {
    btn.disabled = false;
  }
}

/* ===== Address lists ===== */
let alResolvedText = "";
let alResolvedGroups = null;
let alBlobUrl = "";

function alParseGroups(text) {
  const groups = [];
  let cur = null;
  for (const raw of text.split("\n")) {
    const line = raw.trimEnd();
    const m = line.match(/^#\s*=+\s*\d+\.\s*(.+?)\s*=+$/);
    if (m) {
      cur = { title: m[1], lines: [], count: 0 };
      groups.push(cur);
      continue;
    }
    if (!cur) continue;
    if (/^add\s/.test(line)) { cur.count++; }
    cur.lines.push(line);
  }
  return groups;
}

function alCopy(text, el) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(() => {
      if (el) { el.textContent = "Скопировано ✓"; setTimeout(() => (el.textContent = "Копировать"), 1500); }
    });
  }
}

function alCountBadge(g) {
  if (g.count === undefined) return "";
  if (g.resolved !== undefined) {
    return `<span class="chip chip-success">${g.resolved} IP</span>` +
      (g.failed ? `<span class="chip chip-warning">${g.failed} не резолв.</span>` : "");
  }
  return `<span class="chip chip-muted">${g.count} записей</span>`;
}

async function loadAddressLists() {
  const box = $("al-groups");
  box.textContent = "Загрузка…";
  try {
    let text = alResolvedText;
    let groups = alResolvedGroups;
    if (!text) {
      const resp = await fetch("/static/mikrotik-vpn-lists.rsc", { cache: "no-store" });
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      text = await resp.text();
      groups = alParseGroups(text);
    }
    if (!groups || !groups.length) throw new Error("В файле не найдены адрес-листы");
    box.innerHTML = groups.map((g, i) => {
      const linesText = Array.isArray(g.lines) ? g.lines.join("\n") : g.lines;
      return `
      <div class="al-group">
        <div class="al-group-head">
          <span class="al-group-idx">${i + 1}</span>
          <h3 class="al-group-title">${escapeHtml(g.title)}</h3>
          ${alCountBadge(g)}
          <button class="btn btn-ghost btn-sm al-copy" data-idx="${i}" type="button">Копировать</button>
        </div>
        <pre class="al-group-code">${escapeHtml(linesText)}</pre>
      </div>`;
    }).join("");
    box.querySelectorAll(".al-copy").forEach((btn) => {
      btn.addEventListener("click", () => {
        const lines = groups[+btn.dataset.idx].lines;
        alCopy(Array.isArray(lines) ? lines.join("\n") : lines, btn);
      });
    });
    $("btn-al-copy-all").onclick = () => alCopy(text);
  } catch (e) {
    box.textContent = "Ошибка загрузки: " + e.message;
  }
}

async function resolveAddressLists() {
  const btn = $("btn-al-resolve");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Резолвим…";
  try {
    const r = await api("/api/addresslists/resolve", "POST");
    alResolvedGroups = r.groups.map((g) => ({
      title: g.title,
      count: g.count,
      resolved: g.resolved,
      failed: g.failed,
      lines: g.entries.map((e) => {
        const ips = e.ips || [];
        if (ips.length) {
          return ips.map((ip) => `add list=${e.list} comment="${e.comment}" address=${ip} disabled=${e.disabled ? "yes" : "no"}`).join("\n");
        }
        return `add list=${e.list} comment="${e.comment}" address=${e.address} disabled=${e.disabled ? "yes" : "no"}`;
      }).join("\n").replace(/^/, "/ip firewall address-list\n"),
    }));
    alResolvedText = r.rsc;
    const blob = new Blob([r.rsc], { type: "text/plain;charset=utf-8" });
    if (alBlobUrl) URL.revokeObjectURL(alBlobUrl);
    alBlobUrl = URL.createObjectURL(blob);
    $("btn-al-download").href = alBlobUrl;
    $("btn-al-download").setAttribute("download", "mikrotik-vpn-lists-ip.rsc");
    toast(`Резолв готов: ${r.groups.length} групп, IP-записей больше`);
    await loadAddressLists();
  } catch (e) {
    toast("resolve: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function applyAddressLists() {
  const btn = $("btn-al-apply");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Считаем…";
  try {
    const p = await api("/api/addresslists/preview", "POST");
    if (!p.ok) throw new Error(p.error || "preview failed");
    const per = (p.lists || []).map((l) =>
      `${escapeHtml(l.list)}: +${l.add}/−${l.remove}`
    ).join(" · ") || "—";
    $("al-preview-summary").textContent = `Добавить: ${p.add} · Удалить: ${p.remove}`;
    $("al-preview-lists").innerHTML = "По листам: " + per;
    $("al-preview-add-title").textContent = `Добавится (${p.add})`;
    $("al-preview-remove-title").textContent = `Удалится (${p.remove})`;
    $("al-preview-adds").textContent = (p.adds || []).length
      ? (p.adds || []).map((a) => `[${a.list}] ${a.address}${a.comment ? "  # " + a.comment : ""}`).join("\n")
      : "—";
    $("al-preview-removes").textContent = (p.removes || []).length
      ? (p.removes || []).map((r) => `[${r.list}] ${r.address}${r.comment ? "  # " + r.comment : ""}`).join("\n")
      : "—";
    $("al-preview-modal").classList.remove("hidden");
  } catch (e) {
    toast("preview: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function doApplyAddressLists() {
  const btn = $("btn-al-preview-apply");
  btn.disabled = true;
  try {
    const r = await api("/api/addresslists/apply", "POST");
    $("al-preview-modal").classList.add("hidden");
    toast(r.message || "Применено на MikroTik");
    await loadAlMtEntries();
    await loadMikrotikStatus();
  } catch (e) {
    toast("apply: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ===== Авто-обновление листов ===== */
async function loadAutoSync() {
  try {
    const cfg = await api("/api/addresslists/auto-sync");
    $("al-auto-enabled").checked = !!cfg.enabled;
    $("al-auto-time").value = cfg.time || "04:00";
    $("al-auto-last").textContent = cfg.last_run ? cfg.last_run : "—";
    const st = $("al-auto-status");
    st.textContent = cfg.enabled ? "включено" : "выключено";
    st.className = "chip " + (cfg.enabled ? "chip-success" : "chip-muted");
    try {
      const js = await api("/api/addresslists/auto-sync/status");
      if (js.running) {
        st.textContent = "синк идёт";
        st.className = "chip chip-warning";
      }
    } catch (e) { /* status unavailable — не критично */ }
  } catch (e) {
    toast("auto-sync: " + e.message, true);
  }
}

async function saveAutoSync() {
  const btn = $("btn-al-auto-save");
  btn.disabled = true;
  try {
    const r = await api("/api/addresslists/auto-sync", "POST", {
      enabled: $("al-auto-enabled").checked,
      time: $("al-auto-time").value || "04:00",
    });
    toast("Настройки авто-обновления сохранены");
    $("al-auto-result").textContent = "";
    await loadAutoSync();
  } catch (e) {
    toast("auto-sync save: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function runAutoSync() {
  const btn = $("btn-al-auto-run");
  const box = $("al-auto-result");
  const bar = $("al-auto-progress");
  const wrap = $("al-auto-progress-wrap");
  btn.disabled = true;
  box.textContent = "Синхронизируем…";
  wrap.style.display = "block";
  bar.style.width = "0%";
  try {
    await api("/api/addresslists/auto-sync/run", "POST");
    const phaseLabel = { resolve: "резолв доменов", push: "применение", done: "финализация", idle: "готово" };
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      const st = await api("/api/addresslists/auto-sync/status");
      const pct = Math.round((st.progress || 0) * 100);
      bar.style.width = pct + "%";
      if (st.running) {
        const ph = phaseLabel[st.phase] || st.phase;
        box.textContent = `${ph} · удалено ${st.removed} · добавлено ${st.added} · ${pct}%`;
        continue;
      }
      bar.style.width = "100%";
      box.textContent = st.message || "Готово";
      if (st.ok === false) {
        toast("auto-sync: " + (st.message || "failed"), true);
      } else {
        toast("Авто-синк: " + (st.message || "готово"));
      }
      break;
    }
    await loadAutoSync();
    await loadAlMtEntries();
  } catch (e) {
    box.textContent = e.message;
    toast("auto-sync run: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ===== Клиенты через VPN ===== */
async function loadClientVpn() {
  const body = $("cv-body");
  body.innerHTML = '<tr><td colspan="3" class="muted">Загрузка…</td></tr>';
  try {
    const r = await api("/api/mikrotik/client-vpn");
    const items = r.items || [];
    if (!r.ok) {
      body.innerHTML = `<tr><td colspan="3" class="muted">${escapeHtml(r.error || "роутер недоступен")}</td></tr>`;
      return;
    }
    if (!items.length) {
      body.innerHTML = '<tr><td colspan="3" class="muted">Клиентов через VPN пока нет. Добавьте IP выше.</td></tr>';
      return;
    }
    body.innerHTML = items.map((it) => {
      const on = it.router_enabled;
      const st = !it.on_router
        ? chip(false, "в VPN", "нет на роутере")
        : on
          ? chip(true, "в VPN")
          : chip(false, "в VPN", "выключен");
      return `
      <tr>
        <td class="mono"><b>${escapeHtml(it.ip)}</b></td>
        <td>${st}</td>
        <td class="ta-r">
          <button class="icon-btn-sm" data-cvact="toggle" data-ip="${escapeHtml(it.ip)}" data-on="${it.router_enabled ? "1" : "0"}" title="${it.router_enabled ? "Выключить" : "Включить"}">${it.router_enabled ? ICONS.pause : ICONS.play}</button>
          <button class="icon-btn-sm ic-del" data-cvact="del" data-ip="${escapeHtml(it.ip)}" title="Удалить">${ICONS.trash}</button>
        </td>
      </tr>`;
    }).join("");
  } catch (e) {
    body.innerHTML = `<tr><td colspan="3" class="muted">${escapeHtml(e.message)}</td></tr>`;
  }
}

async function addClientVpn(e) {
  e.preventDefault();
  const ip = $("cv-ip").value.trim();
  if (!ip) return;
  try {
    const r = await api("/api/mikrotik/client-vpn", "POST", { ip, enabled: true });
    $("cv-ip").value = "";
    $("cv-result").textContent = r.message || "";
    toast(r.message || "Добавлено");
    await loadClientVpn();
  } catch (e2) {
    toast("client-vpn add: " + e2.message, true);
  }
}

async function toggleClientVpn(ip, on) {
  try {
    const r = await api("/api/mikrotik/client-vpn", "POST", { ip, enabled: !on });
    toast(r.message || "Обновлено");
    await loadClientVpn();
  } catch (e) {
    toast("client-vpn toggle: " + e.message, true);
  }
}

async function delClientVpn(ip) {
  if (!await showConfirm({ title: "Убрать клиента", message: "Убрать клиента " + ip + " из VPN?" })) return;
  try {
    const r = await api("/api/mikrotik/client-vpn/" + encodeURIComponent(ip), "DELETE");
    toast(r.message || "Удалено");
    await loadClientVpn();
  } catch (e) {
    toast("client-vpn del: " + e.message, true);
  }
}

/* ===== Бэкапы .rsc ===== */
async function openAlBackups() {
  $("al-backups-modal").classList.remove("hidden");
  const body = $("al-backups-body");
  body.innerHTML = '<tr><td colspan="4" class="muted">Загрузка…</td></tr>';
  try {
    const r = await api("/api/addresslists/backups");
    const bs = r || [];
    if (!bs.length) {
      body.innerHTML = '<tr><td colspan="4" class="muted">Бэкапов пока нет. Они создаются при каждом сохранении .rsc.</td></tr>';
      return;
    }
    body.innerHTML = bs.map((b) => `
      <tr>
        <td class="mono">${escapeHtml(b.name)}</td>
        <td>${fmtSize(b.size)}</td>
        <td class="mono">${escapeHtml((b.mtime || "").replace("T", " "))}</td>
        <td>
          <button class="btn btn-ghost btn-sm" data-backup="view" data-name="${escapeHtml(b.name)}">Просмотр</button>
          <button class="btn btn-ghost btn-sm" data-backup="restore" data-name="${escapeHtml(b.name)}">Восстановить</button>
        </td>
      </tr>`).join("");
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="muted">Ошибка: ' + escapeHtml(e.message) + "</td></tr>";
  }
}

async function viewAlBackup(name) {
  try {
    const r = await api("/api/addresslists/backups/" + encodeURIComponent(name));
    openAlEditor(r.text || "");
    $("al-backups-modal").classList.add("hidden");
  } catch (e) {
    toast("backup view: " + e.message, true);
  }
}

async function restoreAlBackup(name) {
  if (!await showConfirm({ title: "Восстановить из бэкапа", message: `Восстановить .rsc из бэкапа ${name}?\n\nТекущий файл будет сохранён как новый бэкап.`, okText: "Восстановить" })) return;
  try {
    const r = await api("/api/addresslists/backups/" + encodeURIComponent(name) + "/restore", "POST");
    toast(r.message || "Восстановлено");
    await loadAddressLists();
  } catch (e) {
    toast("backup restore: " + e.message, true);
  }
}

function fmtSize(n) {
  if (!n && n !== 0) return "—";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / (1024 * 1024)).toFixed(1) + " MB";
}

/* ===== Онлайн-редактирование записей на MikroTik ===== */
let alMtList = "";
let alMtEntries = [];
let alMtFilter = "";
let alMtPage = 0;
const AL_MT_PAGE_SIZE = 50;

function alMtFiltered() {
  const q = alMtFilter.trim().toLowerCase();
  if (!q) return alMtEntries;
  return alMtEntries.filter((e) =>
    (e.address || "").toLowerCase().includes(q) ||
    (e.comment || "").toLowerCase().includes(q));
}

function renderAlMtTable() {
  const body = $("al-mt-body");
  const info = $("al-mt-info");
  if (!body) return;
  const filtered = alMtFiltered();
  const pages = Math.max(1, Math.ceil(filtered.length / AL_MT_PAGE_SIZE));
  if (alMtPage >= pages) alMtPage = pages - 1;
  const slice = filtered.slice(alMtPage * AL_MT_PAGE_SIZE, (alMtPage + 1) * AL_MT_PAGE_SIZE);
  body.innerHTML = "";
  if (!slice.length) {
    body.innerHTML = `<tr><td colspan="4" class="muted">Нет записей${alMtFilter ? " по фильтру" : " в листе " + escapeHtml(alMtList)}</td></tr>`;
  }
  for (const e of slice) {
    const tr = document.createElement("tr");
    const id = encodeURIComponent(e[".id"] || "");
    const off = e.disabled === "true";
    const dynamic = String(e.dynamic) === "true";
    const act = dynamic
      ? '<span class="muted" style="font-size:12px">только чтение</span>'
      : `<button class="btn btn-ghost btn-sm" data-almt="comment" data-id="${id}" title="Сменить комментарий">Ред.</button>
         <button class="btn btn-ghost btn-sm" data-almt="toggle" data-id="${id}" data-off="${off ? 1 : 0}">${off ? "Вкл" : "Выкл"}</button>
         <button class="btn btn-ghost btn-sm" data-almt="del" data-id="${id}">Удалить</button>`;
    tr.innerHTML = `
      <td class="mono">${escapeHtml(e.address || "")}</td>
      <td>${escapeHtml(e.comment || "")} ${dynamic ? '<span class="chip chip-muted">dynamic</span>' : ""}</td>
      <td>${chip(!off, "вкл", "выкл")}</td>
      <td>${act}</td>`;
    body.appendChild(tr);
  }
  info.innerHTML = `Лист <b>${escapeHtml(alMtList)}</b>: ${alMtEntries.length} записей` +
    (alMtFilter ? `, по фильтру ${filtered.length}` : "") +
    ` · стр. ${alMtPage + 1}/${pages}`;
  const prev = $("btn-al-mt-prev"), next = $("btn-al-mt-next");
  if (prev) prev.disabled = alMtPage <= 0;
  if (next) next.disabled = alMtPage >= pages - 1;
}

async function loadAlMtLists() {
  try {
    const sel = $("al-mt-list");
    const groups = await api("/api/addresslists/groups");
    const lists = [...new Set(groups.flatMap(g => g.entries.map(e => e.list)))];
    if (!lists.length) { sel.innerHTML = '<option value="">Нет настроенных списков</option>'; $("al-mt-body").innerHTML = ''; return; }
    if (!lists.includes(alMtList)) alMtList = lists[0];
    sel.innerHTML = lists.map((l) =>
      `<option value="${escapeHtml(l)}" ${l === alMtList ? "selected" : ""}>${escapeHtml(l)}</option>`
    ).join("");
    await loadAlMtEntries();
  } catch (e) {
    $("al-mt-info").textContent = "Ошибка: " + e.message;
    $("al-mt-body").innerHTML = "";
  }
}

async function loadAlMtEntries() {
  const body = $("al-mt-body");
  if (!body) return;
  body.innerHTML = '<tr><td colspan="4" class="muted">Загрузка…</td></tr>';
  try {
    const r = await api("/api/mikrotik/address-list?list=" + encodeURIComponent(alMtList));
    alMtEntries = r.entries || [];
    alMtPage = 0;
    renderAlMtTable();
  } catch (e) {
    body.innerHTML = '<tr><td colspan="4" class="muted">Ошибка: ' + escapeHtml(e.message) + "</td></tr>";
  }
}

async function addAlMtEntry() {
  const addr = $("al-mt-address").value.trim();
  const comment = $("al-mt-comment").value.trim();
  if (!addr) {
    toast("Укажите адрес", true);
    return;
  }
  try {
    await api("/api/mikrotik/address-list", "POST", { list: alMtList, address: addr, comment });
    toast("Добавлено: " + addr);
    $("al-mt-address").value = "";
    $("al-mt-comment").value = "";
    await loadAlMtEntries();
  } catch (e) {
    toast("add: " + e.message, true);
  }
}

async function alMtAction(btn) {
  const id = btn.dataset.id;
  if (btn.dataset.almt === "del") {
    if (!await showConfirm({ title: "Удалить запись", message: "Удалить запись с MikroTik?" })) return;
    try {
      await api("/api/mikrotik/address-list/" + id, "DELETE");
      toast("Запись удалена");
      await loadAlMtEntries();
    } catch (e2) {
      toast("del: " + e2.message, true);
    }
  } else if (btn.dataset.almt === "toggle") {
    const newOff = btn.dataset.off !== "1";
    try {
      await api("/api/mikrotik/address-list/" + id, "PATCH", { disabled: newOff });
      toast(newOff ? "Запись отключена" : "Запись включена");
      await loadAlMtEntries();
    } catch (e2) {
      toast("toggle: " + e2.message, true);
    }
  } else if (btn.dataset.almt === "comment") {
    const cur = (alMtEntries.find((e) => encodeURIComponent(e[".id"] || "") === id) || {}).comment || "";
    const nc = prompt("Комментарий записи:", cur);
    if (nc === null) return;
    try {
      await api("/api/mikrotik/address-list/" + id, "PATCH", { comment: nc });
      toast("Комментарий обновлён");
      await loadAlMtEntries();
    } catch (e2) {
      toast("comment: " + e2.message, true);
    }
  }
}

async function openAlMtImport() {
  $("al-mt-io-title").textContent = "Импорт записей";
  $("al-mt-io-text").value = "";
  $("al-mt-io-text").readOnly = false;
  $("btn-al-mt-io-ok").classList.remove("hidden");
  $("btn-al-mt-io-copy").classList.add("hidden");
  $("al-mt-io-modal").classList.remove("hidden");
  $("al-mt-io-text").focus();
}

async function doAlMtImport() {
  const btn = $("btn-al-mt-io-ok");
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/address-list/import", "POST", { text: $("al-mt-io-text").value });
    toast(r.message || "Импортировано");
    $("al-mt-io-modal").classList.add("hidden");
    await loadAlMtEntries();
  } catch (e) {
    toast("import: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function openAlMtExport() {
  const btn = $("btn-al-mt-export");
  const orig = btn.innerHTML;
  btn.disabled = true;
  try {
    const r = await api("/api/mikrotik/address-list/export?list=" + encodeURIComponent(alMtList));
    $("al-mt-io-title").textContent = "Экспорт листа " + alMtList;
    $("al-mt-io-text").value = r.text || "";
    $("al-mt-io-text").readOnly = true;
    $("btn-al-mt-io-ok").classList.add("hidden");
    $("btn-al-mt-io-copy").classList.remove("hidden");
    $("al-mt-io-modal").classList.remove("hidden");
  } catch (e) {
    toast("export: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function openAlEditor(text) {
  try {
    if (text === undefined) {
      const r = await api("/api/addresslists/raw");
      text = r.text;
    }
    $("al-edit-text").value = text;
    $("al-edit-modal").classList.remove("hidden");
  } catch (e) {
    toast("load rsc: " + e.message, true);
  }
}

async function saveAlEditor() {
  const btn = $("btn-al-edit-save");
  btn.disabled = true;
  try {
    await api("/api/addresslists/raw", "POST", { text: $("al-edit-text").value });
    $("al-edit-modal").classList.add("hidden");
    alResolvedText = "";
    alResolvedGroups = null;
    $("btn-al-download").href = "/static/mikrotik-vpn-lists.rsc";
    $("btn-al-download").setAttribute("download", "");
    toast(".rsc сохранён");
    await loadAddressLists();
  } catch (e) {
    toast("save rsc: " + e.message, true);
  } finally {
    btn.disabled = false;
  }
}

async function openAlSync() {
  const btn = $("btn-al-sync");
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.textContent = "Генерируем…";
  try {
    const r = await api("/api/addresslists/sync-script", "POST");
    $("al-sync-text").value = r.script;
    $("al-sync-modal").classList.remove("hidden");
  } catch (e) {
    toast("sync script: " + e.message, true);
  } finally {
    btn.disabled = false;
    btn.innerHTML = orig;
  }
}

async function copyAlSync() {
  try {
    await navigator.clipboard.writeText($("al-sync-text").value);
    toast("Скрипт синхронизации скопирован");
  } catch (e) {
    $("al-sync-text").select();
    document.execCommand("copy");
    toast("Скрипт скопирован");
  }
}

/* ===== Server modal ===== */
function openModal(fill) {
  const f = (id, v) => { const el = $(id); if (el) el.value = v ?? ""; };
  f("f-id", fill ? fill.id : "");
  f("f-name", fill ? fill.name : "");
  f("f-address", fill ? fill.address : "");
  f("f-port", fill ? fill.port : 443);
  f("f-priority", fill ? fill.priority : 100);
  f("f-uuid", fill ? fill.uuid : "");
  f("f-flow", fill ? fill.flow : "xtls-rprx-vision");
  f("f-protocol", fill ? fill.protocol : "vless");
  f("f-network", fill ? fill.network : "tcp");
  f("f-security", fill ? fill.security : "reality");
  f("f-fingerprint", fill ? fill.fingerprint : "chrome");
  f("f-sni", fill ? fill.sni : "");
  f("f-alpn", fill ? fill.alpn : "h2,http/1.1");
  f("f-pbk", fill ? fill.reality_public_key : "");
  f("f-sid", fill ? fill.reality_short_id : "");
  f("f-path", fill ? fill.path : "");
  f("f-mode", fill ? fill.mode : "auto");
  f("f-service-name", fill ? fill.service_name : "");
  f("f-host", fill ? fill.host : "");
  $("f-enabled").checked = fill ? fill.enabled : true;
  $("modal-title").textContent = fill ? "Редактирование сервера" : "Новый сервер";
  $("modal").classList.remove("hidden");
}

async function saveServerForm(e) {
  e.preventDefault();
  const payload = {
    name: $("f-name").value,
    address: $("f-address").value,
    port: parseInt($("f-port").value, 10),
    uuid: $("f-uuid").value,
    protocol: $("f-protocol").value,
    flow: $("f-flow").value,
    network: $("f-network").value,
    security: $("f-security").value,
    sni: $("f-sni").value,
    reality_public_key: $("f-pbk").value,
    reality_short_id: $("f-sid").value,
    fingerprint: $("f-fingerprint").value,
    path: $("f-path").value,
    mode: $("f-mode").value,
    service_name: $("f-service-name").value,
    alpn: $("f-alpn").value,
    host: $("f-host").value,
    enabled: $("f-enabled").checked,
    priority: parseInt($("f-priority").value, 10),
  };
  const id = $("f-id").value;
  try {
    if (id) await api("/api/servers/" + id, "PUT", payload);
    else await api("/api/servers", "POST", payload);
    $("modal").classList.add("hidden");
    toast("Сохранено");
    await loadServers();
  } catch (e2) {
    toast("ошибка: " + e2.message, true);
  }
}

/* ===== Auth ===== */
function showLogin() {
  clearTimeout(updateTimer);
  token = "";
  localStorage.removeItem("xgw_token");
  $("main-view").classList.add("hidden");
  $("login-view").classList.remove("hidden");
}

async function showMain() {
  $("login-view").classList.add("hidden");
  $("main-view").classList.remove("hidden");
  await Promise.all([loadStatus(), loadServers(), loadAudit(), loadTraffic(), loadUpdateStatus()]);
  startTrafficPoll();
}

/* ===== Events ===== */
$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    const r = await api("/api/auth/login", "POST", {
      username: $("login-username").value,
      password: $("login-password").value,
    });
    token = r.token;
    localStorage.setItem("xgw_token", token);
    $("login-error").textContent = "";
    await showMain();
  } catch (e2) {
    $("login-error").textContent = e2.message;
  }
});

$("btn-logout").addEventListener("click", () => {
  api("/api/auth/logout", "POST").catch(() => {});
  showLogin();
});

$("password-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const currentPassword = $("password-current").value;
  const newPassword = $("password-new").value;
  const confirmPassword = $("password-confirm").value;
  if (newPassword.length < 8) {
    toast("Новый пароль должен содержать минимум 8 символов", true);
    return;
  }
  if (newPassword !== confirmPassword) {
    toast("Подтверждение пароля не совпадает", true);
    return;
  }
  try {
    await api("/api/auth/password", "POST", {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    });
    $("password-form").reset();
    showLogin();
    $("login-password").value = "";
    $("login-password").focus();
    toast("Пароль изменён. Войдите с новым паролем");
  } catch (e2) {
    toast(e2.message, true);
  }
});

document.querySelectorAll(".nav-item").forEach((b) =>
  b.addEventListener("click", () => switchView(b.dataset.view))
);
$("btn-nav-toggle").addEventListener("click", () => {
  $("side-nav").classList.add("open");
  $("nav-backdrop").classList.add("show");
});
$("nav-backdrop").addEventListener("click", closeNav);

$("btn-refresh-status").addEventListener("click", () => Promise.all([loadStatus(), loadServers(), loadTraffic()]));
$("btn-switch-best").addEventListener("click", async () => {
  switchView("interfaces");
});
$("btn-run-failover").addEventListener("click", async () => {
  try {
    const r = await api("/api/servers/failover/run", "POST");
    toast(r.message);
    await Promise.all([loadStatus(), loadServers(), loadAudit()]);
  } catch (e) {
    toast("failover: " + e.message, true);
  }
});

$("btn-add").addEventListener("click", () => openModal(null));

$("btn-wg-refresh").addEventListener("click", () => { loadWg(); loadTraffic(); });
$("btn-wg-apply").addEventListener("click", async () => {
  try {
    const r = await api("/api/wg/restart", "POST");
    toast("wg: " + r.message);
    await loadWg();
  } catch (e) {
    toast("wg restart: " + e.message, true);
  }
});
$("btn-wg-add-peer").addEventListener("click", () => openWgPeerModal(null));
$("btn-wg-peer-cancel").addEventListener("click", () => $("wg-peer-modal").classList.add("hidden"));
$("wg-peer-form").addEventListener("submit", saveWgPeer);
$("btn-wg-edit-iface").addEventListener("click", async () => {
  try {
    openWgIfaceModal(await api("/api/wg/status"));
  } catch (e) {
    toast("wg: " + e.message, true);
  }
});
$("btn-wg-iface-cancel").addEventListener("click", () => $("wg-iface-modal").classList.add("hidden"));
$("wg-iface-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/wg/interface", "POST", {
      address: $("wg-address").value.trim(),
      listen_port: parseInt($("wg-port").value, 10) || undefined,
    });
    $("wg-iface-modal").classList.add("hidden");
    toast("Интерфейс сохранён");
    await loadWg();
  } catch (e2) {
    toast("wg iface: " + e2.message, true);
  }
});
$("wg-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-wgact]");
  if (!btn) return;
  const pk = btn.dataset.pk;
  if (btn.dataset.wgact === "edit") {
    const st = await api("/api/wg/status");
    openWgPeerModal((st.peers || []).find((p) => p.public_key === pk));
  } else if (btn.dataset.wgact === "del") {
    if (!await showConfirm({ title: "Удалить peer", message: "Удалить WireGuard peer?\n\nДействие необратимо." })) return;
    try {
      await api("/api/wg/peer/" + encodeURIComponent(pk), "DELETE");
      toast("Peer удалён");
      await loadWg();
    } catch (e2) {
      toast("wg del: " + e2.message, true);
    }
  }
});

$("btn-import").addEventListener("click", () => $("import-modal").classList.remove("hidden"));
$("btn-import-cancel").addEventListener("click", () => $("import-modal").classList.add("hidden"));
$("btn-modal-cancel").addEventListener("click", () => $("modal").classList.add("hidden"));
$("btn-bulk-check").addEventListener("click", runBulkCheck);
$("btn-check-close").addEventListener("click", () => $("check-modal").classList.add("hidden"));

$("btn-import-confirm").addEventListener("click", async () => {
  const raw = $("import-url").value.trim();
  if (!raw) return;
  try {
    if (/^https?:\/\//i.test(raw)) {
      const r = await api("/api/servers/import-subscription", "POST", {
        url: raw,
        skip_existing: true,
      });
      const errNote = r.created_count ? "" : " — новых нет";
      toast(`Импортировано: ${r.created_count}, пропущено: ${r.skipped_count}${errNote}`);
    } else {
      await api("/api/servers/import", "POST", { url: raw });
      toast("Импортировано");
    }
    $("import-modal").classList.add("hidden");
    $("import-url").value = "";
    await loadServers();
  } catch (e) {
    toast("import: " + e.message, true);
  }
});

$("server-form").addEventListener("submit", saveServerForm);

$("servers-body").addEventListener("click", async (e) => {
  const btn = e.target.closest("button[data-act]");
  if (!btn) return;
  const id = btn.dataset.id;
  const act = btn.dataset.act;
  try {
    if (act === "health") {
      const r = await api(`/api/servers/${id}/healthcheck`, "POST");
      toast(`health: ${r.ok ? "OK" : "FAIL"} ${r.error}`, !r.ok);
      await loadServers();
    } else if (act === "test") {
      await api(`/api/servers/${id}/test`, "POST");
      toast("config valid");
    } else if (act === "edit") {
      openModal(serverCache.find((s) => s.id == id));
    } else if (act === "del") {
      if (!await showConfirm({ title: "Удалить сервер", message: "Удалить сервер?\n\nДействие необратимо." })) return;
      await api("/api/servers/" + id, "DELETE");
      toast("Удалён");
      await loadServers();
    }
  } catch (e2) {
    toast(e2.message, true);
  }
});

/* ===== L2TP ===== */
let profileCache = [];
let profileServers = [];
let profileUsers = [];

async function loadL2tp() {
  try {
    const s = await api("/api/l2tp/status");
    const svc = s.services || {};
    const iface = s.interface || {};
    const pool = s.pool || {};
    const auth = s.auth || {};
    const summary = [
      `<span>strongSwan: ${svcBadge(svc.strongswan)}</span>`,
      `<span>xl2tpd: ${svcBadge(svc.xl2tpd)}</span>`,
      `<span>Сервер: <b class="mono">${escapeHtml(iface.local_ip || "—")}</b></span>`,
      `<span>Pool: <b class="mono">${escapeHtml(pool.start || "—")} – ${escapeHtml(pool.end || "—")}</b></span>`,
      `<span>Логин: <b>${escapeHtml(auth.username || "—")}</b></span>`,
      `<span>PSK: ${auth.psk_present ? '<span class="chip chip-success">задан</span>' : '<span class="chip chip-error">не задан</span>'}</span>`,
    ];
    $("l2tp-info").innerHTML = summary.join("");

    const body = $("l2tp-body");
    body.innerHTML = "";
    const sessions = s.sessions || [];
    renderL2tpUsers(s.users || []);
    if (!sessions.length) {
      const tr = document.createElement("tr");
      tr.innerHTML = '<td colspan="6" class="muted">Активных сессий нет</td>';
      body.appendChild(tr);
      return;
    }
    for (const p of sessions) {
      const route = profileCache.find((profile) => profile.ppp_local_ip === p.local_address);
      const routeText = route
        ? `<span class="mono">${escapeHtml(route.local_ip)}</span> → ${escapeHtml(route.server_name || "—")}`
        : '<span class="muted">не определён</span>';
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td class="mono">${escapeHtml(p.interface)}</td>
        <td>${p.state === "UP" ? chip(true, "up", "down") : escapeHtml(p.state)}</td>
        <td class="mono">${escapeHtml(p.address || "—")}</td>
        <td>${routeText}</td>
        <td class="mono">${bytesStr(p.rx_bytes)}</td>
        <td class="mono">${bytesStr(p.tx_bytes)}</td>`;
      body.appendChild(tr);
    }
  } catch (e) {
    $("l2tp-info").textContent = "l2tp: " + e.message;
  }
}

function renderL2tpUsers(users) {
  const body = $("l2tp-users-body");
  body.innerHTML = "";
  if (!users.length) {
    body.innerHTML = '<tr><td colspan="4" class="muted">Пользователей нет</td></tr>';
    return;
  }
  for (const u of users) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="mono"><b>${escapeHtml(u.username)}</b></td>
      <td class="mono">${escapeHtml(u.password)}</td>
      <td class="mono">${escapeHtml(u.peer_ip || "авто")}</td>
      <td class="ta-r">
        <button class="icon-btn-sm ic-del" data-l2tp-del="${escapeHtml(u.username)}" title="Удалить">${ICONS.trash}</button>
      </td>`;
    body.appendChild(tr);
  }
  body.querySelectorAll("[data-l2tp-del]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const u = btn.dataset.l2tpDel;
      if (!await showConfirm({ title: "Удалить пользователя", message: `Удалить пользователя ${u}?\n\nДействие необратимо.` })) return;
      try {
        const r = await api("/api/l2tp/users/" + encodeURIComponent(u), "DELETE");
        toast("Пользователь удалён");
        renderL2tpUsers(r.users);
      } catch (e2) {
        toast("l2tp del: " + e2.message, true);
      }
    });
  });
}

async function loadProfiles(users = null) {
  const body = $("profiles-body");
  try {
    const results = await Promise.all([
      api("/api/profiles"),
      api("/api/servers"),
      users ? Promise.resolve(users) : api("/api/l2tp/status").then((s) => s.users || []),
    ]);
    profileCache = results[0] || [];
    profileServers = (results[1] || []).filter((s) => s.enabled);
    profileUsers = results[2] || [];
    if (!profileCache.length) {
      body.innerHTML = '<tr><td colspan="5" class="muted">Интерфейсы ещё не настроены. Добавьте локальный IP этой ВМ.</td></tr>';
      return;
    }
    body.innerHTML = profileCache.map((p) => `
      <tr>
        <td class="mono"><b>${escapeHtml(p.local_ip)}/${p.prefix}</b><br><span class="muted">${escapeHtml(p.name)} · ${escapeHtml(p.interface)}</span></td>
        <td><span class="mono">${escapeHtml(p.username)}</span></td>
        <td><b>Основной:</b> ${escapeHtml(p.server_name || "не найден")}<br><span class="muted">Резерв: ${escapeHtml(p.backup_server_name || "не выбран")}</span><br><span class="chip ${p.on_backup ? "chip-warning" : "chip-muted"}">Сейчас: ${escapeHtml(p.active_server_name || "заблокирован")}</span></td>
        <td>${!p.enabled ? '<span class="chip chip-muted">выключен</span>' : p.health === "unknown" ? '<span class="chip chip-muted">ожидает проверки</span>' : chip(p.service === "active" && p.health === "ok", "работает", "нет связи")}<br><span class="muted">${p.checked_at ? escapeHtml(new Date(p.checked_at).toLocaleTimeString()) : "—"}</span></td>
        <td class="ta-r">
          <button class="icon-btn-sm" data-profile-edit="${p.id}" title="Изменить">${ICONS.edit || "✎"}</button>
          <button class="icon-btn-sm ic-del" data-profile-del="${p.id}" title="Удалить">${ICONS.trash}</button>
        </td>
      </tr>`).join("");
  } catch (e) {
    body.innerHTML = `<tr><td colspan="5" class="muted">profiles: ${escapeHtml(e.message)}</td></tr>`;
  }
}

function fillProfileSelects(profile = null) {
  $("profile-server").innerHTML = profileServers.map((s) =>
    `<option value="${s.id}" ${profile && Number(profile.server_id) === Number(s.id) ? "selected" : ""}>${escapeHtml(s.name)} · ${escapeHtml(s.protocol)}</option>`
  ).join("");
  $("profile-backup").innerHTML = '<option value="">Без резерва</option>' + profileServers.map((s) =>
    `<option value="${s.id}" ${profile && Number(profile.backup_server_id) === Number(s.id) ? "selected" : ""}>${escapeHtml(s.name)}</option>`
  ).join("");
  $("profile-user").innerHTML = profileUsers.map((u) =>
    `<option value="${escapeHtml(u.username)}" ${profile && profile.username === u.username ? "selected" : ""}>${escapeHtml(u.username)}${u.peer_ip ? " · " + escapeHtml(u.peer_ip) : ""}</option>`
  ).join("");
}

function openProfileModal(profile = null) {
  if (!profileServers.length || !profileUsers.length) {
    toast("Сначала добавьте VPN-сервер и отдельного L2TP-пользователя", true);
    return;
  }
  $("profile-id").value = profile ? profile.id : "";
  $("profile-modal-title").textContent = profile ? "Изменить интерфейс ВМ" : "Новый интерфейс ВМ";
  $("profile-name").value = profile ? profile.name : "";
  $("profile-local-ip").value = profile ? profile.local_ip : "";
  $("profile-prefix").value = profile ? profile.prefix : 24;
  $("profile-interface").value = profile ? profile.interface : "eth0";
  $("profile-enabled").checked = profile ? !!profile.enabled : true;
  fillProfileSelects(profile);
  $("profile-modal").classList.remove("hidden");
}

async function saveProfile(e) {
  e.preventDefault();
  const id = $("profile-id").value;
  const payload = {
    name: $("profile-name").value.trim(),
    username: $("profile-user").value,
    local_ip: $("profile-local-ip").value.trim(),
    prefix: Number($("profile-prefix").value || 24),
    interface: $("profile-interface").value.trim() || "eth0",
    server_id: Number($("profile-server").value),
    backup_server_id: Number($("profile-backup").value) || null,
    enabled: $("profile-enabled").checked,
  };
  if (!payload.name || !payload.local_ip || !payload.server_id) {
    toast("Заполните все поля интерфейса", true);
    return;
  }
  if (payload.backup_server_id === payload.server_id) {
    toast("Основной и резервный сервер должны отличаться", true);
    return;
  }
  try {
    const r = await api(id ? `/api/profiles/${id}` : "/api/profiles", id ? "PUT" : "POST", payload);
    $("profile-modal").classList.add("hidden");
    toast(r.message || "Интерфейс применён");
    await loadProfiles();
  } catch (e2) {
    toast("interface: " + e2.message, true);
  }
}

async function openL2tpModal() {
  try {
    const s = await api("/api/l2tp/status");
    const primary = profileCache.find((p) => p.primary);
    $("l2tp-listen-addr").value = s.interface?.listen_addr || primary?.local_ip || "";
    $("l2tp-local-ip").value = s.interface?.local_ip || primary?.ppp_local_ip || "10.200.2.1";
    $("l2tp-pool-start").value = s.pool?.start || primary?.pool_start || "10.200.2.100";
    $("l2tp-pool-end").value = s.pool?.end || primary?.pool_end || "10.200.2.200";
    $("l2tp-username").value = s.auth?.username || primary?.username || "";
  } catch (e) {
    toast("l2tp: " + e.message, true);
    return;
  }
  $("l2tp-password").value = "";
  $("l2tp-psk").value = "";
  $("l2tp-modal").classList.remove("hidden");
}

async function saveL2tp(e) {
  e.preventDefault();
  const payload = {
    listen_addr: $("l2tp-listen-addr").value.trim(),
    local_ip: $("l2tp-local-ip").value.trim() || "10.200.2.1",
    pool_start: $("l2tp-pool-start").value.trim(),
    pool_end: $("l2tp-pool-end").value.trim(),
    username: $("l2tp-username").value.trim(),
    password: $("l2tp-password").value.trim(),
    psk: $("l2tp-psk").value.trim(),
  };
  if (!payload.pool_start || !payload.pool_end || !payload.username || !payload.password || !payload.psk) {
    toast("Заполни все поля (пароль и PSK обязательны)", true);
    return;
  }
  try {
    await api("/api/l2tp/config", "POST", payload);
    $("l2tp-modal").classList.add("hidden");
    toast("Настройки L2TP сохранены");
    await Promise.all([loadL2tp(), loadProfiles()]);
  } catch (e2) {
    toast("l2tp: " + e2.message, true);
  }
}

$("btn-l2tp-refresh").addEventListener("click", loadL2tp);
$("btn-profile-add").addEventListener("click", () => openProfileModal());
$("btn-profile-users").addEventListener("click", () => {
  loadL2tp();
  $("l2tp-users-card").scrollIntoView({ behavior: "smooth", block: "start" });
});
$("btn-profile-cancel").addEventListener("click", () => $("profile-modal").classList.add("hidden"));
$("profile-form").addEventListener("submit", saveProfile);
$("btn-profile-apply").addEventListener("click", async () => {
  try {
    const r = await api("/api/profiles/apply", "POST");
    toast(r.message || "Интерфейсы применены");
    await loadProfiles();
  } catch (e) { toast("interfaces: " + e.message, true); }
});
$("profiles-body").addEventListener("click", async (e) => {
  const edit = e.target.closest("[data-profile-edit]");
  const del = e.target.closest("[data-profile-del]");
  if (edit) {
    const profile = profileCache.find((p) => Number(p.id) === Number(edit.dataset.profileEdit));
    if (profile) openProfileModal(profile);
    return;
  }
  if (del) {
    const profile = profileCache.find((p) => Number(p.id) === Number(del.dataset.profileDel));
    if (!profile || !await showConfirm({ title: "Удалить интерфейс", message: `Удалить интерфейс «${profile.name}» (${profile.local_ip})? Его L2TP-подключение будет остановлено.` })) return;
    try {
      const r = await api(`/api/profiles/${profile.id}`, "DELETE");
      toast(r.message || "Интерфейс удалён");
      await loadProfiles();
    } catch (e2) { toast("interface: " + e2.message, true); }
  }
});
$("btn-al-refresh").addEventListener("click", () => {
  alResolvedText = "";
  alResolvedGroups = null;
  $("btn-al-download").href = "/static/mikrotik-vpn-lists.rsc";
  loadAddressLists();
});
$("btn-al-resolve").addEventListener("click", resolveAddressLists);
$("btn-al-apply").addEventListener("click", applyAddressLists);
$("btn-al-preview-cancel").addEventListener("click", () => $("al-preview-modal").classList.add("hidden"));
$("btn-al-preview-apply").addEventListener("click", doApplyAddressLists);
$("btn-al-backups").addEventListener("click", openAlBackups);
$("btn-al-backups-close").addEventListener("click", () => $("al-backups-modal").classList.add("hidden"));
$("al-backups-body").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-backup]");
  if (!btn) return;
  const name = btn.dataset.name;
  if (btn.dataset.backup === "view") viewAlBackup(name);
  else restoreAlBackup(name);
});
$("btn-audit-refresh").addEventListener("click", loadAudit);
$("audit-filter").addEventListener("change", loadAudit);
$("btn-clear-data").addEventListener("click", openClearData);
$("btn-clear-data-cancel").addEventListener("click", closeClearData);
$("btn-clear-data-confirm").addEventListener("click", submitClearData);
$("btn-retention-save").addEventListener("click", saveRetention);
$("btn-retention-apply").addEventListener("click", applyRetention);

$("btn-confirm-ok").addEventListener("click", () => closeConfirm(true));
$("btn-confirm-cancel").addEventListener("click", () => closeConfirm(false));
document.addEventListener("keydown", (e) => {
  if ($("confirm-modal").classList.contains("hidden")) return;
  if (e.key === "Escape") { e.preventDefault(); closeConfirm(false); }
  else if (e.key === "Enter") { e.preventDefault(); closeConfirm(true); }
});
document.addEventListener("mousedown", (e) => {
  if ($("confirm-modal").classList.contains("hidden")) return;
  if (e.target.id === "confirm-modal") closeConfirm(false);
});
$("al-form").addEventListener("submit", saveAlerts);
$("btn-al-test").addEventListener("click", testAlerts);
$("btn-al-check").addEventListener("click", runAlertsCheck);
$("btn-al-edit").addEventListener("click", openAlEditor);
$("btn-al-edit-cancel").addEventListener("click", () => $("al-edit-modal").classList.add("hidden"));
$("btn-al-edit-save").addEventListener("click", saveAlEditor);
$("btn-al-sync").addEventListener("click", openAlSync);
$("btn-al-sync-copy").addEventListener("click", copyAlSync);
$("btn-al-sync-close").addEventListener("click", () => $("al-sync-modal").classList.add("hidden"));
$("btn-l2tp-restart").addEventListener("click", async () => {
  try {
    await api("/api/l2tp/restart", "POST");
    await api("/api/profiles/apply", "POST");
    toast("L2TP перезапущен");
    await Promise.all([loadL2tp(), loadProfiles()]);
  } catch (e2) {
    toast("l2tp restart: " + e2.message, true);
  }
});
$("btn-l2tp-edit").addEventListener("click", openL2tpModal);
$("btn-l2tp-cancel").addEventListener("click", () => $("l2tp-modal").classList.add("hidden"));
$("l2tp-form").addEventListener("submit", saveL2tp);

$("btn-l2tp-add-user").addEventListener("click", () => {
  $("l2tp-user-name").value = "";
  $("l2tp-user-pass").value = "";
  $("l2tp-user-modal").classList.remove("hidden");
});
$("btn-l2tp-user-cancel").addEventListener("click", () => $("l2tp-user-modal").classList.add("hidden"));
$("l2tp-user-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("l2tp-user-name").value.trim();
  const password = $("l2tp-user-pass").value.trim();
  try {
    const r = await api("/api/l2tp/users", "POST", { username, password });
    $("l2tp-user-modal").classList.add("hidden");
    toast("Пользователь добавлен");
    renderL2tpUsers(r.users);
    await loadProfiles(r.users);
  } catch (e2) {
    toast("l2tp add user: " + e2.message, true);
  }
});

$("btn-mon-refresh").addEventListener("click", loadMonitor);
$("btn-mon-servers").addEventListener("click", loadMonitorServers);
$("btn-mon-check").addEventListener("click", loadTunnelCheck);
$("btn-traffic-refresh").addEventListener("click", loadTrafficChart);
$("mt-form").addEventListener("submit", saveMikrotik);
$("btn-mt-test").addEventListener("click", testMikrotik);
$("btn-mt-refresh").addEventListener("click", loadMikrotik);
$("btn-mt-mode").addEventListener("click", toggleTunnelMode);
$("btn-rb-save").addEventListener("click", saveRouterBackup);
$("btn-rb-now").addEventListener("click", runRouterBackup);
$("btn-rb-export").addEventListener("click", exportRouterRsc);
$("btn-al-auto-save").addEventListener("click", saveAutoSync);
$("btn-al-auto-run").addEventListener("click", runAutoSync);
$("btn-al-tg-status").addEventListener("click", checkTgBot);
$("btn-al-tg-resolve").addEventListener("click", resolveTgChat);
$("al-tg-result").addEventListener("click", (e) => {
  const el = e.target.closest("[data-fill-chat]");
  if (!el) return;
  $("al-tg-chat").value = el.dataset.fillChat;
  toast("Chat ID подставлен. Нажмите «Сохранить».");
});
$("client-vpn-form").addEventListener("submit", addClientVpn);
$("cv-body").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-cvact]");
  if (!btn) return;
  const ip = btn.dataset.ip;
  if (btn.dataset.cvact === "toggle") toggleClientVpn(ip, btn.dataset.on === "1");
  else if (btn.dataset.cvact === "del") delClientVpn(ip);
});
$("btn-al-mt-refresh").addEventListener("click", loadAlMtEntries);
$("al-mt-list").addEventListener("change", (e) => { alMtList = e.target.value; alMtFilter = ""; $("al-mt-search").value = ""; loadAlMtEntries(); });
$("al-mt-form").addEventListener("submit", (e) => { e.preventDefault(); addAlMtEntry(); });
$("al-mt-body").addEventListener("click", (e) => {
  const btn = e.target.closest("button[data-almt]");
  if (btn) alMtAction(btn);
});
$("al-mt-search").addEventListener("input", (e) => { alMtFilter = e.target.value; alMtPage = 0; renderAlMtTable(); });
$("btn-al-mt-prev").addEventListener("click", () => { if (alMtPage > 0) { alMtPage--; renderAlMtTable(); } });
$("btn-al-mt-next").addEventListener("click", () => { alMtPage++; renderAlMtTable(); });
$("btn-al-mt-import").addEventListener("click", openAlMtImport);
$("btn-al-mt-export").addEventListener("click", openAlMtExport);
$("btn-al-mt-io-ok").addEventListener("click", doAlMtImport);
$("btn-al-mt-io-close").addEventListener("click", () => $("al-mt-io-modal").classList.add("hidden"));
$("btn-al-mt-io-copy").addEventListener("click", () => {
  $("al-mt-io-text").select();
  navigator.clipboard && navigator.clipboard.writeText($("al-mt-io-text").value);
  toast("Скопировано");
});
$("btn-mon-restart").addEventListener("click", async () => {
  if (!await showConfirm({ title: "Перезапуск туннеля", message: "Перезапустить L2TP/IPsec (strongSwan + xl2tpd)?", okText: "Перезапустить", danger: false })) return;
  try {
    await api("/api/monitor/tunnel/restart", "POST");
    toast("Туннель перезапущен");
    await loadMonitor();
  } catch (e) {
    toast("restart: " + e.message, true);
  }
});
startMonitorPoll();
startMikrotikPoll();
startTrafficPoll();
loadMonitorServers();

/* ===== init ===== */
$('btn-version-menu').addEventListener('click', () => switchView('updates'));
$('btn-update-check').addEventListener('click', checkPanelUpdate);
$('btn-update-install').addEventListener('click', installPanelUpdate);
$('btn-zt-save').addEventListener('click', saveZeroTierConfig);
$('btn-zt-connect').addEventListener('click', connectZeroTier);

(async function init() {
  if (token) {
    try {
      await api("/api/auth/me");
      await showMain();
      return;
    } catch (_) {}
  }
  showLogin();
})();
