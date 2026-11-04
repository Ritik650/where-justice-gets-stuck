"""Write the standardisation tables as CSV, so every mapping decision can be reviewed without running anything."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MART, PARQUET  # noqa: E402


def run() -> dict:
    MART.mkdir(parents=True, exist_ok=True)
    act = pd.read_parquet(PARQUET / "maps" / "map_act.parquet")
    act[["act", "act_s", "act_canonical", "act_family", "declared_count"]].sort_values("declared_count", ascending=False).to_csv(
        MART / "map_act.csv", index=False)

    purpose = pd.read_parquet(PARQUET / "maps" / "map_purpose.parquet")
    stages = (purpose.assign(n=pd.to_numeric(purpose["count"], errors="coerce").fillna(0))
              .groupby(["purpose_name_s", "stage"], as_index=False)["n"].sum().sort_values("n", ascending=False))
    stages.to_csv(MART / "map_purpose.csv", index=False)

    typ = pd.read_parquet(PARQUET / "maps" / "map_type.parquet")
    types = (typ.assign(n=pd.to_numeric(typ["count"], errors="coerce").fillna(0))
             .groupby(["type_name_s", "type_category"], as_index=False)["n"].sum().sort_values("n", ascending=False))
    types.to_csv(MART / "map_type.csv", index=False)

    usable = ~act["act_canonical"].isin(["Other / unmapped", "Blank or unusable label", "Implausible act (likely dropdown default)"])
    stats = {
        "act_variants_total": int(len(act)),
        "act_variants_standardized": int(usable.sum()),
        "canonical_acts": int(act.loc[usable, "act_canonical"].nunique()),
        "stage_labels": int(stages["purpose_name_s"].nunique()),
        "type_labels": int(types["type_name_s"].nunique()),
    }
    pd.DataFrame([stats]).to_csv(MART / "mapping_stats.csv", index=False)
    print(stats, flush=True)
    return stats


if __name__ == "__main__":
    run()
