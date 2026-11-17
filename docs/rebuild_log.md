# Rebuild from raw data, 17 November 2026

Before adding the delay-risk model, the whole existing pipeline was re-run from the raw DDL archive on a clean clone,
with the pinned environment (`requirements.txt`, compiled by uv from `requirements.in`: Python 3.13, DuckDB 2.0.0,
pandas 2.3.3, scikit-learn 1.9.1, LightGBM 4.7.0, lifelines 0.30.3, Streamlit 1.67.0). This records how long each step
took and what did not reproduce.

Machine: Windows 11 laptop, 16 logical cores, 16 GB RAM, about 12 GB of free disk at the start.

## Runtime

| Step | Time | Notes |
|---|---|---|
| `download_ddl.py` | 32.9 min | Read 4.6 GB of the 5.13 GB stream at about 2.3 MB/s, stopping once every needed table was saved (5 members, 2.0 GB kept) |
| `load.py` | 5.7 min | 80,935,944 case rows and 76,811,357 act rows; every table's Parquet row count equals its CSV row count |
| `standardize.py` | 7.6 min | `fact_case` row counts equal the source in every year |
| `analysis.py` | 2.7 min | |
| `model.py` | 1.8 min | |
| `quality.py` | 2.7 min | 48 rules |
| `export_maps`, `findings`, `scorecard`, `recalc_excel`, `brief`, `write_readme` | 0.7 min | |
| **Total after download** | **21.1 min** | |

Source files, sizes and SHA-256 hashes: [data/MANIFEST.md](../data/MANIFEST.md).

## What reproduced

37 of the 42 files in `data/mart` reproduce: 16 are byte-identical, and 21 more match the committed ones exactly in
content, differing only in row order because DuckDB does not preserve insertion order in this pipeline. They include
every survival curve, every stage and district table, the coverage checks and all 48 data-quality rule results. The
other five are explained below. Every number in the README's findings table is unchanged except one sentence of the
Cox model's.

## What did not, and why

| What changed | Cause | What was done |
|---|---|---|
| Cox hazard ratios moved by sampling noise (Bihar 0.428 to 0.424, concordance 0.7046 to 0.7045); the README sentence now names Odisha before Bihar and says 23% where it said 21% | `model.py` draws its 3 lakh cases with DuckDB's seeded reservoir sample, which repeats on one DuckDB version but not across versions. `fact_case` deliberately has no case ID, so there is no stable key to hash on instead | Documented here; the outputs regenerated with the pinned DuckDB are committed, so the repository matches what the pinned environment produces. The project already reports that a second seed moves the ratios by about 1% |
| Example records in `issue_log.csv` | The same reservoir sampling | None needed: they are illustrations |
| `state_acts`: the twelfth act differed in two states | Ties at the twelve-act cut-off were broken arbitrarily: in Dadra and Nagar Haveli two acts had 5 open cases each, and in Meghalaya two had 105 | Fixed: ties now go to the act with more cases, then by name (`pipeline/analysis.py`), so the table is the same on every run |
| Charts, the brief and the workbook are byte-different | New library versions render and timestamp files differently | Regenerated and committed |

## Problems found on the way

- **The disk filled faster than the data.** With other applications open, DuckDB's 10 GB memory limit pushed Windows
  to grow its page file from 13 GB to 19 GB, eating free disk while the pipeline also spilled to it. `pipeline/common.py`
  now reads optional `WJGS_MEMORY_LIMIT`, `WJGS_THREADS` and `WJGS_MAX_TEMP` overrides (the defaults are unchanged, and
  a caller's explicit values, such as `model.py`'s single thread, still win). This rebuild used 8 GB and a 3 GB spill cap.
- **Raw archives deleted after loading.** The 1.4 GB case archive and the 0.57 GB acts archive were hashed, then
  deleted once their Parquet row counts matched the CSVs. `data/manifest.json` keeps their hashes, so a fresh download
  can be checked against them.
- **One lint finding** in `pipeline/brief.py` (a variable named `l`) was renamed when ruff was added to CI.
