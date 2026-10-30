// V4 SKU spread scatterplot: SKU 하나 = 점 하나
//   x = 교대 시작 시 그 SKU 를 담은 토트 수, y = 필요 카톤당 트립 수, 크기 = 필요 카톤 (sqrt), 색 = 일부 카톤 피킹 비율 >= 50%
// 필요 카톤이 "Min cartons needed" 미만인 SKU 는 비율의 분모가 작아 믿기 어려우므로 흐리게 그리고,
// brush 선택과 Spearman 상관계수에서 뺀다.
import * as d3 from 'd3';
import {
  C, fmtClock, fmtNum, fmtPct, fmtInt, stationLabel, stationOk, tripInWindow, showTip, hideTip, tipRows, onResize,
} from '../util.js';

const M = { top: 14, right: 16, bottom: 62, left: 52 };
const HOVER_PX = 6;
const FADED_OPACITY = 0.15;

/** 평균 순위 (같은 값은 순위의 평균) */
function ranks(values) {
  const idx = values.map((_, i) => i).sort((a, b) => values[a] - values[b]);
  const r = new Array(values.length);
  for (let i = 0; i < idx.length;) {
    let j = i;
    while (j + 1 < idx.length && values[idx[j + 1]] === values[idx[i]]) j += 1;
    const avg = (i + j) / 2 + 1;
    for (let k = i; k <= j; k += 1) r[idx[k]] = avg;
    i = j + 1;
  }
  return r;
}

/** Spearman 순위 상관계수 = 평균 순위의 Pearson 상관. n < 3 이거나 한쪽 순위가 모두 같으면 null */
export function spearman(xs, ys) {
  const n = xs.length;
  if (n < 3) return null;
  const rx = ranks(xs);
  const ry = ranks(ys);
  const mx = d3.mean(rx);
  const my = d3.mean(ry);
  let sxy = 0;
  let sxx = 0;
  let syy = 0;
  for (let i = 0; i < n; i += 1) {
    sxy += (rx[i] - mx) * (ry[i] - my);
    sxx += (rx[i] - mx) ** 2;
    syy += (ry[i] - my) ** 2;
  }
  return sxx > 0 && syy > 0 ? sxy / Math.sqrt(sxx * syy) : null;
}

const fmtCartons = (v) => (Number.isInteger(v) ? String(v) : fmtNum(v, 1));

/**
 * 현재 필터에서 SKU 통계를 다시 계산한다.
 * - 시간 창: n_trips, trips_per_carton 을 창 안 트립(도킹 구간이 창과 겹침)으로 다시 센다. x 는 시작 시점 기준이라 고정.
 * - 스테이션: 그 스테이션의 트립만 세고, 필요 카톤도 그 스테이션 키트만 더한다. partial_share 도 그 스테이션 트립(교대 전체)으로.
 */
export function skuStats(data, st) {
  const station = st.station;
  const w = st.timeWindow;
  const byStation = station !== 'all';
  const nWin = new Map();
  const nAll = new Map();
  const nPartAll = new Map();
  const inc = (m, k) => m.set(k, (m.get(k) ?? 0) + 1);
  for (const t of data.trips) {
    if (!stationOk(t.station_id, station)) continue;
    const inWin = tripInWindow(t, w);
    for (const s of Object.keys(t.matched_parts)) {
      inc(nAll, s);
      if (inWin) inc(nWin, s);
    }
    for (const s of t.partial_skus) inc(nPartAll, s);
  }
  let cartons = null;
  if (byStation) {
    cartons = new Map();
    for (const r of data.kitSku) {
      if (data.kitById.get(r.kit_id)?.station_id !== station) continue;
      cartons.set(r.sku, (cartons.get(r.sku) ?? 0) + (r.cartons_needed ?? 0));
    }
  }
  return data.skus.map((s) => {
    const c = byStation ? (cartons.get(s.sku) ?? 0) : s.cartons_needed;
    const n = nWin.get(s.sku) ?? 0;
    const nA = nAll.get(s.sku) ?? 0;
    return {
      ...s,
      n_trips: n,
      cartons_needed: c,
      trips_per_carton: c > 0 ? n / c : null,
      partial_share: byStation ? (nA ? (nPartAll.get(s.sku) ?? 0) / nA : null) : s.partial_share,
    };
  });
}

export class SkuScatter {
  constructor(root, store) {
    this.root = root;
    this.store = store;
    this.deps = ['dataVersion', 'timeWindow', 'station', 'selectedSkus', 'selectedKit', 'minCartons'];
    // 카드 머리의 "Min cartons needed" 입력
    this.minInput = root.closest('.card')?.querySelector('#v4-min-cartons') ?? null;
    this.minInput?.addEventListener('input', () => this.onMinInput());
    this.caption = d3.select(root).append('div').attr('class', 'v4-caption');
    this.svg = d3.select(root).append('svg');
    this.status = d3.select(root).append('div').attr('class', 'v4-status');
    this.legend = d3.select(root).append('div').attr('class', 'legend-row');
    this.width = root.clientWidth || 520;
    onResize(root, (w) => {
      this.width = w;
      if (this.data) this.render();
    });
  }

  setData(data) {
    this.data = data;
    this.rMax = d3.max(data.skus, (s) => s.cartons_needed) || 1;
    this.xMax = d3.max(data.skus, (s) => s.n_totes_init) || 1;
  }

  update(state, changed) {
    if (!this.drawn || ['dataVersion', 'timeWindow', 'station', 'minCartons'].some((k) => changed.has(k))) {
      this.render();
      return;
    }
    this.applyStyles();
  }

  onMinInput() {
    const raw = this.minInput.value;
    const v = Number(raw);
    if (raw === '' || !Number.isFinite(v) || v < 0) return; // 입력 중인 빈 값 등은 무시
    const patch = { minCartons: v };
    // brush 로 고른 선택이면 같은 상자 안에서 새 기준을 넘는 SKU 로 다시 고른다 (점 위치는 기준과 무관하다)
    if (this.store.state.skuSource === 'v4' && this.brushData && this.pts) {
      const [[a0, b0], [a1, b1]] = this.brushData;
      patch.selectedSkus = this.pts
        .filter((p) => p.cartons_needed >= v
          && p.n_totes_init >= a0 && p.n_totes_init <= a1
          && p.trips_per_carton <= b0 && p.trips_per_carton >= b1)
        .map((p) => p.sku);
    }
    this.store.set(patch);
  }

  render() {
    const { data, store } = this;
    const st = store.state;
    const innerW = Math.max(160, this.width - M.left - M.right);
    const innerH = Math.max(180, Math.min(300, innerW * 0.62));
    const svg = this.svg.attr('width', this.width).attr('height', M.top + innerH + M.bottom);
    svg.selectAll('*').remove();

    // 크기만 바뀐 다시 그리기면 brush 상자를 데이터 좌표로 되살린다 (점 위치가 그대로이므로)
    const scope = JSON.stringify([st.timeWindow, st.station, data.id]);
    const restore = st.skuSource === 'v4' && this.brushData && this.scope === scope ? this.brushData : null;
    this.scope = scope;
    if (!restore) this.brushData = null;

    const all = skuStats(data, st);
    const pts = all.filter((s) => s.trips_per_carton != null);
    const nHidden = all.length - pts.length;

    // 분모(필요 카톤)가 작은 SKU 는 흐리게. 상관계수와 brush 는 기준 이상만 쓴다.
    const minC = st.minCartons;
    const eligible = pts.filter((p) => p.cartons_needed >= minC);
    const nFaded = pts.length - eligible.length;
    const rho = spearman(eligible.map((p) => p.n_totes_init), eligible.map((p) => p.trips_per_carton));
    if (this.minInput && document.activeElement !== this.minInput) this.minInput.value = minC;

    const x = d3.scaleLinear().domain([0, this.xMax]).nice().range([0, innerW]);
    const yMax = Math.max(0.1, d3.max(pts, (s) => s.trips_per_carton) ?? 0.1);
    const y = d3.scaleLinear().domain([0, yMax * 1.05]).nice().range([innerH, 0]);
    const r = d3.scaleSqrt().domain([0, this.rMax]).range([0, 13]);

    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);
    g.append('g').attr('class', 'grid').call(d3.axisLeft(y).ticks(5).tickSize(-innerW).tickFormat(''))
      .call((s) => s.select('.domain').remove());
    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${innerH})`)
      .call(d3.axisBottom(x).ticks(Math.max(3, innerW / 70)).tickSizeOuter(0));
    g.append('g').attr('class', 'axis').call(d3.axisLeft(y).ticks(5).tickSizeOuter(0));
    g.append('text').attr('class', 'axis-title').attr('x', innerW / 2).attr('y', innerH + 34)
      .attr('text-anchor', 'middle').text('Totes holding the SKU at shift start');
    g.append('text').attr('class', 'axis-title')
      .attr('transform', `translate(${-38},${innerH / 2}) rotate(-90)`)
      .attr('text-anchor', 'middle').text('Trips per carton needed');
    g.append('text').attr('class', 'faded-note').attr('x', 0).attr('y', innerH + 54)
      .text(`Faded: ${nFaded} SKU${nFaded === 1 ? '' : 's'} below ${fmtCartons(minC)} cartons (ratio unreliable)`);

    for (const p of pts) {
      p.cx = x(p.n_totes_init);
      p.cy = y(p.trips_per_carton);
      p.r = Math.max(2, r(p.cartons_needed));
    }
    pts.sort((a, b) => b.r - a.r); // 작은 점이 위에
    this.pts = pts;

    this.rings = g.append('g').selectAll('circle').data(pts, (p) => p.sku).join('circle')
      .attr('cx', (p) => p.cx).attr('cy', (p) => p.cy).attr('r', (p) => p.r + 2.5)
      .attr('fill', 'none').attr('stroke', C.blue).attr('stroke-width', 1.6).attr('display', 'none');
    this.dots = g.append('g').selectAll('circle').data(pts, (p) => p.sku).join('circle')
      .attr('cx', (p) => p.cx).attr('cy', (p) => p.cy).attr('r', (p) => p.r)
      .attr('fill', (p) => (p.partial_share != null && p.partial_share >= 0.5 ? C.partial : C.normal))
      .attr('stroke', C.card).attr('stroke-width', 0.8);
    this.hoverRing = g.append('circle').attr('fill', 'none').attr('stroke', C.ink).attr('stroke-width', 1.5)
      .attr('pointer-events', 'none').attr('display', 'none');

    // 기준 이상 SKU 의 x, y Spearman 상관계수 (오른쪽 위)
    g.append('text').attr('class', 'stat-note').attr('x', innerW - 4).attr('y', 12).attr('text-anchor', 'end')
      .text(`ρ = ${rho == null ? '–' : d3.format('.2f')(rho)} (n = ${eligible.length})`);
    this.minC = minC;

    // --- 2D brush + 가까운 점 호버 (brush 가 점 위를 덮으므로 Delaunay 로 찾는다) ----------------
    const delaunay = d3.Delaunay.from(pts, (p) => p.cx, (p) => p.cy);
    this.brush = d3.brush()
      .extent([[0, 0], [innerW, innerH]])
      .on('end', (ev) => {
        if (!ev.sourceEvent) return;
        const s = ev.selection;
        if (!s) {
          this.brushData = null;
          store.set({ selectedSkus: [], skuSource: null, selectedTrip: null });
          return;
        }
        const [[x0, y0], [x1, y1]] = s;
        this.brushData = [[x.invert(x0), y.invert(y0)], [x.invert(x1), y.invert(y1)]];
        const skus = eligible.filter((p) => p.cx >= x0 && p.cx <= x1 && p.cy >= y0 && p.cy <= y1).map((p) => p.sku);
        store.set({ selectedSkus: skus, skuSource: 'v4', selectedTrip: null });
      });
    const gBrush = g.append('g').attr('class', 'brush').call(this.brush);
    if (restore) gBrush.call(this.brush.move, restore.map(([a, b]) => [x(a), y(b)]));
    gBrush
      .on('pointermove.hover', (ev) => {
        const [mx, my] = d3.pointer(ev, g.node());
        const i = delaunay.find(mx, my);
        const p = pts[i];
        if (p && Math.hypot(p.cx - mx, p.cy - my) <= p.r + HOVER_PX) {
          this.hoverRing.attr('display', null).attr('cx', p.cx).attr('cy', p.cy).attr('r', p.r + 1);
          this.tip(ev, p);
        } else {
          this.hoverRing.attr('display', 'none');
          hideTip();
        }
      })
      .on('pointerleave.hover', () => {
        this.hoverRing.attr('display', 'none');
        hideTip();
      });
    // 시간 창이나 스테이션이 바뀌면 점이 다시 놓이므로 brush 상자는 지운다 (선택한 SKU 집합은 그대로 유지)
    this.gBrush = gBrush;

    // --- 캡션, 범례 -----------------------------------------------------------
    const w = st.timeWindow;
    const byStation = st.station !== 'all';
    const parts = [
      w ? `trips in ${fmtClock(w[0])}–${fmtClock(w[1])}` : 'trips over the whole shift',
      byStation ? `station ${stationLabel(st.station)} only` : 'all stations',
    ];
    const hidden = nHidden ? ` · ${nHidden} SKUs not needed${byStation ? ' at this station' : ''} are not shown` : '';
    this.caption.html(`y counts ${parts.join(' · ')}${hidden}`);
    const sizes = [Math.round(this.rMax / 10), Math.round(this.rMax / 2), Math.round(this.rMax)].filter((v) => v > 0);
    this.legend.html(
      `<span><i class="dot" style="background:${C.partial}"></i>≥ 50% of picks were partial cartons</span>`
      + `<span><i class="dot" style="background:${C.normal}"></i>&lt; 50%</span>`
      + `<span class="size-legend">Size = cartons needed ${sizes.map((v) => `<i class="dot hollow" style="width:${2 * r(v)}px;height:${2 * r(v)}px"></i>${fmtInt(v)}`).join(' ')}</span>`
      + `<span><i class="dot ring" style="border-color:${C.blue}"></i>Needed by the selected kit</span>`,
    );

    this.drawn = true;
    this.applyStyles();
  }

  applyStyles() {
    const st = this.store.state;
    const sel = new Set(st.selectedSkus);
    const kitSkus = new Set((this.data.skusByKit.get(st.selectedKit) ?? []).map((r) => r.sku));
    const faded = (p) => p.cartons_needed < this.minC;
    this.dots.attr('opacity', (p) => {
      if (faded(p)) return FADED_OPACITY;
      if (sel.size) return sel.has(p.sku) ? 1 : 0.15;
      if (kitSkus.size) return kitSkus.has(p.sku) ? 1 : 0.25;
      return 0.9;
    });
    this.rings
      .attr('display', (p) => (kitSkus.has(p.sku) ? null : 'none'))
      .attr('opacity', (p) => (faded(p) ? FADED_OPACITY : 1));
    if (sel.size) this.dots.filter((p) => sel.has(p.sku)).raise();

    // V3 트립 클릭으로 바뀐 선택이면 brush 상자를 지운다
    if (st.skuSource !== 'v4') this.gBrush.call(this.brush.move, null);

    const shown = this.pts.filter((p) => sel.has(p.sku)).length;
    const from = st.skuSource === 'v3' && st.selectedTrip != null ? ` from trip #${st.selectedTrip}` : '';
    this.status.html(sel.size
      ? `<b>${sel.size}</b> SKU${sel.size > 1 ? 's' : ''} selected${from}${shown < sel.size ? ` (${shown} shown)` : ''} → trips carrying them are highlighted in V1 <button class="link" type="button">Clear</button>`
      : '<span class="muted">Drag a box to select SKUs; their trips are highlighted in V1.</span>');
    this.status.select('button').on('click', () => {
      this.store.set({ selectedSkus: [], skuSource: null, selectedTrip: null });
    });
  }

  tip(ev, p) {
    showTip(ev, tipRows(p.sku, [
      ['Totes holding it', fmtInt(p.n_totes_init)],
      ['Trips', fmtInt(p.n_trips)],
      ['Cartons needed', fmtNum(p.cartons_needed, 1)],
      ['Trips / carton', fmtNum(p.trips_per_carton, 2)],
      ['Partial-carton picks', fmtPct(p.partial_share)],
      ['Lot size', p.lot_size ?? '–'],
      p.cartons_needed < this.minC
        ? ['', `<span class="muted">Below ${fmtCartons(this.minC)} cartons — ratio unreliable, not selectable</span>`]
        : null,
    ]));
  }
}
