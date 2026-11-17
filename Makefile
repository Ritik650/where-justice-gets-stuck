# The delay-risk model (src/ml), step by step. Each target runs one step on the profile in config.yaml:
#
#   make all                    the real data (downloads 5.1 GB on first run)
#   make all PROFILE=fixture    a synthetic fixture with the same schema, in about a minute (CI runs this)
#
# On Windows, run with GNU make (for example `mingw32-make`) from a shell where `python` is the project venv,
# or pass PYTHON=.venv/Scripts/python.exe.

PYTHON ?= python
PROFILE ?= full
export ML_PROFILE := $(PROFILE)
export MLFLOW_DISABLE_AGENT_HINT := 1
ML := $(PYTHON) -X utf8 -m src.ml

.PHONY: all data dq features train evaluate report test lint mlflow manifest pipeline clean-ml

all: data dq features train evaluate report

## data: source Parquet for the profile (full: download, load and standardise; fixture: generate)
data:
	$(ML).data

## dq: the label, its exclusions with row counts, class balance and label checks
dq:
	$(ML).dq

## features: stratified sample, point-in-time features, then the temporal and unseen-court splits
features:
	$(ML).sample
	$(ML).features
	$(ML).split

## train: baselines B0-B2, logistic regression, LightGBM grid, Cox model and the experiments, all logged
train:
	$(ML).train

## evaluate: test metrics, bootstrap intervals, slices, calibration, importance, error analysis
evaluate:
	$(ML).evaluate

## report: reports/ml_poc_report.md, figures, model card (and the README, on the full profile)
report:
	$(ML).report

test:
	$(PYTHON) -m pytest tests -q

lint:
	$(PYTHON) -m ruff check src tests pipeline dashboard

## mlflow: load every logged run (reports/experiments.csv) into the local MLflow store; then `mlflow ui --backend-store-uri sqlite:///mlflow.db`
mlflow:
	$(ML).tracking --sync

## manifest: refresh data/MANIFEST.md from the raw files on disk
manifest:
	$(ML).manifest

## pipeline: the descriptive project (marts, dashboard tables, brief, scorecard) from pipeline/run_all.py
pipeline:
	$(PYTHON) -I pipeline/run_all.py

clean-ml:
	$(ML).clean
