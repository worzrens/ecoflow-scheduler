/* Screens. Data comes from the app (Model.java) through App.setModel / App.setLive; nothing is fetched here. */
'use strict';

const $ = id => document.getElementById(id);
const FRESH = 90;                       // seconds a reading counts as live
const RANGES = {
  dash: [['30 min', 1800], ['1 h', 3600], ['6 h', 21600], ['24 h', 86400], ['7 d', 604800]],
  power: [['24 hours', 86400], ['3 days', 259200], ['7 days', 604800]],
  soc: [['24 hours', 86400], ['3 days', 259200], ['7 days', 604800]],
  real: [['Today', 1], ['3 days', 3], ['7 days', 7]],
  plan: [['Today', 'today'], ['+ Tomorrow', 'tomorrow'], ['3 days', 3], ['7 days', 7]]
};
const chosen = {dash: 1800, power: 259200, soc: 259200, real: 3, plan: 3, which: 'out'};
try { Object.assign(chosen, JSON.parse(localStorage.getItem('chosen') || '{}')); } catch (e) { /* not available */ }

let model = null, tab = 'dashboard', liveProblem = '';
const editing = {account: false, repo: false}, busy = {account: false, repo: false, sync: false};

const charts = {};
function makeCharts() {
  charts.dash = new AreaChart($('dash-chart'), 'W');
  charts.dashBars = null;
  charts.power = new AreaChart($('power-chart'), 'W');
  charts.bars = new PillBars($('power-bars'));
  charts.soc = new AreaChart($('soc-chart'), '%', 100);
  charts.real = new Timeline($('real-chart'), 'real');
  charts.plan = new Timeline($('plan-chart'), 'plan');
}

function chips(id, options, current, pick) {
  const box = $(id);
  box.textContent = '';
  for (const [label, value] of options) {
    const b = document.createElement('button');
    b.type = 'button';
    b.textContent = label;
    b.className = value === current ? 'on' : '';
    b.onclick = () => pick(value);
    box.appendChild(b);
  }
}

function choose(key, value) {
  chosen[key] = value;
  try { localStorage.setItem('chosen', JSON.stringify(chosen)); } catch (e) { /* not available */ }
  render();
}

const nowSec = () => model && model.fixedNow ? model.fixedNow : Date.now() / 1000;
const live = () => model && model.live;
const fresh = () => live() && nowSec() - model.live.ts <= FRESH && !liveProblem;
const watts = v => Math.round(v) + ' W';

function fmtDuration(minutes) {
  if (minutes == null || minutes <= 0) return '--';
  const m = Math.floor(minutes), d = Math.floor(m / 1440), h = Math.floor(m % 1440 / 60);
  if (d) return d + 'd ' + h + 'h';
  return h ? h + 'h ' + pad2(m % 60) + 'm' : (m % 60) + 'm';
}

function when(ts) {
  const d = new Date(ts * 1000);
  return d.toDateString() === new Date(nowSec() * 1000).toDateString() ? hhmm(ts) : weekday(ts) + ' ' + hhmm(ts);
}

function socColor(soc) {
  const stops = [[0, [239, 68, 68]], [10, [239, 68, 68]], [25, [251, 146, 60]], [45, [250, 204, 21]], [70, [46, 230, 138]], [100, [46, 230, 138]]];
  const v = Math.max(0, Math.min(100, soc));
  for (let i = 1; i < stops.length; i++) {
    const [a, ca] = stops[i - 1], [b, cb] = stops[i];
    if (v >= a && v <= b) return ca.map((x, k) => Math.round(x + (cb[k] - x) * (v - a) / (b - a || 1)));
  }
  return [46, 230, 138];
}

/* same rules as power.state_of */
function stateOf(r, prev) {
  const net = r.in - r.out;
  if (!r.grid) return net > 3 ? 'charging' : 'discharging';
  if (r.soc >= 99.5 || (prev === 'full' && r.soc >= 98)) return net >= -3 ? 'full' : 'discharging';
  if (net > 3 || (prev === 'charging' && net > 0)) return 'charging';
  return net < -3 ? 'discharging' : 'ongrid';
}

/* ------------------------------------------------------------------ dashboard */
function renderHeader() {
  const dot = $('status').firstElementChild, label = $('status').lastElementChild;
  const connected = model && (model.setup.account.connected || model.setup.repo.connected);
  let text = 'Not set up', cls = '';
  if (connected) {
    if (fresh()) { text = 'Live'; cls = 'ok'; }
    else if (liveProblem) { text = liveProblem; cls = 'bad'; }
    else if (live()) { text = 'Last reading ' + when(model.live.ts); cls = 'bad'; }
    else text = 'Waiting for data…';
  }
  dot.className = 'dot ' + cls;
  label.textContent = text;
}

function renderDashboard() {
  const r = live(), ok = fresh();
  const name = r ? (model.state ? model.state.name : stateOf(r)) : null;
  $('temp').textContent = r && ok && r.temp ? Math.round(r.temp) + ' °C' : '';
  $('remain').textContent = !r ? '--' : (name === 'charging' && ok && r.chgMin > 0 ? fmtDuration(r.chgMin) + ' to full' : fmtDuration(r.dsgMin));
  const chip = $('state'), since = $('since');
  const labels = {charging: '⚡ Charging', discharging: 'Discharging', full: '✓ Fully charged', ongrid: 'On grid'};
  if (!r) { chip.textContent = 'No data'; chip.className = 'chip'; since.textContent = ''; }
  else if (!ok) { chip.textContent = 'Offline'; chip.className = 'chip'; since.textContent = '• last data ' + when(r.ts); }
  else {
    chip.textContent = labels[name] + (r.grid ? '' : ' · no electricity');
    chip.className = 'chip ' + (!r.grid ? 'warn' : (name === 'charging' || name === 'full' ? 'ok' : ''));
    since.textContent = model.state ? '• ' + (name === 'charging' || name === 'discharging' ? 'started ' : 'since ') + when(model.state.since) : '';
  }
  const fill = $('bat-fill');
  if (r && r.soc != null) {
    const [R, G, B] = socColor(r.soc), color = ok ? `rgb(${R},${G},${B})` : '#6b7280';
    fill.style.width = 'max(26px, ' + Math.max(0, Math.min(100, r.soc)) + '%)';
    fill.style.background = `linear-gradient(90deg, color-mix(in srgb, ${color} 52%, black), ${color} 75%, color-mix(in srgb, ${color} 80%, white))`;
    $('bat-text').textContent = Math.round(r.soc) + '%';
  } else { fill.style.width = '0'; $('bat-text').textContent = '--'; }
  fill.className = ok ? name : '';

  // Input card, same three presentations as the desktop app: limit / full / charging
  const hasInput = !!r && r.in >= 1;
  const mode = !hasInput ? 'none' : (name === 'charging' && r.in - r.out > 3 ? 'charging' : (name === 'full' ? 'full' : 'limit'));
  $('in-title').textContent = mode === 'charging' ? 'Charging' : 'Input';
  $('in-right').hidden = !hasInput;
  const limit = r && r.limit ? watts(r.limit) : '--';
  $('limit-value').className = 'stat' + (mode === 'full' ? ' off' : '');
  if (mode === 'charging') {
    const usage = Math.min(Math.max(r.out, 0), Math.max(r.in, 0));
    $('in-value').textContent = watts(Math.max(0, r.in - usage));
    $('in-sub').textContent = 'Limit ' + limit;
    $('limit-caption').textContent = 'Usage';
    $('limit-value').textContent = watts(usage);
    $('limit-sub').textContent = 'Total input ' + watts(r.in);
  } else {
    $('in-value').textContent = r ? watts(r.in) : '-- W';
    $('in-sub').textContent = mode === 'full' ? 'Battery full - powering the load' : (r && !r.grid ? 'No electricity' : '');
    $('limit-caption').textContent = 'Limit';
    $('limit-value').textContent = limit;
    $('limit-sub').textContent = mode === 'full' ? 'not in use - battery full' : '';
  }
  $('out-value').textContent = r ? watts(r.out) : '-- W';
  $('acout').textContent = r && r.acOut != null && ok ? 'AC output ' + watts(r.acOut) : '';

  chips('dash-range', RANGES.dash, chosen.dash, v => choose('dash', v));
  powerArea(charts.dash, chosen.dash, $('dash-caption'), $('dash-value'), $('dash-sub'), 'Energy used', RANGES.dash);
}

/* ------------------------------------------------------------------ graphs shared by both tabs */
const label = (list, value) => (list.find(x => x[1] === value) || list[0])[0];
const within = secs => (model ? model.samples : []).filter(s => s[0] >= nowSec() - secs);

function energy(rows, idx) {
  let total = 0;
  for (let i = 1; i < rows.length; i++) {
    const dt = rows[i][0] - rows[i - 1][0];
    if (dt > 0 && dt <= 300) total += rows[i - 1][idx] * dt / 3.6e6;
  }
  return total;
}

function powerArea(chart, secs, caption, value, sub, title, ranges) {
  const rows = within(secs), all = model ? model.samples : [];
  const edge = all.filter(s => s[0] < nowSec() - secs).slice(-1).concat(rows);
  caption.textContent = title + ' - ' + label(ranges, secs);
  value.textContent = fmtEnergy(energy(rows, 3));
  sub.textContent = 'used  |  ' + fmtEnergy(energy(rows, 2)) + ' in';
  chart.set([{name: 'Input', color: C.green, pts: edge.map(s => [s[0], s[2]]), stepZero: true},
             {name: 'Output', color: C.orange, pts: edge.map(s => [s[0], s[3]])}], nowSec() - secs, nowSec());
}

/* ------------------------------------------------------------------ statistics */
const seg = a => ({start: a[0], end: a[1], kind: a[2], socStart: a[3], socEnd: a[4], out: a[5], est: a[6], manual: a[7]});
const planSeg = a => ({start: a[0], end: a[1], kind: a[2]});

/* A day of the schedule graph; days without a published schedule say why. */
function planDay(d, today) {
  let segs = d.plan.map(planSeg);
  if (!segs.length) {
    const later = d.start > today;
    segs = [{start: d.start, end: d.end, kind: KIND.NODATA, note: later ? 'Not published' : 'Not saved',
      detail: later ? 'Not published yet; it is picked up automatically.' : 'No schedule was saved for this day.'}];
  }
  return {start: d.start, end: d.end, segs};
}

function renderStats() {
  chips('real-range', RANGES.real, chosen.real, v => choose('real', v));
  chips('plan-range', RANGES.plan, chosen.plan, v => choose('plan', v));
  chips('power-range', RANGES.power, chosen.power, v => choose('power', v));
  chips('soc-range', RANGES.soc, chosen.soc, v => choose('soc', v));
  if (!model || !model.days.length) return;
  const days = model.days, past = days.slice(0, -1), todayStart = past[past.length - 1].start, now = nowSec();

  const overlay = $('compare').checked;
  const real = past.slice(-chosen.real).map(d => ({start: d.start, end: d.end, segs: d.real.map(seg), plan: d.plan.map(planSeg)}));
  let off = 0, estimated = 0, manual = 0, count = 0, planned = 0;
  for (const d of real) {
    let inside = false;
    for (const s of d.segs) {
      if (s.kind === KIND.OUTAGE) { off += s.end - s.start; estimated += s.est; manual += s.manual; if (!inside) count++; inside = true; } else inside = false;
    }
    for (const s of d.plan) if (s.kind === KIND.OUTAGE) planned += s.end - s.start;
  }
  $('real-value').textContent = off > 0 ? (estimated > 0 ? '~' : '') + fmtHm(off) : 'None';
  $('real-sub').textContent = [count ? count + (count === 1 ? ' outage' : ' outages') : 'no outages recorded',
    estimated > 0 ? fmtHm(estimated) + ' estimated' : '', manual > 0 ? fmtHm(manual) + ' marked by hand' : '', overlay ? 'schedule said ' + fmtHm(planned) : ''].filter(Boolean).join(' · ');
  $('real-legend').innerHTML = '<span><i class="mark box green"></i>Electricity</span><span><i class="mark box hollow"></i>No electricity</span><span><i class="mark box none"></i>No data</span>' +
    (overlay ? '<span><i class="mark box orange-line"></i>Planned outage</span>' : '');
  charts.real.gaps = model.gaps || [];
  charts.real.set(real, now, overlay);

  const todayIdx = days.length - 2;
  const shown = chosen.plan === 'today' ? [days[todayIdx]] : chosen.plan === 'tomorrow' ? days.slice(todayIdx) : past.slice(-chosen.plan);
  const plan = shown.map(d => planDay(d, todayStart));
  let p = 0, maybe = 0, outs = 0;
  const missing = new Set();
  for (const d of plan) for (const s of d.segs) {
    if (s.kind === KIND.OUTAGE) { p += s.end - s.start; outs++; }
    if (s.kind === KIND.MAYBE) maybe += s.end - s.start;
    if (s.note) missing.add(s.note.toLowerCase());
  }
  const saved = shown.some(d => d.plan.length);
  $('plan-value').textContent = !saved ? '--' : (p > 0 ? fmtHm(p) : 'None');
  $('plan-sub').textContent = !saved ? (model.group ? [...missing].join(', ') : 'no outage group synced yet')
    : [outs ? outs + (outs === 1 ? ' planned outage' : ' planned outages') : 'no outages planned',
       maybe > 0 ? '+' + fmtHm(maybe) + ' possible' : '', ...missing, model.group ? 'group ' + model.group : ''].filter(Boolean).join(' · ');
  charts.plan.set(plan, now, false);

  const bars = chosen.power > 86400;
  $('power-chart').hidden = bars;
  $('power-bars').hidden = !bars;
  $('power-which').hidden = !bars;
  if (bars) {
    const n = Math.round(chosen.power / 86400), rows = past.slice(-n).map(d => ({day: d.start, inKwh: d.inKwh, outKwh: d.outKwh, has: d.hasData}));
    chips('power-which', [['Output', 'out'], ['Input', 'in']], chosen.which, v => choose('which', v));
    const total = rows.reduce((s, r) => s + (chosen.which === 'out' ? r.outKwh : r.inKwh), 0);
    $('power-caption').textContent = 'Total energy ' + (chosen.which === 'out' ? 'usage' : 'input') + ' - ' + label(RANGES.power, chosen.power);
    $('power-value').textContent = total.toFixed(2) + ' kWh';
    $('power-sub').textContent = '';
    charts.bars.set(rows, chosen.which);
  } else {
    powerArea(charts.power, chosen.power, $('power-caption'), $('power-value'), $('power-sub'), 'Statistic', RANGES.power);
  }

  const rows = within(chosen.soc).filter(s => s[1] != null);
  const levels = rows.map(s => s[1]);
  $('soc-caption').textContent = 'Battery level - ' + label(RANGES.soc, chosen.soc);
  $('soc-value').textContent = levels.length ? Math.round(levels[levels.length - 1]) + '%' : '--';
  $('soc-sub').textContent = levels.length ? 'min ' + Math.round(levels.reduce((a, b) => Math.min(a, b))) + '% - max ' + Math.round(levels.reduce((a, b) => Math.max(a, b))) + '%' : '';
  charts.soc.set([{name: 'Battery', color: C.green, pts: rows.map(s => [s[0], s[1]])}], now - chosen.soc, now);
}

/* ------------------------------------------------------------------ marking stretches without data */
let markZone = null, toastTimer;

function showSheet(zone) {
  markZone = zone;
  $('mark-sheet').hidden = !zone;
  if (!zone) return;
  const span = zone.end - zone.start;
  $('mark-title').textContent = 'No data ' + when(zone.start) + '–' + when(zone.end) + ' (' + fmtHm(span) + ')';
  $('mark-clear').hidden = !zone.marked;
}

function toast(message) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, 6000);
}

/* ------------------------------------------------------------------ settings: summary once connected, form to edit */
function renderSettings() {
  if (!model) return;
  const {account, repo} = model.setup;
  for (const [kind, short, info] of [['account', 'acc', account], ['repo', 'repo', repo]]) {
    const form = !info.connected || editing[kind];
    $(short + '-summary').hidden = form;
    $(short + '-form').hidden = !form;
    $(short + '-cancel').hidden = !info.connected || busy[kind];
    const button = $(short + '-connect');
    button.disabled = busy[kind];
    button.textContent = busy[kind] ? (kind === 'account' ? 'Signing in…' : 'Connecting and syncing…') : 'Connect';
  }
  $('acc-line').textContent = [account.email, account.sn, account.host].join('  ·  ');
  $('acc-status').textContent = account.error ? 'Last reading failed: ' + account.error : (fresh() ? 'Connected - live' : 'Connected');
  $('repo-line').textContent = repo.repo;
  $('repo-status').textContent = busy.sync ? 'Syncing…' : repo.error ? 'Last sync failed: ' + repo.error
    : repo.marksError ? 'Your marks were not sent: ' + repo.marksError
    : [repo.syncedAt ? 'Last sync ' + when(repo.syncedAt) : 'Connected', repo.samples + ' samples',
       repo.group ? repo.scheduleDays + ' schedule days for group ' + repo.group : 'no outage group synced yet'].join(' · ');
  $('sync-now').disabled = busy.sync;
  $('auto-update').checked = model.setup.autoUpdate;
}

/* Fill the form fields only when it opens, so refreshes never overwrite what is being typed. */
function openForm(kind) {
  const info = model.setup[kind];
  if (kind === 'account') {
    $('email').value = info.email;
    $('sn').value = info.sn;
    $('host').value = info.host;
    $('password').value = '';
    $('password').placeholder = info.connected ? 'saved - leave empty to keep' : '';
    $('acc-msg').textContent = '';
  } else {
    $('repo').value = info.repo;
    $('token').value = '';
    $('token').placeholder = info.connected ? 'saved - leave empty to keep' : '';
    $('repo-msg').textContent = '';
  }
}

let formsFilled = false;
function render() {
  renderHeader();
  if (tab === 'dashboard') renderDashboard();
  else if (tab === 'statistics') renderStats();
  else renderSettings();
}

const App = {
  setModel(m) {
    const newer = model && model.live && (!m.live || model.live.ts > m.live.ts);
    if (newer) { m.live = model.live; m.state = model.state; }
    model = m;
    if (!formsFilled) { openForm('account'); openForm('repo'); formsFilled = true; }
    render();
  },
  setLive(r) {
    if (!model) return;
    liveProblem = '';
    const name = stateOf(r, model.state && model.state.name);
    if (!model.state || model.state.name !== name) model.state = {name, since: r.ts};
    model.live = r;
    const last = model.samples[model.samples.length - 1];
    if (!last || r.ts - last[0] >= 5) model.samples.push([r.ts, r.soc, r.in, r.out]);
    renderHeader();
    if (tab === 'dashboard') renderDashboard();
  },
  liveError(message) { liveProblem = message; render(); },
  fail(message) { liveProblem = message; renderHeader(); },
  connected(kind, error) {
    busy[kind] = false;
    const box = $((kind === 'account' ? 'acc' : 'repo') + '-msg');
    box.textContent = error;
    box.className = 'msg' + (error ? ' bad' : '');
    if (!error) {
      editing[kind] = false;
      if (kind === 'account') { liveProblem = ''; $('password').value = ''; } else $('token').value = '';
    }
    render();
  },
  refreshDone() { busy.sync = false; render(); },
  marked(error) { toast(error ? 'Saved on this phone, not shared: ' + error : 'Saved and shared'); },
  showTab(name) {
    tab = name;
    showSheet(null);
    document.querySelectorAll('.tab').forEach(s => { s.hidden = s.id !== 'tab-' + name; });
    document.querySelectorAll('nav button').forEach(b => b.classList.toggle('on', b.dataset.tab === name));
    document.querySelector('main').scrollTop = 0;
    render();
  }
};

function start() {
  makeCharts();
  document.querySelectorAll('nav button').forEach(b => { b.onclick = () => App.showTab(b.dataset.tab); });
  $('compare').onchange = render;
  charts.real.onZone = showSheet;
  $('mark-close').onclick = () => showSheet(null);
  document.querySelectorAll('[data-mark]').forEach(b => {
    b.onclick = () => {
      if (markZone && window.Native) Native.mark(markZone.start, markZone.end, b.dataset.mark);
      showSheet(null);
    };
  });
  document.querySelectorAll('[data-edit]').forEach(b => { b.onclick = () => { editing[b.dataset.edit] = true; openForm(b.dataset.edit); render(); }; });
  document.querySelectorAll('[data-cancel]').forEach(b => { b.onclick = () => { editing[b.dataset.cancel] = false; render(); }; });
  document.querySelectorAll('[data-forget]').forEach(b => {
    let armed = null;                                           // a second tap confirms
    const original = b.textContent;
    b.onclick = () => {
      if (!armed) {
        b.textContent = 'Tap again to confirm';
        armed = setTimeout(() => { armed = null; b.textContent = original; }, 3000);
        return;
      }
      clearTimeout(armed); armed = null; b.textContent = original;
      const kind = b.dataset.forget;
      if (window.Native) Native.disconnect(kind);
      setTimeout(() => { openForm(kind); }, 400);
    };
  });
  $('acc-form').onsubmit = e => {
    e.preventDefault();
    if (busy.account) return;
    busy.account = true;
    $('acc-msg').textContent = '';
    document.activeElement.blur();
    render();
    Native.connectAccount($('email').value, $('password').value, $('sn').value, $('host').value);
  };
  $('repo-form').onsubmit = e => {
    e.preventDefault();
    if (busy.repo) return;
    busy.repo = true;
    $('repo-msg').className = 'msg';
    $('repo-msg').textContent = 'The first download can take a minute.';
    document.activeElement.blur();
    render();
    Native.connectRepo($('repo').value, $('token').value);
  };
  $('auto-update').onchange = e => {
    model.setup.autoUpdate = e.target.checked;
    if (window.Native) Native.setAutoUpdate(e.target.checked);
  };
  $('sync-now').onclick = () => { busy.sync = true; render(); Native.refresh(); };
  let resize;
  window.addEventListener('resize', () => { clearTimeout(resize); resize = setTimeout(render, 80); });
  setInterval(() => { renderHeader(); if (tab === 'dashboard' && !document.hidden) renderDashboard(); }, 15000);
  if (window.Native) Native.ready();
}

start();
