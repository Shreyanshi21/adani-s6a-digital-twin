# Khavda Hybrid Park – S6a-234MW digital twin

The IFC4 model of the Khavda Hybrid Park with the S6a-234MW plot (AGE26AL), linked to the P6 schedule and coloured by VisiLean status. A 3D web viewer comes with it.

```
data/drawings/51YY-KPIG-ARY-BES-DE-L-0001 … R2.pdf   ─┐
data/schedule/FY26-P18 S6a <date>.xer                 ─┤  python pipeline/run_pipeline.py
                                                        ▼
build/Khavda_Hybrid_Park_S6a-234MW.ifc   (IFC4: model + schedule tasks + VisiLean status)
dist/   (ready-to-serve viewer)      dist/web/khavda-s6a-4d.html   (single-file web edition)
```

## Setup (once)

```bash
python -m pip install -r requirements.txt
```

You need Python 3.11 or newer. The viewer needs a recent Chrome or Edge, and internet the first time to load three.js from the jsDelivr CDN.

## Everyday use

| Task | Command (or VS Code: *Terminal → Run Task…*) |
|---|---|
| Build everything (reuses finished steps) | `python pipeline/run_pipeline.py` |
| New schedule: drop the `.xer` into `data/schedule/`, then | `python pipeline/run_pipeline.py --from link` |
| Rebuild the IFC after editing `build_ifc.py` | `python pipeline/run_pipeline.py --from ifc` |
| Rebuild viewer outputs after editing `viewer/index.html` | `python pipeline/run_pipeline.py --from dist` |
| Open the viewer | `python -m http.server 8765 --directory dist`, then go to <http://localhost:8765> |

The pipeline takes the newest `.xer` in `data/schedule/` unless you pass `--xer <file>`.

## Pipeline steps (`pipeline/`)

| Step | Script | What it does | Output |
|---|---|---|---|
| `pdf` | `cache_pdf.py` | Reads the vector drawings and text of sheet 1 (whole park) and sheet 3 (S6a detail) | `build/p1.pkl`, `build/p3.pkl` |
| `extract` | `extract.py` | Georeferences both sheets to UTM 42N from the coordinate labels (residuals: 2 cm on sheet 3, 0.15 m on sheet 1). Extracts tables, inverters, ICRs, roads, WTGs, PSS, 400 kV routes, plots and BESS | `build/features.json` |
| `ifc` | `build_ifc.py` | Builds the IFC4 model: 9,093 FT tables (56 modules each), piles, MMS, 883 inverters, 19 ICR/IDT stations, PSS-10, BESS, 393 WTGs (with separate rotors), towers, roads and terrain | `build/…_base.ifc` |
| `link` | `link_schedule.py` | Adds the P6 activities as `IfcTask` (WBS = VisiLean location tree) and links each activity to the elements it builds. Derives the VisiLean status | `build/Khavda_Hybrid_Park_S6a-234MW.ifc`, `build/link_report.json` |
| `scene` | `export_scene.py` | Pre-tessellates the IFC into a compact 3D package (~4 MB) so the viewer needs no IFC engine | `build/scene.bin` |
| `dist` | (in `run_pipeline.py`) | Assembles the servable viewer folder | `dist/` |
| `web` | `build_web.py` | Builds the single-file page, with the package embedded at the end of the file | `dist/web/khavda-s6a-4d.html` |

`render_ifc.py` renders preview PNGs of any IFC (VS Code task *Render preview PNGs*).

## Viewer (`viewer/index.html`)

The viewer is a single HTML file using three.js r160 and web-ifc 0.0.66. It loads in this order:
1. The prepared package: `scene.bin` when served over http, `scene-data.js` when the file is opened from disk.
2. The raw IFC, with **Open…** or `?file=…`.

Features:
- Realistic mode: sky, sun shadows, textured PV modules, spinning WTGs, guided tour.
- Labels by zoom level.
- Model tree, classes and search panels.
- Properties panel with UTM E/N coordinates.
- Colour modes: VisiLean status, block, IFC class.
- Schedule tab: status roll-up, work-type filter, as-built view, delayed highlight, and import of a VisiLean CSV export (`External Id` + `Status`).
- Wheel zoom about the point under the cursor, double-click to fly to a spot, and a measure tool.

**Status colours** (sampled from VisiLean): Not Ready `#d47d70` · Not Committed `#ddd75d` · Started `#3c007b` · Complete `#72a64c`.

## Publishing the web edition

`dist/web/khavda-s6a-4d.html` is the page published at <https://claude.ai/artifact/XJAFctthxtyojAjDQtf1Ba>. The model data must stay at the end of that file: claude.ai doesn't display the page when a multi-MB data block sits near the top.

## Notes

See `docs/IFC_Model_Notes.md` for:
- georeferencing
- the activity-to-element mapping
- how the VisiLean status is derived from P6
- modelling assumptions (indicative plots outside S6a, typical equipment sizes, Block 8 boundary)
