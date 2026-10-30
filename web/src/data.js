// 정적 JSON 읽기. 경로는 페이지 기준 상대 경로라 dev 서버와 빌드 결과 모두에서 동작한다.
import * as d3 from 'd3';

async function getJSON(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

export const loadIndex = () => getJSON('data/index.json');

export async function loadDataset(id) {
  const base = `data/${id}/`;
  const [meta, trips, kits, kitSku, busy, skus] = await Promise.all(
    ['meta', 'trips', 'kits', 'kit_sku', 'busy_bins', 'skus'].map((f) => getJSON(`${base}${f}.json`)),
  );

  // 자주 쓰는 색인
  const kitById = new Map(kits.map((k) => [k.kit_id, k]));
  const tripsByKit = d3group(trips, (t) => t.kit_id);
  const skusByKit = d3group(kitSku, (r) => r.kit_id);
  const stations = meta.stations;

  // V4 "Min cartons needed" 기본값: SKU별 필요 카톤(교대 전체) 분포의 하위 25% 값, 정수로 반올림, 최소 1
  const cartons = skus.map((s) => s.cartons_needed).filter((c) => c > 0).sort(d3.ascending);
  const defaultMinCartons = Math.max(1, Math.round(d3.quantile(cartons, 0.25) ?? 1));

  return { id, meta, trips, kits, kitSku, busy, skus, kitById, tripsByKit, skusByKit, stations, defaultMinCartons };
}

function d3group(rows, key) {
  const m = new Map();
  for (const r of rows) {
    const k = key(r);
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  }
  return m;
}
