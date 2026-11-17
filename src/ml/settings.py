"""Read config.yaml, resolve the active profile, and hold the paths every step shares."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"
SQL_DIR = ROOT / "sql"


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


@dataclass
class Settings:
    profile: str
    cfg: dict
    source: Path
    district_flags: Path
    work: Path
    reports: Path
    mart: Path
    sample_size: int
    threads: int
    memory_limit: str
    extra: dict = field(default_factory=dict)

    # Row-level files. They live under `work`, which git ignores.
    @property
    def sample_path(self) -> Path:
        return self.work / "sample.parquet"

    @property
    def features_path(self) -> Path:
        return self.work / "features.parquet"

    @property
    def splits_path(self) -> Path:
        return self.work / "splits.parquet"

    @property
    def predictions_dir(self) -> Path:
        return self.work / "predictions"

    @property
    def models_dir(self) -> Path:
        return self.work / "models"

    @property
    def experiments_path(self) -> Path:
        return self.reports / "experiments.csv"

    @property
    def results_path(self) -> Path:
        """Every number the report quotes, written by evaluate.py."""
        return self.reports / "ml_results.json"

    @property
    def figures_dir(self) -> Path:
        return self.reports / "figures"

    def src(self, relative: str) -> str:
        """A source Parquet path for read_parquet(), with forward slashes so DuckDB accepts it on Windows."""
        return (self.source / relative).as_posix()

    def section(self, name: str) -> dict:
        return self.cfg[name]

    @property
    def seed(self) -> int:
        return int(self.cfg["seed"])

    def config_hash(self) -> str:
        """Short hash of the effective settings, stored with every run."""
        text = json.dumps(self.cfg, sort_keys=True, default=str)
        return hashlib.sha256(text.encode()).hexdigest()[:10]

    def ensure_dirs(self) -> None:
        for p in (self.work, self.reports, self.mart, self.predictions_dir, self.models_dir, self.figures_dir):
            p.mkdir(parents=True, exist_ok=True)


def load(profile: str | None = None) -> Settings:
    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf8"))
    name = profile or os.environ.get("ML_PROFILE", "full")
    if name not in raw["profiles"]:
        raise SystemExit(f"unknown profile {name!r}; config.yaml defines {sorted(raw['profiles'])}")
    prof = raw["profiles"][name]
    cfg = deep_merge({k: v for k, v in raw.items() if k != "profiles"}, prof.get("overrides", {}))
    cfg["profile"] = name
    return Settings(
        profile=name,
        cfg=cfg,
        source=ROOT / prof["source"],
        district_flags=ROOT / prof["district_flags"],
        work=ROOT / prof["work"],
        reports=ROOT / prof["reports"],
        mart=ROOT / prof["mart"],
        sample_size=int(prof["sample_size"]),
        threads=int(prof["threads"]),
        memory_limit=str(prof["memory_limit"]),
    )


# Files the pipeline itself rewrites. A run that regenerates them is still running the committed code, so changes here
# do not make the commit "dirty"; any other tracked change (code, SQL, config) does.
GENERATED = ["reports", "data/mart", "outputs", "docs/model_card.md", "README.md"]


def git_commit() -> str:
    """The commit the code ran from, with "-dirty" if code, SQL or config differ from it."""
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        paths = ["--", "."] + [f":(exclude){p}" for p in GENERATED]
        dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no", *paths], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return out.stdout.strip() + ("-dirty" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def read_sql(name: str, **params) -> str:
    """Read a file from sql/ and fill its {placeholders}. Comment lines are left as written."""
    lines = (SQL_DIR / name).read_text(encoding="utf8").splitlines()
    return "\n".join(line if line.lstrip().startswith("--") else line.format(**params) for line in lines) + "\n"


def split_statements(sql: str) -> list[str]:
    """Split a SQL file on semicolons that end a line, skipping comment-only chunks."""
    parts = []
    for chunk in sql.split(";\n"):
        body = "\n".join(line for line in chunk.splitlines() if not line.strip().startswith("--")).strip().rstrip(";")
        if body:
            parts.append(body)
    return parts
