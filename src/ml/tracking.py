"""Log every run: parameters, feature version, split, metrics and runtime.

reports/experiments.csv is the record of every run and is committed with the code, so each number in the README and
the report can be traced to a row. Runs are also logged to a local MLflow store (mlflow.db, not committed) when
config.yaml turns it on; MLflow failing never stops a build, because the CSV is the source of truth.

    python -m src.ml.tracking --sync    load every row of experiments.csv into MLflow (skips rows already there)
    mlflow ui --backend-store-uri sqlite:///mlflow.db
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import time
import uuid
import warnings
from datetime import datetime, timezone

from .settings import ROOT, Settings, git_commit, load

# MLflow 3 no longer accepts a plain folder as its store by default, so runs go to a local SQLite file.
MLFLOW_URI = f"sqlite:///{(ROOT / 'mlflow.db').as_posix()}"
METRICS = ["valid_auc", "valid_pr_auc", "valid_brier", "valid_log_loss", "test_auc", "test_pr_auc", "test_brier",
           "test_log_loss", "test_unseen_auc", "runtime_s"]

COLUMNS = [
    "run_id", "session", "timestamp", "profile", "stage", "model", "label", "params", "feature_version", "features",
    "split_version", "train_rows", "valid_rows", "test_rows",
    "valid_auc", "valid_pr_auc", "valid_brier", "valid_log_loss",
    "test_auc", "test_pr_auc", "test_brier", "test_log_loss", "test_unseen_auc", "extra_metrics",
    "runtime_s", "config_hash", "git_commit", "notes",
]


class Tracker:
    def __init__(self, s: Settings, feature_version: str, split_version: str):
        self.s = s
        self.path = s.experiments_path
        self.session = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.common = {"profile": s.profile, "feature_version": feature_version, "split_version": split_version,
                       "config_hash": s.config_hash(), "git_commit": git_commit(), "session": self.session}
        self.mlflow = None
        if s.cfg["tracking"].get("mlflow"):
            os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
            try:
                import mlflow
                mlflow.set_tracking_uri(MLFLOW_URI)
                mlflow.set_experiment(f"delay-risk-{s.profile}")
                self.mlflow = mlflow
            except Exception as exc:  # noqa: BLE001 - tracking is optional; the CSV is the record
                warnings.warn(f"MLflow logging disabled: {exc}", stacklevel=2)

    def log(self, stage: str, model: str, params: dict, metrics: dict, runtime_s: float, label: str = "label_24m",
            features: int | None = None, rows: dict | None = None, notes: str = "", extra: dict | None = None) -> dict:
        rows = rows or {}
        row = {c: "" for c in COLUMNS} | self.common | {
            "run_id": uuid.uuid4().hex[:10],
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stage": stage, "model": model, "label": label, "params": json.dumps(params, sort_keys=True, default=str),
            "features": features if features is not None else "",
            "train_rows": rows.get("train", ""), "valid_rows": rows.get("valid", ""), "test_rows": rows.get("test", ""),
            "extra_metrics": json.dumps(extra or {}, sort_keys=True, default=float),
            "runtime_s": round(runtime_s, 1), "notes": notes,
        }
        for key, value in metrics.items():
            if key in row:
                row[key] = round(float(value), 6) if value is not None and value == value else ""
        new = not self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", newline="", encoding="utf8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNS)
            if new:
                w.writeheader()
            w.writerow(row)
        if self.mlflow is not None:
            try:
                with self.mlflow.start_run(run_name=f"{model} [{stage}]"):
                    self.mlflow.log_params({k: str(v)[:250] for k, v in params.items()} | {"stage": stage, "label": label})
                    self.mlflow.set_tags({k: str(v) for k, v in self.common.items()} | {"run_id": row["run_id"], "notes": notes})
                    numeric = {k: float(v) for k, v in metrics.items() if v is not None and v == v}
                    numeric |= {k: float(v) for k, v in (extra or {}).items() if isinstance(v, (int, float)) and v == v}
                    self.mlflow.log_metrics(numeric | {"runtime_s": runtime_s})
            except Exception as exc:  # noqa: BLE001
                warnings.warn(f"MLflow logging failed for {model}: {exc}", stacklevel=2)
        print(f"  logged {row['run_id']} {stage:<10} {model:<45} valid_auc={row['valid_auc']} test_auc={row['test_auc']} "
              f"{runtime_s:.0f}s", flush=True)
        return row


class Timer:
    def __enter__(self):
        self.t0 = time.time()
        return self

    def __exit__(self, *exc):
        self.seconds = time.time() - self.t0


def sync_to_mlflow(s: Settings) -> int:
    """Log every experiments.csv row into MLflow under its own run ID, skipping rows MLflow already has."""
    os.environ.setdefault("MLFLOW_DISABLE_AGENT_HINT", "1")
    import mlflow
    import pandas as pd

    mlflow.set_tracking_uri(MLFLOW_URI)
    experiment = mlflow.set_experiment(f"delay-risk-{s.profile}")
    done = set()
    existing = mlflow.search_runs(experiment_ids=[experiment.experiment_id], output_format="pandas")
    if len(existing) and "tags.run_id" in existing:
        done = set(existing["tags.run_id"].dropna())
    rows = pd.read_csv(s.experiments_path, dtype={"run_id": str})
    added = 0
    for r in rows.to_dict("records"):
        if r["run_id"] in done:
            continue
        params = json.loads(r["params"]) if isinstance(r["params"], str) and r["params"] else {}
        with mlflow.start_run(run_name=f"{r['model']} [{r['stage']}]"):
            mlflow.log_params({k: str(v)[:250] for k, v in params.items()} | {"stage": r["stage"], "label": r["label"]})
            tags = {k: str(r[k]) for k in ("run_id", "session", "timestamp", "profile", "model", "feature_version",
                                           "split_version", "config_hash", "git_commit", "notes") if k in r}
            mlflow.set_tags(tags)
            metrics = {k: float(r[k]) for k in METRICS if k in r and r[k] == r[k] and r[k] != ""}
            extra = json.loads(r["extra_metrics"]) if isinstance(r.get("extra_metrics"), str) and r["extra_metrics"] else {}
            metrics |= {k: float(v) for k, v in extra.items() if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v}
            mlflow.log_metrics(metrics)
        added += 1
    return added


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sync", action="store_true", help="load experiments.csv into MLflow")
    if ap.parse_args().sync:
        settings = load()
        print(f"added {sync_to_mlflow(settings)} runs to {MLFLOW_URI}", flush=True)
