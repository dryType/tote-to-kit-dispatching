import * as d3 from 'd3';

// 색 규칙 (모든 뷰 공통). 주황(late)은 지연에만 쓴다.
export const C = {
  ink: '#16213A',
  bg: '#F5F3EE',
  card: '#FBFAF7',
  grid: '#D8D4CA',
  blue: '#2D63A8',
  late: '#C2610F',
  partial: '#16213A',
  normal: '#8FADD3',
};

// 히트맵: 순차 파랑 5단계
export const HEAT = d3.quantize(d3.interpolateLab('#EEF2F8', '#2D5A94'), 5);

// ---------------------------------------------------------------------------
// 포맷
// ---------------------------------------------------------------------------

/** 초 -> h:mm (교대 시작 기준) */
export function fmtClock(sec) {
  if (sec == null || !Number.isFinite(sec)) return '–';
  const m = Math.floor(Math.max(0, sec) / 60);
  return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`;
}

/** 초 -> "45 s", "12 min", "1 h 05 min" */
export function fmtDur(sec) {
  if (sec == null || !Number.isFinite(sec)) return '–';
  const s = Math.abs(sec);
  if (s < 90) return `${Math.round(s)} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}

export const fmtPct = (v) => (v == null ? '–' : `${Math.round(v * 100)}%`);
export const fmtInt = d3.format(',');
export const fmtNum = (v, nd = 2) => (v == null ? '–' : d3.format(`,.${nd}f`)(v));

/** station_1 -> S1 */
export const stationLabel = (id) => (id === 'all' ? 'All' : String(id).replace(/^station_/, 'S'));

/** 시간 축 눈금: 분 단위로 떨어지는 간격 중 approx 개 안팎이 되는 것 */
const STEPS = [60, 120, 300, 600, 900, 1800, 3600, 7200, 10800];
export function timeTicks([t0, t1], approx) {
  const span = t1 - t0;
  const step = STEPS.find((s) => span / s <= approx) ?? STEPS[STEPS.length - 1];
  const out = [];
  for (let t = Math.ceil(t0 / step) * step; t <= t1 + 1e-9; t += step) out.push(t);
  return out;
}

// ---------------------------------------------------------------------------
// 필터 (뷰끼리 같은 정의를 쓰도록 한곳에 둔다)
// ---------------------------------------------------------------------------

/** 트립이 시간 창 안에 있다 = 도킹 구간 [t_dock, t_kit_end] 이 창과 겹친다 */
export const tripInWindow = (t, w) => !w || (t.t_dock < w[1] && t.t_kit_end > w[0]);

/** 키트가 시간 창 안에 있다 = [start, end] 가 창과 겹친다 */
export const kitInWindow = (k, w) => !w || (k.start < w[1] && (k.end ?? Infinity) > w[0]);

export const stationOk = (id, station) => station === 'all' || id === station;

/** 트립이 선택된 SKU 중 하나라도 실었나 */
export const tripHasSku = (t, skuSet) => Object.keys(t.matched_parts).some((s) => skuSet.has(s));

// ---------------------------------------------------------------------------
// 툴팁 (화면에 하나)
// ---------------------------------------------------------------------------

let tipEl = null;

export function showTip(event, html) {
  if (!tipEl) tipEl = document.getElementById('tooltip');
  tipEl.innerHTML = html;
  tipEl.hidden = false;
  const pad = 14;
  const { innerWidth: vw, innerHeight: vh } = window;
  const r = tipEl.getBoundingClientRect();
  let x = event.clientX + pad;
  let y = event.clientY + pad;
  if (x + r.width > vw - 8) x = event.clientX - r.width - pad;
  if (y + r.height > vh - 8) y = event.clientY - r.height - pad;
  tipEl.style.left = `${Math.max(8, x)}px`;
  tipEl.style.top = `${Math.max(8, y)}px`;
}

export function hideTip() {
  if (!tipEl) tipEl = document.getElementById('tooltip');
  tipEl.hidden = true;
}

/** 툴팁 행: [라벨, 값] 목록 -> html */
export function tipRows(title, rows) {
  const body = rows
    .filter(Boolean)
    .map(([k, v, cls]) => `<tr><th>${k}</th><td${cls ? ` class="${cls}"` : ''}>${v}</td></tr>`)
    .join('');
  return `<div class="tip-title">${title}</div><table>${body}</table>`;
}

/** 엘리먼트 폭이 바뀌면 다시 그린다 (프레임당 한 번) */
export function onResize(el, fn) {
  let raf = 0;
  let lastW = 0;
  new ResizeObserver((entries) => {
    const w = Math.round(entries[0].contentRect.width);
    if (w === lastW) return;
    lastW = w;
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => fn(w));
  }).observe(el);
}
