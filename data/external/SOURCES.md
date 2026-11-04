# External data sources

| File | Source | Licence / status | Notes |
|---|---|---|---|
| `njdg_state_pendency_2026-07-30.csv` | NJDG data in Lok Sabha Unstarred Question 3371, Annexure II, answered 7 Aug 2026 (https://sansad.in/getFile/lsapps/loksabhaquestions/annex/188/AU3371_Lq6K9K.pdf) | Government of India parliamentary record | Transcribed by hand from the PDF; `tests/test_external.py` checks the rows sum to the printed totals. The source labels the last column "More than 5 years", but it cannot be cumulative because West Bengal's ">10 years" is larger, so it is stored as 5–10 years. |
| `census2011_districts_raw.csv` | Census 2011 district totals, via https://github.com/nishusharma1608/India-Census-2011-Analysis (mirror of the Kaggle `danofer/india-census` file) | Underlying data: Registrar General & Census Commissioner, India | 640 districts on 2011 boundaries. |
| `2011_Dist.shp`, `.dbf`, `.shx` | Census 2011 district boundaries, https://github.com/datameet/maps/tree/master/Districts/Census_2011 | DataMeet India community, CC BY 4.0 | Source for `data/geo/*.geojson`, built by `pipeline/build_geo.py`. Not committed because of size. For display only. Not an official map of India. |
| `district_crosswalk_overrides.csv` | Hand-built for this project | Same licence as the derived data | Links DDL districts that have no Census 2011 ID in DDL's own crosswalk, with the link type for each row. |
