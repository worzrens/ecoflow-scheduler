/* Canvas graphs with touch hover, the mobile counterpart of ecoflow_app/charts.py and outages.py. */
'use strict';

const C = {
  bg: '#0e1013', card: '#171a1f', card2: '#20242b', grid: '#2a2e36', text: '#f3f4f6', muted: '#8b93a1',
  green: '#2ee68a', orange: '#ffa629', red: '#f87171', bar: '#2c3038', nodata: '#2c3038'
};
const KIND = {NODATA: 0, GRID: 1, OUTAGE: 2, MAYBE: 3};
const FONT = 'system-ui, sans-serif';

const pad2 = n => String(n).padStart(2, '0');
const hhmm = ts => { const d = new Date(ts * 1000); return pad2(d.getHours()) + ':' + pad2(d.getMinutes()); };
const weekday = ts => new Date(ts * 1000).toLocaleDateString('en-GB', {weekday: 'short'});
const dayMonth = ts => { const d = new Date(ts * 1000); return pad2(d.getDate()) + '.' + pad2(d.getMonth() + 1); };
const fmtHm = seconds => {
  const m = Math.round(seconds / 60);
  if (m <= 0) return '0m';
  return m >= 60 ? Math.floor(m / 60) + 'h ' + pad2(m % 60) + 'm' : m + 'm';
};
const fmtEnergy = kwh => kwh < 1 ? Math.round(kwh * 1000) + ' Wh' : kwh.toFixed(2) + ' kWh';

function fit(canvas) {
  const ratio = window.devicePixelRatio || 1, w = canvas.clientWidth, h = canvas.clientHeight;
  if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
    canvas.width = Math.round(w * ratio);
    canvas.height = Math.round(h * ratio);
  }
  const g = canvas.getContext('2d');
  g.setTransform(ratio, 0, 0, ratio, 0, 0);
  g.clearRect(0, 0, w, h);
  return {g, w, h};
}

function rounded(g, x, y, w, h, r) {
  r = Math.max(0, Math.min(r, w / 2, h / 2));
  g.beginPath();
  g.moveTo(x + r, y);
  g.arcTo(x + w, y, x + w, y + h, r);
  g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r);
  g.arcTo(x, y, x + w, y, r);
  g.closePath();
}

function text(g, s, x, y, color, size = 11, align = 'left', bold = false) {
  g.fillStyle = color;
  g.font = (bold ? '600 ' : '') + size + 'px ' + FONT;
  g.textAlign = align;
  g.textBaseline = 'middle';
  g.fillText(s, x, y);
}

function line(g, x0, y0, x1, y1, color, dash = []) {
  g.strokeStyle = color;
  g.lineWidth = 1;
  g.setLineDash(dash);
  g.beginPath();
  g.moveTo(x0, y0);
  g.lineTo(x1, y1);
  g.stroke();
  g.setLineDash([]);
}

/* Value bubble next to the finger, kept inside the canvas. lines = [[text, color], ...] */
function bubble(g, W, H, px, py, lines) {
  let size = 12;
  const widest = () => { g.font = '600 ' + size + 'px ' + FONT; return Math.max(...lines.map(l => g.measureText(l[0]).width)); };
  while (widest() + 24 > W - 4 && size > 9) size--;
  const w = Math.min(W - 4, widest() + 24), step = size + 6, h = lines.length * step + 12;
  let x = px + 18 + w < W ? px + 18 : px - 18 - w;
  x = Math.max(2, Math.min(x, W - w - 2));
  let y = py - h - 24;                                 // above the finger
  if (y < 2) y = Math.min(py + 24, H - h - 2);
  y = Math.max(2, y);
  g.fillStyle = C.card2;
  g.shadowColor = 'rgba(0,0,0,.5)';
  g.shadowBlur = 10;
  rounded(g, x, y, w, h, 12);
  g.fill();
  g.shadowBlur = 0;
  lines.forEach((l, i) => text(g, l[0], x + 12, y + 6 + step / 2 + i * step, l[1], size, 'left', true));
}

/* Touch / mouse: the bubble follows the finger and stays after lifting it; a tap elsewhere closes it. */
function touchable(canvas, onPoint, onClear) {
  const point = e => { const r = canvas.getBoundingClientRect(); onPoint(e.clientX - r.left, e.clientY - r.top); };
  let down = false;
  canvas.addEventListener('pointerdown', e => { down = true; point(e); });
  canvas.addEventListener('pointermove', e => { if (down || e.pointerType === 'mouse') point(e); });
  canvas.addEventListener('pointerup', () => { down = false; });
  canvas.addEventListener('pointercancel', () => { down = false; onClear(); });      // the page started scrolling
  canvas.addEventListener('pointerleave', e => { if (e.pointerType === 'mouse') onClear(); });
  document.addEventListener('pointerdown', e => { if (e.target !== canvas) onClear(); });
}

/* ------------------------------------------------------------------ smooth area chart */
function downsample(pts, n) {
  if (pts.length <= n) return pts;
  const t0 = pts[0][0], span = (pts[pts.length - 1][0] - t0) / n || 1, out = [];
  let bucket = [], idx = 0;
  const flush = () => { if (bucket.length) out.push([bucket.reduce((s, b) => s + b[0], 0) / bucket.length, bucket.reduce((s, b) => s + b[1], 0) / bucket.length]); bucket = []; };
  for (const p of pts) {
    const i = Math.min(Math.floor((p[0] - t0) / span), n - 1);
    if (i !== idx) flush();
    idx = i;
    bucket.push(p);
  }
  flush();
  return out;
}

/* Monotone cubic (Fritsch-Carlson): smooth without overshoot. Appends to the current path. */
function monotone(g, pts, moveFirst) {
  if (moveFirst) g.moveTo(pts[0].x, pts[0].y); else g.lineTo(pts[0].x, pts[0].y);
  const n = pts.length;
  if (n < 3) { for (let i = 1; i < n; i++) g.lineTo(pts[i].x, pts[i].y); return; }
  const dx = [], m = [];
  for (let i = 0; i < n - 1; i++) { dx.push(Math.max(0.01, pts[i + 1].x - pts[i].x)); m.push((pts[i + 1].y - pts[i].y) / dx[i]); }
  const t = [m[0]];
  for (let i = 1; i < n - 1; i++) t.push(m[i - 1] * m[i] <= 0 ? 0 : (m[i - 1] + m[i]) / 2);
  t.push(m[n - 2]);
  for (let i = 0; i < n - 1; i++) {
    if (m[i] === 0) { t[i] = t[i + 1] = 0; continue; }
    const a = t[i] / m[i], b = t[i + 1] / m[i], s = a * a + b * b;
    if (s > 9) { const tau = 3 / Math.sqrt(s); t[i] = tau * a * m[i]; t[i + 1] = tau * b * m[i]; }
  }
  for (let i = 0; i < n - 1; i++) {
    const h = dx[i] / 3;
    g.bezierCurveTo(pts[i].x + h, pts[i].y + t[i] * h, pts[i + 1].x - h, pts[i + 1].y - t[i + 1] * h, pts[i + 1].x, pts[i + 1].y);
  }
}

class AreaChart {
  constructor(canvas, unit, fixedHi) {
    Object.assign(this, {canvas, unit, fixedHi, series: [], t0: 0, t1: 1, hover: null});
    touchable(canvas, (x, y) => { this.hover = {x, y}; this.draw(); }, () => { if (this.hover) { this.hover = null; this.draw(); } });
  }

  set(series, t0, t1) { Object.assign(this, {series, t0, t1: Math.max(t1, t0 + 1)}); this.draw(); }

  draw() {
    if (!this.canvas.clientWidth) return;
    const {g, w: W, h: H} = fit(this.canvas);
    const r = {l: 36, t: 18, w: W - 36 - 6, h: H - 18 - 24};
    r.b = r.t + r.h;
    const span = this.t1 - this.t0;
    let peak = 0;
    for (const s of this.series) for (const p of s.pts) if (p[1] > peak) peak = p[1];
    const hi = this.fixedHi || Math.max(500, Math.ceil(peak / 100) * 100);
    const step = [20, 25, 50, 100, 200, 250, 500, 1000, 2000, 5000].find(s => hi / s <= 5) || 5000;
    for (let v = 0; v <= hi + 1e-6; v += step) {
      const y = r.b - v / hi * r.h;
      line(g, r.l, y, r.l + r.w, y, C.grid, [3, 4]);
      text(g, String(v), r.l - 6, y, C.muted, 10, 'right');
    }
    text(g, this.unit, r.l - 6, 6, C.muted, 10, 'right');
    const ticks = W < 420 ? 3 : 4;
    for (let i = 0; i <= ticks; i++) {
      const d = this.t0 + i / ticks * span;
      const label = span <= 86400 ? hhmm(d) : weekday(d) + ' ' + hhmm(d);
      text(g, label, r.l + i / ticks * r.w, r.b + 14, C.muted, 10, i === 0 ? 'left' : (i === ticks ? 'right' : 'center'));
    }

    const items = [];
    for (const s of this.series) {
      const inside = s.pts.filter(p => p[0] >= this.t0 && p[0] <= this.t1);
      const before = s.pts.filter(p => p[0] < this.t0).slice(-1), after = s.pts.filter(p => p[0] > this.t1).slice(0, 1);
      const pts = downsample(before.concat(inside, after), Math.max(40, Math.floor(r.w / 7)));
      if (!pts.length) continue;
      const xs = pts.map(p => r.l + (p[0] - this.t0) / span * r.w);
      const ys = pts.map(p => r.b - Math.min(Math.max(p[1], 0), hi) / hi * r.h);
      const dts = pts.slice(1).map((p, i) => p[0] - pts[i][0]).sort((a, b) => a - b);
      const limit = Math.max(90, span / 150, 3 * (dts.length ? dts[dts.length >> 1] : 0));
      const gap = pts.slice(1).map((p, i) => p[0] - pts[i][0] > limit);
      const smooth = ys.map((y, i) => i > 0 && i < ys.length - 1 && !gap[i - 1] && !gap[i] ? 0.25 * ys[i - 1] + 0.5 * y + 0.25 * ys[i + 1] : y);
      const sp = xs.map((x, i) => ({x, y: smooth[i]}));
      const runs = [[sp[0]]], bridges = [];
      for (let i = 1; i < pts.length; i++) {
        if (!gap[i - 1]) { runs[runs.length - 1].push(sp[i]); continue; }
        const a = sp[i - 1], b = sp[i], va = pts[i - 1][1], vb = pts[i][1];
        let poly = [a, b];
        if (s.stepZero && va > 5 && vb <= 5) poly = [a, {x: a.x, y: r.b}, {x: b.x, y: r.b}, b];   // input gone: outage began
        else if (s.stepZero && vb > 5 && va <= 5) poly = [a, {x: b.x, y: a.y}, b];
        bridges.push(poly);
        runs.push([b]);
      }
      items.push({s, sp, runs, bridges, hits: pts.map((p, i) => ({x: xs[i], y: smooth[i], t: p[0], v: p[1]})).filter(q => q.t >= this.t0 && q.t <= this.t1)});
    }

    g.save();
    g.beginPath();
    g.rect(r.l - 1, r.t - 4, r.w + 2, r.h + 8);
    g.clip();
    [...items].reverse().forEach(it => {                     // the first series (input) ends up on top
      const first = it === items[0];
      const fill = g.createLinearGradient(0, r.t, 0, r.b);
      fill.addColorStop(0, it.s.color + (first ? '78' : '37'));
      fill.addColorStop(1, it.s.color + '08');
      g.beginPath();
      g.moveTo(it.sp[0].x, r.b);
      it.runs.forEach((run, k) => {
        if (k > 0) it.bridges[k - 1].slice(1, -1).forEach(c => g.lineTo(c.x, c.y));
        monotone(g, run, false);
      });
      g.lineTo(it.sp[it.sp.length - 1].x, r.b);
      g.closePath();
      g.fillStyle = fill;
      g.fill();
    });
    [...items].reverse().forEach(it => {
      g.strokeStyle = it.s.color;
      g.lineWidth = 2.2;
      g.lineJoin = 'round';
      it.runs.forEach(run => { g.beginPath(); monotone(g, run, true); g.stroke(); });
      g.setLineDash([4, 5]);
      it.bridges.forEach(b => { g.beginPath(); b.forEach((c, i) => i ? g.lineTo(c.x, c.y) : g.moveTo(c.x, c.y)); g.stroke(); });
      g.setLineDash([]);
    });
    g.restore();

    if (!items.some(it => it.hits.length)) text(g, 'No data in this range yet', r.l + r.w / 2, r.t + r.h / 2, C.muted, 13, 'center');
    if (!this.hover) return;
    const hits = [];
    for (const it of items) {
      if (!it.hits.length) continue;
      const q = it.hits.reduce((a, b) => Math.abs(b.x - this.hover.x) < Math.abs(a.x - this.hover.x) ? b : a);
      if (Math.abs(q.x - this.hover.x) <= 40) hits.push({s: it.s, q});
    }
    if (!hits.length) return;
    const gx = hits[0].q.x;
    line(g, gx, r.t, gx, r.b, '#4b5160', [3, 3]);
    for (const {s, q} of hits) {
      g.fillStyle = s.color + '46';
      g.beginPath(); g.arc(q.x, q.y, 10, 0, 7); g.fill();
      g.fillStyle = s.color; g.strokeStyle = C.bg; g.lineWidth = 2;
      g.beginPath(); g.arc(q.x, q.y, 5, 0, 7); g.fill(); g.stroke();
    }
    const t = hits[0].q.t;
    bubble(g, W, H, gx, Math.min(...hits.map(h => h.q.y)),
      [[dayMonth(t) + ' ' + hhmm(t), C.muted]].concat(hits.map(h => [h.s.name + '  ' + Math.round(h.q.v) + ' ' + this.unit, h.s.color])));
  }
}

/* ------------------------------------------------------------------ daily energy pill bars */
class PillBars {
  constructor(canvas) {
    Object.assign(this, {canvas, rows: [], which: 'out', sel: -1});
    touchable(canvas, x => {
      const {l, slot} = this.geom(canvas.clientWidth);
      const i = Math.floor((x - l) / slot);
      if (i >= 0 && i < this.rows.length && i !== this.sel) { this.sel = i; this.draw(); }
    }, () => {});
  }

  geom(W) { return {l: 52, slot: (W - 52 - 4) / Math.max(1, this.rows.length)}; }

  set(rows, which) {
    Object.assign(this, {rows, which});
    if (this.sel < 0 || this.sel >= rows.length) this.sel = rows.length - 1;
    this.draw();
  }

  draw() {
    if (!this.canvas.clientWidth) return;
    const {g, w: W, h: H} = fit(this.canvas);
    const {l, slot} = this.geom(W), top = 30, bottom = H - 24, h = bottom - top;
    const values = this.rows.map(r => this.which === 'out' ? r.outKwh : r.inKwh);
    const peak = Math.max(0.5, ...values);
    const step = [0.25, 0.5, 1, 2, 5, 10, 20, 50].find(s => peak / s <= 4) || 100;
    const max = Math.ceil(peak / step) * step;
    for (let v = 0; v <= max + 1e-6; v += step) {
      const y = bottom - v / max * h;
      line(g, l, y, W - 4, y, C.grid, [3, 4]);
      text(g, +v.toFixed(2) + ' kWh', l - 6, y, C.muted, 10, 'right');
    }
    const bw = Math.min(30, slot * 0.6);
    this.rows.forEach((row, i) => {
      const cx = l + slot * (i + 0.5), selected = i === this.sel;
      let y;
      if (row.has) {
        const bh = Math.max(Math.min(bw, 16), values[i] / max * h);
        y = bottom - bh;
        rounded(g, cx - bw / 2, y, bw, bh, 8);
        g.fillStyle = selected ? C.green : C.bar;
        g.fill();
      } else {
        y = bottom - h * 0.38;
        g.setLineDash([3, 3]);
        g.strokeStyle = selected ? C.green : '#4a505c';
        rounded(g, cx - bw / 2, y, bw, h * 0.38, 8);
        g.stroke();
        g.setLineDash([]);
      }
      text(g, weekday(row.day), cx, bottom + 14, selected ? C.text : C.muted, 11, 'center', selected);
      if (selected) {
        const s = row.has ? values[i].toFixed(2) + ' kWh' : 'No data';
        g.font = '600 12px ' + FONT;
        const tw = g.measureText(s).width + 18, bx = Math.max(2, Math.min(cx - tw / 2, W - tw - 2));
        rounded(g, bx, Math.max(2, y - 30), tw, 24, 9);
        g.fillStyle = C.card2;
        g.fill();
        text(g, s, bx + tw / 2, Math.max(2, y - 30) + 12, C.text, 12, 'center', true);
      }
    });
  }
}

/* ------------------------------------------------------------------ outage timelines */
const REAL_TEXT = {1: ['Electricity', C.green], 2: ['No electricity', C.red], 0: ['No data', C.muted]};
const SHORT = {'Planned outage': 'Planned', 'Possible outage': 'Possible', 'No electricity': 'No power', 'Not published': 'Not out'};
const PLAN_TEXT = {1: ['Power on', C.green], 2: ['Planned outage', C.orange], 3: ['Possible outage', C.orange], 0: ['No schedule', C.muted]};

/* days: [{start, end, segs: [{start, end, kind, socStart, socEnd, out, est, note, detail}], plan: [...] or null}] */
class Timeline {
  constructor(canvas, mode) {
    Object.assign(this, {canvas, mode, days: [], now: 0, overlay: false, hover: null});
    touchable(canvas, (x, y) => this.point(x, y), () => { if (this.hover) { this.hover = null; this.draw(); } });
  }

  set(days, now, overlay) {
    Object.assign(this, {days, now, overlay});
    this.calendar = days.length <= 3;
    this.canvas.classList.toggle('calendar', this.calendar);
    if (this.hover && this.hover.i >= days.length) this.hover = null;
    this.draw();
  }

  geom(W, H) {
    const r = this.calendar ? {l: 40, t: 52, w: W - 40 - 2, h: H - 52 - 8} : {l: 40, t: 8, w: W - 40 - 2, h: H - 8 - 38};
    r.slot = r.w / Math.max(1, this.days.length);
    return r;
  }

  column(i, r) {
    if (this.calendar) return {x: r.l + r.slot * i + 3, w: r.slot - 6};
    const w = Math.min(46, r.slot * 0.68);
    return {x: r.l + r.slot * (i + 0.5) - w / 2, w};
  }

  rect(d, col, r, s, inset = 0) {
    const span = d.end - d.start;
    const y0 = r.t + (s.start - d.start) / span * r.h, y1 = r.t + (s.end - d.start) / span * r.h;
    return {x: col.x + inset, y: y0 + inset, w: col.w - 2 * inset, h: Math.max(2, y1 - y0 - 2 * inset)};
  }

  point(x, y) {
    const r = this.geom(this.canvas.clientWidth, this.canvas.clientHeight);
    const i = Math.floor((x - r.l) / r.slot);
    let hit = null;
    if (i >= 0 && i < this.days.length && y >= r.t && y <= r.t + r.h) {
      const d = this.days[i], t = d.start + (y - r.t) / r.h * (d.end - d.start);
      const seg = d.segs.find(s => s.start <= t && t <= s.end) || null;
      const plan = this.overlay && d.plan ? d.plan.find(s => s.start <= t && t <= s.end) || null : null;
      if (seg || (plan && plan.kind >= KIND.OUTAGE)) hit = {i, seg, plan, x, y};
    }
    this.hover = hit;
    this.draw();
  }

  outline(g, q, kind, radius, solid) {
    if (kind !== KIND.OUTAGE && kind !== KIND.MAYBE) return;
    g.strokeStyle = kind === KIND.OUTAGE ? C.orange : C.orange + '96';
    g.lineWidth = solid ? 2.2 : 1.6;
    g.setLineDash(solid ? [] : (kind === KIND.OUTAGE ? [4, 3] : [1.5, 3]));
    rounded(g, q.x, q.y, q.w, q.h, radius);
    g.stroke();
    g.setLineDash([]);
  }

  draw() {
    if (!this.canvas.clientWidth) return;
    const {g, w: W, h: H} = fit(this.canvas);
    const r = this.geom(W, H), real = this.mode === 'real';
    const fill = {1: C.green, 2: C.card, 3: C.green, 0: C.nodata};
    if (this.calendar) {
      const hourH = r.h / 24, every = hourH >= 18 ? 2 : 3;
      for (let h = 0; h <= 24; h++) {
        const y = r.t + h * hourH;
        line(g, r.l, y, r.l + r.w, y, '#262a31');
        if (h < 24 && h % every === 0) text(g, pad2(h) + ':00', r.l - 5, y, C.muted, 10, 'right');
      }
      for (let i = 0; i <= this.days.length; i++) line(g, r.l + r.slot * i, r.t - 6, r.l + r.slot * i, r.t + r.h, '#262a31');
    } else {
      [['00:00', 0], ['06:00', .25], ['12:00', .5], ['18:00', .75], ['24:00', 1]].forEach(([s, f]) => {
        const y = r.t + f * r.h;
        line(g, r.l, y, r.l + r.w, y, C.grid, [3, 4]);
        text(g, s, r.l - 5, y, C.muted, 10, 'right');
      });
    }
    const today = new Date(this.now * 1000).toDateString();
    this.days.forEach((d, i) => {
      const col = this.column(i, r), hovered = this.hover && this.hover.i === i;
      const date = new Date(d.start * 1000);
      if (this.calendar) {
        const cx = col.x + col.w / 2, isToday = date.toDateString() === today;
        text(g, weekday(d.start).toUpperCase(), cx, 8, C.muted, 10, 'center');
        if (isToday) { g.fillStyle = C.green; g.beginPath(); g.arc(cx, 30, 14, 0, 7); g.fill(); }
        text(g, String(date.getDate()), cx, 31, isToday ? '#06130c' : C.text, 15, 'center', isToday);
        for (const s of d.segs) {
          const q = this.rect(d, col, r, s);
          q.y += 1; q.h = Math.max(1, q.h - 2);
          rounded(g, q.x, q.y, q.w, q.h, 7);
          g.fillStyle = real ? fill[s.kind] : (s.kind === KIND.NODATA ? C.nodata : C.card);
          if (!real && s.kind === KIND.GRID) g.fillStyle = C.green;
          g.fill();
          if (!real) this.outline(g, {x: q.x + .8, y: q.y + .8, w: q.w - 1.6, h: q.h - 1.6}, s.kind, 7);
          else if (s.kind === KIND.OUTAGE) {
            g.strokeStyle = '#5a606c'; g.lineWidth = 1.2; g.setLineDash([3, 3]);
            rounded(g, q.x + .8, q.y + .8, q.w - 1.6, q.h - 1.6, 7); g.stroke(); g.setLineDash([]);
          }
          if (hovered && this.hover.seg === s) { g.strokeStyle = '#fff'; g.lineWidth = 1.6; rounded(g, q.x, q.y, q.w, q.h, 7); g.stroke(); }
          this.blockText(g, q, d, s);
        }
      } else {
        g.save();
        rounded(g, col.x, r.t, col.w, r.h, 8);
        g.clip();
        for (const s of d.segs) {
          const q = this.rect(d, col, r, s);
          g.fillStyle = real ? fill[s.kind] : (s.kind === KIND.GRID ? C.green : (s.kind === KIND.NODATA ? C.nodata : C.card));
          g.fillRect(q.x, q.y, q.w, q.h);
          if (hovered && this.hover.seg === s) { g.fillStyle = 'rgba(255,255,255,.16)'; g.fillRect(q.x, q.y, q.w, q.h); }
        }
        g.restore();
        if (!real) for (const s of d.segs) this.outline(g, this.rect(d, col, r, s, 1.5), s.kind, 5);
        g.strokeStyle = hovered ? '#4a505c' : '#2f343d';
        g.lineWidth = 1.2;
        rounded(g, col.x, r.t, col.w, r.h, 8);
        g.stroke();
        const cx = col.x + col.w / 2;
        text(g, weekday(d.start), cx, r.t + r.h + 13, hovered ? C.text : C.muted, 11, 'center', hovered);
        text(g, dayMonth(d.start), cx, r.t + r.h + 28, C.muted, 10, 'center');
      }
      if (this.overlay && d.plan) {
        for (const s of d.plan) this.outline(g, this.rect(d, col, r, s, 2), s.kind, 6);
        if (hovered && !this.hover.seg) this.outline(g, this.rect(d, col, r, this.hover.plan, 2), this.hover.plan.kind, 6, true);
      }
      if (this.calendar && d.start <= this.now && this.now < d.end) {
        const y = r.t + (this.now - d.start) / (d.end - d.start) * r.h;
        line(g, col.x - 3, y, col.x + col.w, y, '#ef4444');
        g.fillStyle = '#ef4444'; g.beginPath(); g.arc(col.x - 3, y, 3.5, 0, 7); g.fill();
      }
    });
    if (this.hover) bubble(g, W, H, this.hover.x, this.hover.y, this.lines());
  }

  range(d, s) { return hhmm(s.start) + '–' + (s.end >= d.end - 1 ? '24:00' : hhmm(s.end)); }

  blockText(g, q, d, s) {
    if (q.h < 17 || q.w < 62) return;
    const names = this.mode === 'real' ? REAL_TEXT : PLAN_TEXT;
    const [name, color] = names[s.kind];
    const onGreen = s.kind === KIND.GRID;
    const ink = onGreen ? '#06260f' : (s.kind === KIND.NODATA ? C.muted : color);
    g.save();
    g.beginPath(); g.rect(q.x, q.y, q.w - 3, q.h); g.clip();
    const title = s.note || name;
    g.font = '600 11px ' + FONT;
    text(g, g.measureText(title).width > q.w - 11 ? (SHORT[title] || title) : title, q.x + 7, q.y + 10, ink, 11, 'left', true);
    if (q.h >= 32) text(g, this.range(d, s), q.x + 7, q.y + 24, ink, 10);
    if (q.h >= 46 && this.mode === 'real' && s.kind !== KIND.NODATA) {
      const extra = [battery(s, true), (s.est ? '~' : '') + fmtEnergy(s.out || 0)].filter(Boolean);
      text(g, extra[0], q.x + 7, q.y + 37, ink, 10);
      if (q.h >= 60 && extra[1]) text(g, extra[1], q.x + 7, q.y + 50, ink, 10);
    }
    g.restore();
  }

  lines() {
    const {i, seg, plan} = this.hover, d = this.days[i];
    if (!seg) {
      const out = [[PLAN_TEXT[plan.kind][0], C.orange], [this.range(d, plan), C.text], [fmtHm(plan.end - plan.start), C.muted]];
      if (plan.start > this.now) out.push(['Starts in ' + fmtHm(plan.start - this.now), C.muted]);
      else if (plan.end > this.now) out.push(['Ends in ' + fmtHm(plan.end - this.now) + ' (if on schedule)', C.muted]);
      return out;
    }
    const names = this.mode === 'real' ? REAL_TEXT : PLAN_TEXT;
    const out = [[seg.note || names[seg.kind][0], names[seg.kind][1]], [this.range(d, seg), C.text]];
    const length = seg.end - seg.start;
    if (this.mode === 'real' && seg.est > 1) out.push([fmtHm(length) + ' total / ' + fmtHm(seg.est) + ' estimated', C.text]);
    else out.push([fmtHm(length), C.muted]);
    if (this.mode === 'real') {
      if (seg.kind === KIND.NODATA) out.push(['Nothing was recorded', C.muted]);
      else {
        out.push(['Power used: ' + (seg.est ? '~' : '') + fmtEnergy(seg.out || 0), C.muted]);
        if (battery(seg)) out.push([battery(seg), C.muted]);
      }
    } else if (seg.detail) out.push([seg.detail, C.muted]);
    if (plan && plan.kind >= KIND.OUTAGE) out.push(['Schedule: ' + PLAN_TEXT[plan.kind][0].toLowerCase() + ' ' + this.range(d, plan), C.orange]);
    else if (this.overlay && this.mode === 'real' && seg.kind === KIND.OUTAGE) out.push(['Schedule: no outage planned', C.muted]);
    return out;
  }
}

function battery(s, short) {
  if (s.socStart == null || s.socEnd == null) return '';
  const a = Math.round(s.socStart), b = Math.round(s.socEnd), tilde = s.est ? '~' : '';
  if (a === b) return short ? tilde + a + '%' : 'Battery ' + tilde + a + '% (steady)';
  return short ? tilde + a + '→' + b + '%' : 'Battery ' + tilde + a + '% → ' + b + '%';
}
