// V3 Kit trace: 선택된 키트 하나의 진행률 계단선 + 트립 글리프 줄
import * as d3 from 'd3';
import {
  C, fmtClock, fmtDur, fmtInt, fmtNum, stationLabel, timeTicks, kitInWindow, tripInWindow,
  showTip, hideTip, tipRows, onResize,
} from '../util.js';

const M = { top: 22, right: 18, bottom: 28, left: 46 };
const PLOT_H = 170;
const GLYPH_GAP = 12;
const GLYPH_H = 16;

export class KitTrace {
  constructor(root, store) {
    this.root = root;
    this.store = store;
    this.deps = ['dataVersion', 'selectedKit', 'lateOnly', 'station', 'timeWindow', 'hoveredTrip', 'selectedTrip'];
    const head = d3.select(root).append('div').attr('class', 'v3-head');
    this.select = head.append('select').attr('class', 'kit-select').attr('aria-label', 'Kit')
      .on('change', (ev) => store.set({ selectedKit: ev.target.value || null }));
    this.summary = head.append('div').attr('class', 'v3-summary');
    this.svg = d3.select(root).append('svg');
    this.empty = d3.select(root).append('div').attr('class', 'empty-state');
    this.legend = d3.select(root).append('div').attr('class', 'legend-row');
    this.width = root.clientWidth || 420;
    onResize(root, (w) => {
      this.width = w;
      if (this.data) this.render();
    });
  }

  setData(data) {
    this.data = data;
  }

  update(state, changed) {
    if (['dataVersion', 'lateOnly', 'station', 'timeWindow', 'selectedKit'].some((k) => changed.has(k))) {
      this.renderSelect();
    }
    if (!this.drawn || ['dataVersion', 'selectedKit', 'station'].some((k) => changed.has(k))) {
      this.render();
      return;
    }
    this.applyStyles();
  }

  /** 키트 선택 목록: Late kits only, Station, 시간 창을 적용한다. 선택된 키트는 항상 남긴다. */
  renderSelect() {
    const st = this.store.state;
    const kits = this.data.kits.filter((k) => k.start != null
      && (!st.lateOnly || k.late)
      && (st.station === 'all' || k.station_id === st.station)
      && kitInWindow(k, st.timeWindow));
    const n = kits.length;
    const sel = this.data.kitById.get(st.selectedKit);
    if (sel && !kits.includes(sel)) kits.unshift(sel);
    kits.sort((a, b) => a.start - b.start);

    const opts = [{ value: '', label: n ? `Choose a kit (${n} listed)` : 'No kits match the filters' }, ...kits.map((k) => ({
      value: k.kit_id,
      label: `${k.kit_id} · ${stationLabel(k.station_id)} · ${fmtClock(k.start)} · ${k.late ? `late ${fmtDur(k.tardiness)}` : 'on time'}`,
    }))];
    this.select.selectAll('option').data(opts, (o) => o.value).join('option')
      .attr('value', (o) => o.value).text((o) => o.label);
    this.select.property('value', st.selectedKit ?? '');
  }

  render() {
    const { data, store } = this;
    const st = store.state;
    const kit = data.kitById.get(st.selectedKit);
    this.svg.selectAll('*').remove();
    this.kit = kit;

    if (!kit) {
      this.drawn = true;
      this.svg.attr('height', 0);
      this.summary.html('');
      this.legend.html('');
      const noLate = st.lateOnly && !data.kits.some((k) => k.late);
      this.empty.attr('hidden', null).html(noLate
        ? '<strong>No late kits in this run.</strong><span>Turn off “Late kits only” or pick another run.</span>'
        : '<strong>Click a kit in V1</strong><span>or choose one from the list above.</span>');
      return;
    }
    this.empty.attr('hidden', true);

    const kEnd = kit.end ?? data.meta.t_end;
    const trips = (data.tripsByKit.get(kit.kit_id) ?? []).filter((t) => t.t_dock != null);
    const nPartial = trips.filter((t) => t.partial_picks > 0).length;
    this.summary.html(
      `<b>${kit.kit_id}</b> at ${stationLabel(kit.station_id)} · ${kit.n_trips} trips · ${kit.n_sku_required} SKUs · `
      + `${fmtInt(kit.qty_required)} parts · `
      + (kit.late ? `<span class="late-text">late by ${fmtDur(kit.tardiness)}</span>` : `on time (${fmtDur(-kit.lateness)} early)`),
    );

    const innerW = Math.max(160, this.width - M.left - M.right);
    const glyphY = PLOT_H + GLYPH_GAP;
    const innerH = glyphY + GLYPH_H;
    const svg = this.svg.attr('width', this.width).attr('height', M.top + innerH + M.bottom);

    const t0 = Math.min(kit.start, kit.deadline);
    const t1 = Math.max(kEnd, kit.deadline);
    const pad = (t1 - t0) * 0.04 || 60;
    const x = d3.scaleLinear().domain([t0 - pad, t1 + pad]).range([0, innerW]);
    const y = d3.scaleLinear().domain([0, 1]).range([PLOT_H, 0]);
    this.x = x;

    const uid = Math.random().toString(36).slice(2, 8);
    const defs = svg.append('defs');
    defs.append('clipPath').attr('id', `v3-before-${uid}`).append('rect')
      .attr('x', -2).attr('y', -10).attr('width', Math.max(0, x(kit.deadline) + 2)).attr('height', PLOT_H + 20);
    defs.append('clipPath').attr('id', `v3-after-${uid}`).append('rect')
      .attr('x', x(kit.deadline)).attr('y', -10).attr('width', Math.max(0, innerW - x(kit.deadline) + 4)).attr('height', PLOT_H + 20);

    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

    // 시간 창 띠 (뒤에 깔기)
    this.windowBand = g.append('rect').attr('class', 'window-band')
      .attr('y', -6).attr('height', innerH + 8).attr('fill', C.blue).attr('fill-opacity', 0.07);

    // y 격자, 축
    g.append('g').attr('class', 'grid')
      .call(d3.axisLeft(y).tickValues([0, 0.25, 0.5, 0.75, 1]).tickSize(-innerW).tickFormat(''))
      .call((s) => s.select('.domain').remove());
    g.append('g').attr('class', 'axis')
      .call(d3.axisLeft(y).tickValues([0, 0.5, 1]).tickFormat(d3.format('.0%')).tickSizeOuter(0));
    g.append('text').attr('class', 'axis-title').attr('x', -M.left + 4).attr('y', -9).text('Kit filled');

    // 목표 진행선 (start, 0) -> (deadline, 100%)
    if (!kit.released_late) {
      g.append('line').attr('class', 'target-line')
        .attr('x1', x(kit.start)).attr('y1', y(0)).attr('x2', x(kit.deadline)).attr('y2', y(1))
        .attr('stroke', C.ink).attr('stroke-opacity', 0.4).attr('stroke-dasharray', '1 3');
    }

    // 진행률 계단선: 납기 전 파랑, 납기 뒤 주황
    const pts = kit.progress.slice();
    const area = d3.area().curve(d3.curveStepAfter).x((d) => x(d[0])).y0(y(0)).y1((d) => y(d[1]));
    const line = d3.line().curve(d3.curveStepAfter).x((d) => x(d[0])).y((d) => y(d[1]));
    for (const [part, color] of [['before', C.blue], ['after', C.late]]) {
      const gp = g.append('g').attr('clip-path', `url(#v3-${part}-${uid})`);
      gp.append('path').attr('d', area(pts)).attr('fill', color).attr('fill-opacity', 0.1);
      gp.append('path').attr('d', line(pts)).attr('fill', 'none').attr('stroke', color).attr('stroke-width', 2.2);
    }
    g.append('circle').attr('cx', x(kEnd)).attr('cy', y(1)).attr('r', 3)
      .attr('fill', kit.late ? C.late : C.blue);

    // 납기 점선
    g.append('line').attr('x1', x(kit.deadline)).attr('x2', x(kit.deadline)).attr('y1', -6).attr('y2', innerH)
      .attr('stroke', C.ink).attr('stroke-width', 1.2).attr('stroke-dasharray', '4 3');
    const dlRight = x(kit.deadline) > innerW * 0.7;
    g.append('text').attr('class', 'annot')
      .attr('x', x(kit.deadline) + (dlRight ? -4 : 4)).attr('y', -9)
      .attr('text-anchor', dlRight ? 'end' : 'start')
      .text(`deadline ${fmtClock(kit.deadline)}`);

    // slip 표시 (늦은 키트만)
    if (kit.late && kit.slip_start != null) {
      const sx = x(kit.slip_start);
      const sy = kit.released_late ? y(0)
        : y(Math.min(1, (kit.slip_start - kit.start) / (kit.deadline - kit.start)));
      // 납기 뒤에 투입된 키트는 표시가 0% 에 붙으므로 세로선을 위까지 올리고 라벨을 위에 단다
      const labelY = kit.released_late ? 12 : Math.max(12, sy - 8);
      g.append('line').attr('x1', sx).attr('x2', sx).attr('y1', kit.released_late ? 4 : sy).attr('y2', PLOT_H)
        .attr('stroke', C.late).attr('stroke-width', 1.2).attr('stroke-dasharray', '2 2');
      g.append('circle').attr('cx', sx).attr('cy', sy).attr('r', 4.5)
        .attr('fill', C.card).attr('stroke', C.late).attr('stroke-width', 2);
      const right = sx > innerW * 0.6;
      g.append('text').attr('class', 'annot late-text')
        .attr('x', sx + (right ? -8 : 8)).attr('y', labelY)
        .attr('text-anchor', right ? 'end' : 'start')
        .text(`slipped at ${fmtClock(kit.slip_start)}${kit.released_late ? ' (released after deadline)' : ''}`);
    }

    // 트립 글리프 줄
    g.append('text').attr('class', 'lane-label').attr('x', -6).attr('y', glyphY + GLYPH_H / 2 + 4).text('trips');
    g.append('line').attr('x1', 0).attr('x2', innerW).attr('y1', glyphY + GLYPH_H + 0.5).attr('y2', glyphY + GLYPH_H + 0.5)
      .attr('stroke', C.grid);
    // 도킹 대기 (t_wait -> t_dock) 를 가는 선으로
    this.waitL = g.selectAll('line.wait').data(trips.filter((t) => t.dock_wait > 0)).join('line')
      .attr('class', 'wait')
      .attr('x1', (t) => x(t.t_wait)).attr('x2', (t) => x(t.t_dock))
      .attr('y1', glyphY + GLYPH_H / 2).attr('y2', glyphY + GLYPH_H / 2)
      .attr('stroke', C.ink).attr('stroke-opacity', 0.35);
    this.glyphs = g.selectAll('rect.glyph').data(trips, (t) => t.trip_id).join('rect')
      .attr('class', 'glyph')
      .attr('x', (t) => x(t.t_dock))
      .attr('width', (t) => Math.max(2.5, x(t.t_kit_end) - x(t.t_dock) - 0.5))
      .attr('y', glyphY).attr('height', GLYPH_H)
      .attr('fill', (t) => (t.partial_picks > 0 ? C.partial : C.normal))
      .on('mouseenter', (ev, t) => {
        store.set({ hoveredTrip: t.trip_id });
        this.tip(ev, t);
      })
      .on('mousemove', (ev, t) => this.tip(ev, t))
      .on('mouseleave', () => {
        store.set({ hoveredTrip: null });
        hideTip();
      })
      .on('click', (ev, t) => {
        if (store.state.selectedTrip === t.trip_id) {
          store.set({ selectedTrip: null, selectedSkus: [], skuSource: null });
        } else {
          store.set({ selectedTrip: t.trip_id, selectedSkus: Object.keys(t.matched_parts), skuSource: 'v3' });
        }
      });

    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${innerH + 2})`)
      .call(d3.axisBottom(x).tickValues(timeTicks(x.domain(), innerW / 70)).tickFormat(fmtClock).tickSizeOuter(0));

    this.legend.html(
      `<span><i class="sw" style="background:${C.partial}"></i>Trip with a partial-carton pick (${nPartial})</span>`
      + `<span><i class="sw" style="background:${C.normal}"></i>Full cartons only (${trips.length - nPartial})</span>`
      + `<span><i class="ln" style="border-color:${C.ink}"></i>Dock wait</span>`
      + (kit.released_late ? '' : '<span><i class="ln dotted"></i>Target pace</span>')
      + `<span><i class="ln" style="border-color:${C.late}"></i>After deadline</span>`
      + '<span class="muted">Click a trip to highlight its SKUs in V4</span>',
    );

    this.drawn = true;
    this.applyStyles();
  }

  applyStyles() {
    if (!this.kit) return;
    const st = this.store.state;
    const w = st.timeWindow;
    const [d0, d1] = this.x.domain();
    if (w && w[1] > d0 && w[0] < d1) {
      const a = this.x(Math.max(w[0], d0));
      this.windowBand.attr('display', null).attr('x', a).attr('width', Math.max(1, this.x(Math.min(w[1], d1)) - a));
    } else {
      this.windowBand.attr('display', 'none');
    }
    this.glyphs
      .attr('opacity', (t) => (tripInWindow(t, w) ? 1 : 0.25))
      .attr('stroke', (t) => (t.trip_id === st.hoveredTrip || t.trip_id === st.selectedTrip ? C.blue : null))
      .attr('stroke-width', (t) => (t.trip_id === st.selectedTrip ? 2.5 : t.trip_id === st.hoveredTrip ? 1.5 : null));
    this.waitL.attr('opacity', (t) => (tripInWindow(t, w) ? 1 : 0.25));
  }

  tip(ev, t) {
    showTip(ev, tipRows(`Trip #${t.trip_id}`, [
      ['Tote', t.tote_id],
      ['Distance', `${fmtNum(t.distance_m, 1)} m`],
      ['Dock wait', fmtDur(t.dock_wait)],
      ['Matched qty', fmtInt(t.matched_qty)],
      ['Partial picks', `${t.partial_picks} of ${Object.keys(t.matched_parts).length} SKUs`],
      ['Docked', `${fmtClock(t.t_dock)} – ${fmtClock(t.t_kit_end)}`],
    ]));
  }
}
