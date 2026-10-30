import './style.css';
import { createStore } from './store.js';
import { loadIndex, loadDataset } from './data.js';
import { fmtClock, fmtInt, stationLabel } from './util.js';
import { Timeline } from './views/timeline.js';
import { Heatmap } from './views/heatmap.js';
import { KitTrace } from './views/kittrace.js';
import { SkuScatter } from './views/skuscatter.js';

let data = null;

// 상태끼리의 규칙
function normalize(next, prev) {
  const kit = data?.kitById.get(next.selectedKit);
  // 필터에 걸린 키트는 선택 해제 (V1 에서 숨겨진 키트가 V3 에 남지 않게)
  if (kit && ((next.lateOnly && !kit.late) || (next.station !== 'all' && kit.station_id !== next.station))) {
    next.selectedKit = null;
  }
  // 키트가 바뀌면 이전 키트의 트립 클릭으로 고른 SKU 는 해제
  if (next.selectedKit !== prev.selectedKit && next.skuSource === 'v3') {
    next.selectedTrip = null;
    next.selectedSkus = [];
    next.skuSource = null;
  }
  // 스테이션 필터 밖의 강조 행은 해제
  if (next.station !== prev.station && next.station !== 'all' && next.focusRow && next.focusRow !== next.station) {
    next.focusRow = null;
    next.focusCell = null;
  }
  return next;
}

const store = createStore({
  policy: null, // 데이터셋 (정책 × 부하) id
  dataVersion: 0,
  timeWindow: null, // [t0, t1] 초 또는 null(전체)
  selectedKit: null,
  selectedSkus: [],
  skuSource: null, // 'v4' (brush) | 'v3' (트립 클릭)
  selectedTrip: null,
  lateOnly: false,
  station: 'all',
  hoveredTrip: null,
  focusRow: null, // V2 셀 클릭으로 강조한 스테이션 행
  focusCell: null,
  minCartons: 1, // V4: 필요 카톤이 이보다 작은 SKU 는 흐리게 그리고 brush 선택·상관계수에서 뺀다
}, normalize);

const views = [
  new Timeline(document.getElementById('v1-body'), store),
  new Heatmap(document.getElementById('v2-body'), store),
  new KitTrace(document.getElementById('v3-body'), store),
  new SkuScatter(document.getElementById('v4-body'), store),
];

store.subscribe((state, changed) => {
  if (!data) return;
  for (const v of views) {
    if (v.deps.some((k) => changed.has(k))) v.update(state, changed);
  }
  syncHeader(state, changed);
});

// ---------------------------------------------------------------------------
// 헤더
// ---------------------------------------------------------------------------
const el = {
  dataset: document.getElementById('dataset-select'),
  station: document.getElementById('station-select'),
  lateOnly: document.getElementById('late-only'),
  info: document.getElementById('shift-info'),
  reset: document.getElementById('reset-all'),
  v1Reset: document.getElementById('v1-reset'),
  windowLabel: document.getElementById('window-label'),
  error: document.getElementById('error'),
  footer: document.getElementById('footer-run'),
};

el.dataset.addEventListener('change', () => switchDataset(el.dataset.value));
el.station.addEventListener('change', () => store.set({ station: el.station.value }));
el.lateOnly.addEventListener('change', () => store.set({ lateOnly: el.lateOnly.checked }));
el.v1Reset.addEventListener('click', () => store.set({ timeWindow: null, focusCell: null, focusRow: null }));
el.reset.addEventListener('click', () => store.set({
  timeWindow: null, selectedKit: null, selectedSkus: [], skuSource: null, selectedTrip: null,
  lateOnly: false, station: 'all', focusRow: null, focusCell: null,
  minCartons: data?.defaultMinCartons ?? 1,
}));

function syncHeader(state, changed) {
  if (changed.has('dataVersion')) {
    const m = data.meta;
    const late = m.n_late_kits
      ? `<span class="late-text"><b>${m.n_late_kits}</b> late kits</span>`
      : '<span>no late kits</span>';
    el.info.innerHTML = [
      `<b>${fmtInt(m.n_totes)}</b> totes`, `<b>${m.n_kits}</b> kits`, `<b>${fmtInt(m.n_trips)}</b> trips`,
      `<b>${m.n_stations}</b> stations`, `<b>${m.n_agvs}</b> AMRs`, `shift <b>${fmtClock(m.t_end)}</b>`, late,
    ].join('<span class="sep">·</span>');
    el.station.innerHTML = ['all', ...data.stations]
      .map((s) => `<option value="${s}">${s === 'all' ? 'All' : stationLabel(s)}</option>`).join('');
    el.footer.textContent = `Run: ${m.policy_name} · ${m.size} instance, seed ${m.seed}, target load ${m.target_load?.toFixed(1)} · `
      + `source ${m.source_dir}`;
  }
  el.station.value = state.station;
  el.lateOnly.checked = state.lateOnly;
  el.dataset.value = state.policy;
  const w = state.timeWindow;
  el.windowLabel.textContent = w ? `Window ${fmtClock(w[0])} – ${fmtClock(w[1])}` : 'Whole shift';
  el.v1Reset.disabled = !w;
}

// ---------------------------------------------------------------------------
// 데이터셋 전환
// ---------------------------------------------------------------------------
async function switchDataset(id) {
  try {
    document.body.classList.add('loading');
    const next = await loadDataset(id);
    data = next;
    for (const v of views) v.setData(next);
    const st = store.state;
    const url = new URL(window.location.href);
    url.searchParams.set('run', id);
    window.history.replaceState(null, '', url);
    store.set({
      policy: id,
      dataVersion: st.dataVersion + 1,
      timeWindow: null,
      selectedKit: null,
      selectedSkus: [],
      skuSource: null,
      selectedTrip: null,
      hoveredTrip: null,
      focusRow: null,
      focusCell: null,
      station: next.stations.includes(st.station) ? st.station : 'all',
      minCartons: next.defaultMinCartons,
    });
    el.error.hidden = true;
  } catch (err) {
    el.error.hidden = false;
    el.error.textContent = `Could not load run "${id}": ${err.message}`;
    console.error(err);
  } finally {
    document.body.classList.remove('loading');
  }
}

async function init() {
  try {
    const index = await loadIndex();
    el.dataset.innerHTML = index.datasets.map((d) => {
      const late = d.n_late_kits ? `${d.n_late_kits} late` : 'no late kits';
      const load = d.target_load == null ? '' : ` · load ${d.target_load.toFixed(1)}`;
      return `<option value="${d.id}">${d.policy_name.replace(/ Policy$/, '')}${load} · ${late}</option>`;
    }).join('');
    const want = new URL(window.location.href).searchParams.get('run');
    const first = index.datasets.some((d) => d.id === want) ? want : index.default;
    await switchDataset(first);
  } catch (err) {
    el.error.hidden = false;
    el.error.textContent = `Could not load data/index.json — run tools/build_vis_data.py first. (${err.message})`;
    console.error(err);
  }
}

// 헤드리스 확인용으로 store 를 노출한다 (UI 동작에는 쓰지 않음)
window.__trace = { store, get data() { return data; } };

init();
