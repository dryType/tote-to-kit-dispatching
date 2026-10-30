# Tote-to-Kit Dispatching

Discrete-event simulator (SimPy) of fixed-station kitting with AMRs: AMRs carry totes from storage to kitting stations,
and a dispatching policy decides which tote goes to which kit. `src/` holds the simulator and policies, `data/` the
instance generators.

## Tote-Kit Dispatch Trace (information visualization)

A web interface (D3 v7 + vanilla JS, built with Vite) for tracing one simulated shift:

| View | Shows | Interactions |
|---|---|---|
| V1 Station timeline | Kit bars (orange = past deadline, ink tick = deadline) and docked trips per station | Brush the overview or scroll to zoom → filters V2–V4; click a kit → V3; SKUs brushed in V4 highlight their trips |
| V2 Congestion heatmap | Dock occupancy per station and AMR fleet utilization in 5-min bins | Click a cell → V1 highlights the station and zooms to that time |
| V3 Kit trace | Fill progress of one kit against its deadline, slip point, one glyph per trip | Hover a trip for details; click a trip → its SKUs are selected in V4 and V1 |
| V4 SKU spread | Per SKU: totes holding it at shift start vs. trips per carton needed | 2D brush → selects SKUs; recomputes for the V1 time window and station filter |

Header controls: run (policy × load), "Late kits only", and a station filter.

### Requirements

- Python 3.14 (the codebase targets 3.14), with `simpy` and `pandas`
- Node.js 20.19+ (for Vite 8) — tested with Node 24.22.1

### 1. Generate simulation data

Runs the simulator on a generated instance and writes CSV tables to `vis_data/<size>_s<seed>_L<load>/<policy>/`.

```bash
# from the repository root
python src/simulation_engine/vis_export.py --size medium --seed 42 --load 0.8 --policies new_cpr --out vis_data
python src/simulation_engine/vis_export.py --size medium --seed 42 --load 1.0 --policies greedy cpr new_cpr --out vis_data
```

Each run prints `checks: all ok` when its validation passes (row counts, non-negative dock waits, kit/SKU sums).
At load 0.8 no kit is late; the load 1.0 runs are included so the late-kit views have content.

### 2. Preprocess CSV → JSON

Converts every run under `vis_data/` into `web/public/data/<policy>_L<load>/` and writes `web/public/data/index.json`.

```bash
python tools/build_vis_data.py --default new_cpr_L1.0
```

### 3. Run the web interface

```bash
cd web
npm install
npm run dev        # http://localhost:5173/  (add ?run=greedy_L1.0 to open a specific run)
```

`npm run build` writes a static site to `web/dist/` (it only reads the JSON files; no backend).

### Files

- `src/simulation_engine/vis_export.py` — wraps the simulator (no simulator or policy code is modified) and exports tables
- `tools/build_vis_data.py` — preprocessing; definitions of derived fields are in each `meta.json`
- `web/src/` — `main.js` (store wiring, header), `store.js`, `data.js`, `util.js`, `views/` (one file per view)
- `AI_USAGE.md` — disclosure of AI-generated code
