# Dashboard design source

The dashboard design was generated with Google Stitch (project `18189591592686076503`, "Where Justice Gets Stuck dashboard", design system "Informed Ledger") and then built natively in Streamlit.

## Screens

| Stitch screen | Built as |
|---|---|
| Main dashboard: header note, four KPI cards, question switcher, map beside a ranked table, caveats, data-quality scores, sources | `dashboard/app_pages/findings.py` |
| State Profile (`424014fbd0584ba88e12167e8f0b0e5b`): state selector, six KPI cards with national comparisons, survival and stage charts, district and act tables | `dashboard/app_pages/state_profile.py` |
| Data Quality (`002b4e75639043299b0f9bbe15e03741`): Scorecard, Rules, Issue log and Coverage views, a heat table and a trend by filing year | `dashboard/app_pages/data_quality.py` |

## Tokens

| Token | Value | Used for |
|---|---|---|
| Canvas | `#F9F8F6` | Page background |
| Panel | `#FFFFFF` | Chart backgrounds |
| Subdued surface | `#F4F2EE` | Table headers |
| Hairline | `#E5E3DF` | Borders and dividers |
| Ink | `#18181B` | Text and selected controls |
| Muted ink | `#71717A` | Axis labels and captions |
| Data accent | `#1E40AF` | Focal data only, never chrome |
| Sequential ramp | `#DBEAFE` to `#1E40AF` | Map scale |
| Type | Inter, sentence case | Everything |
| Corners | 0 px, no shadows | Everything |

## Left out of the designs

The generated screens included an invented organisation name, extra navigation items and export buttons, none of which exist in this project.

## Where the charts differ

Where the charts need several colours, they use a palette checked with a colour-vision validator. Cobalt fails that check's lightness band as a categorical colour, so it stays reserved for emphasis and the map.
