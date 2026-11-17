"""Delay-risk model: will a case be decided within 24 months of filing?

Steps, in the order `make all` runs them:
    fixture.py   (fixture profile only) a small synthetic dataset with the real schema
    dq.py        label definition, data-quality exclusions with row counts, class balance, label checks
    sample.py    a stratified sample by state x filing year, with a fixed seed
    features.py  point-in-time features in DuckDB SQL (sql/features.sql)
    split.py     temporal split plus a held-out set of courts; split IDs saved to disk
    train.py     baselines B0-B2, logistic regression, LightGBM, Cox; every run logged
    evaluate.py  test metrics, bootstrap intervals, slices, calibration, importance, error analysis
    report.py    reports/ml_poc_report.md, figures, dashboard tables
"""
