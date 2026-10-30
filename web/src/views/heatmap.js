// V2 Congestion heatmap: 행 = 스테이션들 + AMR fleet, 열 = 5분 구간, 명도 = 가동 비율 (고정 도메인 [0, 1])
// 스테이션 셀 가운데 점 = 평균 대기 AMR 수 (면적 비례). 가동 비율이 100%에서 멈춰도 대기가 쌓인 정도가 보이게.
import * as d3 from 'd3';
import { C, HEAT, fmtClock, fmtNum, fmtPct, stationLabel, timeTicks, showTip, hideTip, tipRows, onResize } from '../util.js';

const M = { top: 66, right: 12, bottom: 30, left: 74 };
const ROW_H = 24;
const FLEET_GAP = 6; // 스테이션 행과 AMR fleet 행 사이
const Q_LEGEND = [0.25, 0.5, 1]; // 점 크기 범례 (AMR 수). 스테이션 AGV 상한이 2라 평균 대기는 1을 넘기 어렵다

export class Heatmap {
  constructor(root, store) {
    this.root = root;
    this.store = store;
    this.deps = ['dataVersion', 'timeWindow', 'station', 'focusRow', 'focusCell'];
    this.svg = d3.select(root).append('svg');
    this.width = root.clientWidth || 360;
    this.color = d3.scaleQuantize().domain([0, 1]).range(HEAT);
    onResize(root, (w) => {
      this.width = w;
      if (this.data) this.render();
    });
  }

  setData(data) {
    this.data = data;
  }

  update(state, changed) {
    if (!this.drawn || changed.has('dataVersion') || changed.has('station')) {
      this.render();
      return;
    }
    this.applyStyles();
  }

  render() {
    const { data, store } = this;
    const st = store.state;
    const busy = data.busy;
    const rows = busy.rows.filter((r) => r.kind === 'fleet' || st.station === 'all' || r.id === st.station);
    const innerW = Math.max(120, this.width - M.left - M.right);
    const nSt = rows.filter((r) => r.kind === 'station').length;
    const innerH = rows.length * ROW_H + FLEET_GAP;
    const rowY = (r, i) => i * ROW_H + (r.kind === 'fleet' ? FLEET_GAP : 0);

    const x = d3.scaleLinear().domain([0, busy.t_end]).range([0, innerW]);
    this.x = x;

    // 점 크기: 면적 ∝ 평균 대기 AMR 수. 도메인은 1 AMR 로 고정해 실행끼리 비교할 수 있게 한다 (넘으면 늘린다).
    // 가장 큰 점의 지름 = 5분 셀 폭, 이웃 셀과 겹치지 않게.
    const hasQueue = !!busy.queue_available;
    const cellW = x(busy.bin_sec) - x(0);
    const rMax = Math.max(1.5, Math.min(cellW - 0.5, ROW_H - 4) / 2);
    const qScale = d3.scaleSqrt().domain([0, Math.max(1, busy.queue_max ?? 0)]).range([0, rMax]);

    const svg = this.svg.attr('width', this.width).attr('height', M.top + innerH + M.bottom);
    svg.selectAll('*').remove();

    // --- 범례: 5단계 + 0%, 100% ---------------------------------------------
    const lg = svg.append('g').attr('transform', `translate(${M.left},8)`);
    const sw = Math.min(26, innerW / 8);
    lg.append('text').attr('class', 'legend-title').attr('x', 0).attr('y', 11).text('Utilization');
    const lx = 72;
    lg.selectAll('rect').data(HEAT).join('rect')
      .attr('x', (d, i) => lx + i * sw).attr('y', 2).attr('width', sw).attr('height', 11)
      .attr('fill', (d) => d);
    lg.append('rect').attr('x', lx).attr('y', 2).attr('width', sw * 5).attr('height', 11)
      .attr('fill', 'none').attr('stroke', C.grid);
    lg.append('text').attr('class', 'legend-tick').attr('x', lx).attr('y', 25).attr('text-anchor', 'start').text('0%');
    lg.append('text').attr('class', 'legend-tick').attr('x', lx + sw * 5).attr('y', 25).attr('text-anchor', 'end').text('100%');
    lg.append('text').attr('class', 'legend-note').attr('x', lx + sw * 5 + 10).attr('y', 11)
      .text('5-min bins');

    // 점 크기 범례: 진한 셀 위에 실제 크기 점 (점 색이 배경색이라 카드 위에서는 안 보인다)
    if (hasQueue) {
      const qg = lg.append('g').attr('transform', 'translate(0,34)');
      qg.append('text').attr('class', 'legend-title').attr('x', 0).attr('y', 11).text('Waiting');
      const box = Math.max(12, 2 * rMax + 6);
      let qx = lx;
      for (const v of Q_LEGEND) {
        qg.append('rect').attr('x', qx).attr('y', 7 - box / 2).attr('width', box).attr('height', box)
          .attr('fill', HEAT[4]);
        qg.append('circle').attr('cx', qx + box / 2).attr('cy', 7).attr('r', qScale(v)).attr('fill', C.bg);
        qg.append('text').attr('class', 'legend-tick').attr('x', qx + box + 4).attr('y', 11).text(v);
        qx += box + 30;
      }
      qg.append('text').attr('class', 'legend-note').attr('x', qx - 4).attr('y', 11).text('AMRs (avg)');
    }

    const g = svg.append('g').attr('transform', `translate(${M.left},${M.top})`);

    // 행 라벨
    this.labels = svg.append('g').attr('transform', `translate(0,${M.top})`)
      .selectAll('text').data(rows).join('text')
      .attr('class', 'row-label small')
      .attr('x', 8)
      .attr('y', (r, i) => rowY(r, i) + ROW_H / 2 + 4)
      .text((r) => (r.kind === 'fleet' ? 'AMR fleet' : stationLabel(r.id)));

    // 셀
    const cells = rows.flatMap((r, i) => r.values.map((v, k) => ({
      row: r, i, k, v, t0: busy.bin_starts[k], t1: busy.bin_starts[k] + busy.bin_lengths[k],
      q: r.queue?.[k] ?? null, qMax: r.max_queue?.[k] ?? null,
    })));
    this.cells = g.selectAll('rect.cell').data(cells).join('rect')
      .attr('class', 'cell')
      .attr('x', (d) => x(d.t0))
      .attr('y', (d) => rowY(d.row, d.i) + 1)
      .attr('width', (d) => Math.max(0.5, x(d.t1) - x(d.t0) - 0.5))
      .attr('height', ROW_H - 2)
      .attr('fill', (d) => this.color(d.v))
      .on('mouseenter', (ev, d) => this.tip(ev, d))
      .on('mousemove', (ev, d) => this.tip(ev, d))
      .on('mouseleave', hideTip)
      .on('click', (ev, d) => this.clickCell(d));

    // 대기 점: 스테이션 행만, 대기 0 이면 없음. 이벤트는 아래 셀이 받는다.
    this.dots = g.selectAll('circle.queue').data(cells.filter((d) => d.row.kind === 'station' && d.q > 0)).join('circle')
      .attr('class', 'queue')
      .attr('cx', (d) => (x(d.t0) + x(d.t1)) / 2)
      .attr('cy', (d) => rowY(d.row, d.i) + ROW_H / 2)
      .attr('r', (d) => qScale(d.q))
      .attr('fill', C.bg)
      .attr('pointer-events', 'none');

    // 선택된 셀 테두리 (파랑 = 선택)
    this.focusRect = g.append('rect').attr('fill', 'none').attr('stroke', C.blue).attr('stroke-width', 2)
      .attr('pointer-events', 'none').attr('display', 'none');
    this.rowY = rowY;
    this.rows = rows;

    g.append('g').attr('class', 'axis').attr('transform', `translate(0,${innerH + 2})`)
      .call(d3.axisBottom(x).tickValues(timeTicks(x.domain(), innerW / 45)).tickFormat(fmtClock).tickSizeOuter(0));

    this.drawn = true;
    this.applyStyles();
  }

  clickCell(d) {
    const { store } = this;
    const pad = this.data.busy.bin_sec; // 앞뒤로 한 구간씩 붙여서 15분 창
    const tEnd = this.data.busy.t_end;
    const cellKey = `${d.row.id}|${d.k}`;
    if (store.state.focusCell === cellKey) {
      store.set({ focusCell: null, focusRow: null });
      return;
    }
    store.set({
      focusCell: cellKey,
      focusRow: d.row.kind === 'station' ? d.row.id : null,
      timeWindow: [Math.max(0, d.t0 - pad), Math.min(tEnd, d.t1 + pad)],
    });
  }

  applyStyles() {
    const st = this.store.state;
    const w = st.timeWindow;
    const inWin = (d) => !w || (d.t1 > w[0] && d.t0 < w[1]);
    this.cells.attr('opacity', (d) => (inWin(d) ? 1 : 0.22));
    this.dots.attr('opacity', (d) => (inWin(d) ? 1 : 0.22));
    this.labels.classed('is-focus', (r) => r.id === st.focusRow);

    const fc = st.focusCell && this.cells.filter((d) => `${d.row.id}|${d.k}` === st.focusCell);
    if (fc && !fc.empty()) {
      const d = fc.datum();
      this.focusRect.attr('display', null)
        .attr('x', this.x(d.t0) - 1).attr('y', this.rowY(d.row, d.i))
        .attr('width', this.x(d.t1) - this.x(d.t0) + 1.5).attr('height', ROW_H);
    } else {
      this.focusRect.attr('display', 'none');
    }
  }

  tip(ev, d) {
    const fleet = d.row.kind === 'fleet';
    showTip(ev, tipRows(fleet ? 'AMR fleet' : `Station ${stationLabel(d.row.id)}`, [
      ['Time', `${fmtClock(d.t0)} – ${fmtClock(d.t1)}`],
      [fleet ? 'AMRs on trips' : 'Dock occupied', fmtPct(d.v)],
      fleet ? ['Fleet', `${d.row.n_agvs} AMRs`] : null,
      !fleet && d.q != null ? ['Avg AMRs waiting', fmtNum(d.q, 2)] : null,
      !fleet && d.qMax != null ? ['Max AMRs waiting', d.qMax] : null,
      ['', '<span class="muted">Click to zoom V1 here</span>'],
    ]));
  }
}
