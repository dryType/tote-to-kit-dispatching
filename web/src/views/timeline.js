// V1 Station timeline: 스테이션별 스윔레인 (위: 키트 막대, 아래: 도킹 레인의 트립 블록)
// 아래 overview 띠의 brush 와 본문 휠 zoom / 드래그로 시간 창을 고른다.
import * as d3 from 'd3';
import {
  C, fmtClock, fmtDur, stationLabel, timeTicks, tripHasSku, showTip, hideTip, tipRows, onResize,
} from '../util.js';

const M = { top: 24, right: 16, left: 74 };
const ROW_H = 56;
const KIT_Y = 10; // 행 안에서 키트 레인 위치
const KIT_H = 16;
const DOCK_Y = 32; // 도킹 레인 위치
const DOCK_H = 16;
const OV_GAP = 30; // 본문과 overview 사이 (본문 아래 여백 + overview 제목)
const OV_H = 30;
const OV_AXIS = 22;
const MIN_WINDOW = 120; // 가장 좁은 시간 창 (초)

export class Timeline {
  constructor(root, store) {
    this.root = root;
    this.store = store;
    this.deps = ['dataVersion', 'timeWindow', 'selectedKit', 'selectedSkus', 'lateOnly', 'station', 'hoveredTrip', 'focusRow'];
    this.svg = d3.select(root).append('svg').attr('class', 'v1-svg');
    this.width = root.clientWidth || 1000;
    this.origin = null; // 이번 시간 창 변경을 일으킨 컨트롤 ('brush' | 'zoom'), 그 컨트롤은 다시 맞추지 않는다
    onResize(root, (w) => {
      this.width = w;
      if (this.data) this.render();
    });
  }

  setData(data) {
    this.data = data;
    this.full = [0, data.meta.t_end];
  }

  update(state, changed) {
    if (!this.drawn || changed.has('dataVersion') || changed.has('station')) {
      this.render();
      return;
    }
    if (changed.has('timeWindow')) this.applyWindow();
    if (changed.has('lateOnly')) this.applyLateOnly();
    if (['selectedKit', 'selectedSkus', 'hoveredTrip', 'focusRow'].some((k) => changed.has(k))) this.applyStyles();
  }

  // -------------------------------------------------------------------------
  render() {
    const { data, store } = this;
    const st = store.state;
    const stations = data.stations.filter((s) => st.station === 'all' || s === st.station);
    this.stations = stations;
    const innerW = Math.max(200, this.width - M.left - M.right);
    const mainH = stations.length * ROW_H;
    const height = M.top + mainH + OV_GAP + OV_H + OV_AXIS;
    this.innerW = innerW;
    this.mainH = mainH;

    const rowY = new Map(stations.map((s, i) => [s, i * ROW_H]));
    this.rowY = rowY;
    this.x0 = d3.scaleLinear().domain(this.full).range([0, innerW]);
    this.x = this.x0.copy().domain(st.timeWindow ?? this.full);

    const svg = this.svg.attr('width', this.width).attr('height', height);
    svg.selectAll('*').remove();

    const clipId = `v1-clip-${Math.random().toString(36).slice(2, 8)}`;
    svg.append('defs').append('clipPath').attr('id', clipId)
      .append('rect').attr('x', 0).attr('y', -8).attr('width', innerW).attr('height', mainH + 8);

    // --- 행 배경, 라벨 ---------------------------------------------------------
    const gRows = svg.append('g').attr('transform', `translate(0,${M.top})`);
    this.rowBg = gRows.selectAll('rect.row-bg').data(stations).join('rect')
      .attr('class', 'row-bg')
      .attr('x', 0).attr('y', (s) => rowY.get(s))
      .attr('width', this.width).attr('height', ROW_H)
      .attr('fill', C.blue).attr('fill-opacity', 0);
    gRows.selectAll('line.row-sep').data(stations.slice(1)).join('line')
      .attr('class', 'row-sep')
      .attr('x1', 0).attr('x2', this.width)
      .attr('y1', (s) => rowY.get(s)).attr('y2', (s) => rowY.get(s))
      .attr('stroke', C.grid);
    this.rowLabel = gRows.selectAll('text.row-label').data(stations).join('text')
      .attr('class', 'row-label')
      .attr('x', 8).attr('y', (s) => rowY.get(s) + ROW_H / 2 + 5)
      .text(stationLabel);
    const sub = gRows.selectAll('g.lane-labels').data(stations).join('g')
      .attr('transform', (s) => `translate(${M.left - 8},${rowY.get(s)})`);
    sub.append('text').attr('class', 'lane-label').attr('y', KIT_Y + KIT_H / 2 + 4).text('kits');
    sub.append('text').attr('class', 'lane-label').attr('y', DOCK_Y + DOCK_H / 2 + 4).text('dock');

    // --- 위 시간 축 -----------------------------------------------------------
    this.gAxis = svg.append('g').attr('class', 'axis').attr('transform', `translate(${M.left},${M.top})`);

    // --- 본문 (zoom 대상) -------------------------------------------------------
    const gMain = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);
    this.gMain = gMain;
    gMain.append('rect').attr('class', 'zoom-capture')
      .attr('width', innerW).attr('height', mainH).attr('fill', 'transparent');
    const gClip = gMain.append('g').attr('clip-path', `url(#${clipId})`);

    // 레인 바닥선
    gClip.selectAll('line.lane-base').data(stations.flatMap((s) => [rowY.get(s) + KIT_Y + KIT_H, rowY.get(s) + DOCK_Y + DOCK_H]))
      .join('line').attr('class', 'lane-base')
      .attr('x1', 0).attr('x2', innerW).attr('y1', (y) => y + 0.5).attr('y2', (y) => y + 0.5)
      .attr('stroke', C.grid);

    // 키트 막대
    const kits = data.kits.filter((k) => k.start != null && rowY.has(k.station_id));
    this.kitG = gClip.selectAll('g.kit').data(kits, (k) => k.kit_id).join('g')
      .attr('class', 'kit')
      .attr('transform', (k) => `translate(0,${rowY.get(k.station_id) + KIT_Y})`)
      .on('mouseenter', (ev, k) => this.kitTip(ev, k))
      .on('mousemove', (ev, k) => this.kitTip(ev, k))
      .on('mouseleave', hideTip)
      .on('click', (ev, k) => {
        ev.stopPropagation();
        store.set({ selectedKit: store.state.selectedKit === k.kit_id ? null : k.kit_id });
      });
    this.kitG.append('rect').attr('class', 'k-on').attr('height', KIT_H)
      .attr('fill', C.blue).attr('fill-opacity', 0.16).attr('stroke', C.blue).attr('stroke-width', 0.9);
    this.kitG.append('rect').attr('class', 'k-late').attr('height', KIT_H).attr('fill', C.late);
    this.kitG.append('rect').attr('class', 'k-outline').attr('height', KIT_H + 4).attr('y', -2)
      .attr('fill', 'none').attr('stroke', C.ink).attr('stroke-width', 2).attr('rx', 2).attr('opacity', 0);
    this.kitG.append('line').attr('class', 'k-slack')
      .attr('y1', KIT_H / 2).attr('y2', KIT_H / 2)
      .attr('stroke', C.ink).attr('stroke-dasharray', '2 2').attr('opacity', 0);
    this.kitG.append('line').attr('class', 'k-deadline')
      .attr('y1', -7).attr('y2', -1).attr('stroke', C.ink).attr('stroke-width', 1.5);
    this.kitG.append('text').attr('class', 'k-label').attr('y', KIT_H / 2 + 4);

    // 도킹 레인 트립 블록
    const trips = data.trips.filter((t) => rowY.has(t.station_id) && t.t_dock != null);
    this.tripR = gClip.selectAll('rect.trip').data(trips, (t) => t.trip_id).join('rect')
      .attr('class', 'trip')
      .attr('y', (t) => rowY.get(t.station_id) + DOCK_Y)
      .attr('height', DOCK_H)
      .attr('fill', C.blue)
      .on('mouseenter', (ev, t) => {
        store.set({ hoveredTrip: t.trip_id });
        this.tripTip(ev, t);
      })
      .on('mousemove', (ev, t) => this.tripTip(ev, t))
      .on('mouseleave', () => {
        store.set({ hoveredTrip: null });
        hideTip();
      });

    // --- zoom ---------------------------------------------------------------
    const span = this.full[1] - this.full[0];
    this.zoom = d3.zoom()
      .scaleExtent([1, Math.max(1, span / MIN_WINDOW)])
      .extent([[0, 0], [innerW, mainH]])
      .translateExtent([[0, 0], [innerW, mainH]])
      .on('zoom', (ev) => {
        if (!ev.sourceEvent) return; // 코드에서 맞춘 변환
        const dom = ev.transform.rescaleX(this.x0).domain();
        this.setWindow(dom, 'zoom');
      });
    gMain.call(this.zoom).on('dblclick.zoom', null);

    // --- overview + brush ----------------------------------------------------
    const ovY = M.top + mainH + OV_GAP;
    svg.append('text').attr('class', 'ov-title').attr('x', M.left).attr('y', ovY - 7)
      .text('Overview — drag to select a time window, scroll the timeline to zoom');
    svg.append('text').attr('class', 'lane-label').attr('x', M.left - 8).attr('y', ovY + OV_H / 2 + 4).text('shift');
    const gOv = svg.append('g').attr('transform', `translate(${M.left},${ovY})`);
    gOv.append('rect').attr('width', innerW).attr('height', OV_H).attr('fill', C.bg);
    const ovRowH = Math.min(9, OV_H / Math.max(1, stations.length));
    const ovTop = (OV_H - ovRowH * stations.length) / 2;
    this.ovKits = gOv.selectAll('rect.ov-kit').data(kits).join('rect')
      .attr('class', 'ov-kit')
      .attr('x', (k) => this.x0(k.start))
      .attr('width', (k) => Math.max(1, this.x0(k.end ?? this.full[1]) - this.x0(k.start) - 1))
      .attr('y', (k) => ovTop + stations.indexOf(k.station_id) * ovRowH + 1)
      .attr('height', Math.max(2, ovRowH - 2))
      .attr('fill', (k) => (k.late ? C.late : C.blue))
      .attr('fill-opacity', (k) => (k.late ? 0.85 : 0.35));
    gOv.append('g').attr('class', 'axis').attr('transform', `translate(0,${OV_H})`)
      .call(d3.axisBottom(this.x0).tickValues(timeTicks(this.full, innerW / 70)).tickFormat(fmtClock).tickSizeOuter(0));

    this.brush = d3.brushX()
      .extent([[0, 0], [innerW, OV_H]])
      .on('brush end', (ev) => {
        if (!ev.sourceEvent) return;
        const s = ev.selection;
        this.setWindow(s ? s.map(this.x0.invert) : null, 'brush');
      });
    this.gBrush = gOv.append('g').attr('class', 'brush').call(this.brush);

    this.drawn = true;
    this.applyWindow();
    this.applyLateOnly();
    this.applyStyles();
  }

  setWindow(dom, origin) {
    let w = dom;
    if (w) {
      const [a, b] = w;
      if (b - a < MIN_WINDOW) {
        const mid = (a + b) / 2;
        w = [Math.max(this.full[0], mid - MIN_WINDOW / 2), Math.min(this.full[1], mid + MIN_WINDOW / 2)];
      }
      // 거의 전체면 창 없음으로 본다
      if (w[0] <= this.full[0] + 1 && w[1] >= this.full[1] - 1) w = null;
    }
    this.origin = origin;
    this.store.set({ timeWindow: w });
    this.origin = null;
  }

  // -------------------------------------------------------------------------
  applyWindow() {
    const w = this.store.state.timeWindow;
    const x = this.x.domain(w ?? this.full);

    this.gAxis.call(
      d3.axisTop(x).tickValues(timeTicks(x.domain(), this.innerW / 80)).tickFormat(fmtClock).tickSizeOuter(0),
    );

    const kEnd = (k) => k.end ?? this.full[1];
    this.kitG.select('rect.k-on')
      .attr('x', (k) => x(k.start))
      .attr('width', (k) => Math.max(0, x(Math.min(kEnd(k), Math.max(k.start, k.deadline))) - x(k.start)));
    this.kitG.select('rect.k-late')
      .attr('x', (k) => x(Math.max(k.start, k.deadline)))
      .attr('width', (k) => Math.max(0, x(kEnd(k)) - x(Math.max(k.start, k.deadline))));
    this.kitG.select('rect.k-outline')
      .attr('x', (k) => x(k.start) - 2)
      .attr('width', (k) => Math.max(0, x(kEnd(k)) - x(k.start)) + 4);
    this.kitG.select('line.k-deadline').attr('x1', (k) => x(k.deadline)).attr('x2', (k) => x(k.deadline));
    this.kitG.select('line.k-slack')
      .attr('x1', (k) => x(kEnd(k))).attr('x2', (k) => (k.deadline > kEnd(k) ? x(k.deadline) : x(kEnd(k))));
    // 라벨은 막대의 보이는 부분 왼쪽에 붙인다 (확대해서 막대 시작이 창 밖이어도 보이게)
    this.kitG.select('text.k-label')
      .attr('x', (k) => Math.max(x(k.start), 0) + 4)
      .text((k) => (Math.min(x(kEnd(k)), this.innerW) - Math.max(x(k.start), 0) > 64 ? k.kit_id.replace(/^KIT_/, '') : ''));

    this.tripR
      .attr('x', (t) => x(t.t_dock))
      .attr('width', (t) => Math.max(1, x(t.t_kit_end) - x(t.t_dock) - 0.5));

    // 컨트롤 맞추기 (변경을 일으킨 컨트롤은 건드리지 않는다)
    if (this.origin !== 'brush') {
      this.gBrush.call(this.brush.move, w ? w.map(this.x0) : null);
    }
    if (this.origin !== 'zoom') {
      const t = w
        ? d3.zoomIdentity.scale(this.innerW / (this.x0(w[1]) - this.x0(w[0]))).translate(-this.x0(w[0]), 0)
        : d3.zoomIdentity;
      this.gMain.call(this.zoom.transform, t);
    }
  }

  applyLateOnly() {
    const lateOnly = this.store.state.lateOnly;
    this.kitG.attr('display', (k) => (lateOnly && !k.late ? 'none' : null));
    this.ovKits.attr('display', (k) => (lateOnly && !k.late ? 'none' : null));
  }

  applyStyles() {
    const st = this.store.state;
    const skuSet = new Set(st.selectedSkus);
    this.tripR
      .attr('opacity', (t) => (skuSet.size && !tripHasSku(t, skuSet) ? 0.13 : 1))
      .attr('stroke', (t) => (t.trip_id === st.hoveredTrip ? C.ink : null))
      .attr('stroke-width', (t) => (t.trip_id === st.hoveredTrip ? 2 : null));
    if (st.hoveredTrip != null) this.tripR.filter((t) => t.trip_id === st.hoveredTrip).raise();

    this.kitG.select('rect.k-outline').attr('opacity', (k) => (k.kit_id === st.selectedKit ? 1 : 0));
    this.kitG.select('line.k-slack').attr('opacity', (k) => (k.kit_id === st.selectedKit ? 0.7 : 0));
    this.kitG.select('line.k-deadline').attr('stroke-width', (k) => (k.kit_id === st.selectedKit ? 2.5 : 1.5));
    if (st.selectedKit) this.kitG.filter((k) => k.kit_id === st.selectedKit).raise();

    this.rowBg.attr('fill-opacity', (s) => (s === st.focusRow ? 0.08 : 0));
    this.rowLabel.classed('is-focus', (s) => s === st.focusRow);
  }

  // -------------------------------------------------------------------------
  kitTip(ev, k) {
    const status = k.end == null
      ? ['Status', 'not completed']
      : k.late
        ? ['Status', `Late by ${fmtDur(k.tardiness)}`, 'late']
        : ['Status', `On time, ${fmtDur(-k.lateness)} early`];
    showTip(ev, tipRows(k.kit_id, [
      ['Station', stationLabel(k.station_id)],
      ['Kitting', `${fmtClock(k.start)} – ${fmtClock(k.end)}`],
      ['Deadline', fmtClock(k.deadline)],
      status,
      ['Trips', k.n_trips],
      ['', '<span class="muted">Click to trace in V3</span>'],
    ]));
  }

  tripTip(ev, t) {
    showTip(ev, tipRows(`Trip #${t.trip_id}`, [
      ['Tote', t.tote_id],
      ['Kit', t.kit_id],
      ['AMR', t.agv_id],
      ['Docked', `${fmtClock(t.t_dock)} – ${fmtClock(t.t_kit_end)} (${fmtDur(t.t_kit_end - t.t_dock)})`],
      ['Dock wait', fmtDur(t.dock_wait)],
      ['SKUs', `${Object.keys(t.matched_parts).length} (${t.partial_picks} partial-carton)`],
    ]));
  }
}
