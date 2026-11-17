# Feature audit: what is known at filing

Every column in the source tables, marked **known at filing** or **known after filing**, with what the delay-risk model
does with it. The rule is simple: a model that predicts at filing may only see what a registry knows on the day a case
is filed. `tests/test_ml_features.py` enforces it, and `src/ml/features.py` lists the post-filing columns that no
model input may use (`POST_FILING_COLUMNS`).

The DDL files are a snapshot taken when each court's records were collected, mostly in early 2019. A column can be
"known at filing" in principle and still be recorded later; those cases are marked *at filing, as recorded*.

## Case table (`cases_YYYY`)

| Column | Known | Used by the model | Reason |
|---|---|---|---|
| `ddl_case_id` | At filing | No | An identifier. Used only to join tables and to fix the sample and splits. |
| `year` | At filing | As `filing_year` | The file year; matches the filing date. |
| `state_code` | At filing | As `state` | Where the case is filed. |
| `dist_code` | At filing | As `district` | |
| `court_no` | At filing | As `court`, and `court_level` via the court key | The establishment a case is filed in. A transfer to another establishment creates a new record. |
| `cino` | At filing | No (dropped at load) | Links a row to a named eCourts record. Never stored. |
| `judge_position` | **After** | No | The designation of the court hall where the case sits at collection. It changes when a case moves between halls, so it describes the case's later path, not its filing. |
| `female_petitioner` | At filing, as recorded | As `petitioner_gender` | The petitioner is named in the filing. Gender is predicted from the name by DDL; "unclear" and "missing" codes double as party-type flags (a state or company has no gendered name). |
| `female_defendant` | At filing, as recorded | As `defendant_gender` | The respondent or accused is named in the filing. |
| `female_adv_pet` | At filing, as recorded | As `petitioner_advocate` | The petitioner's advocate usually files the case. Could be updated later if counsel changes. |
| `female_adv_def` | **After** | No; leakage test only | The defendant's advocate is entered when the defendant appears and contests, which is after filing and much more common in long cases. |
| `type_name` | At filing | As `case_type` and `case_type_label` | The case type is assigned at registration. Decoded with `type_name_key` on code and year. |
| `purpose_name` | **After** | No; leakage test only | The purpose of the last or next hearing: the stage a case had reached at collection. |
| `disp_name` | **After** | No | The disposition. Part of the outcome. |
| `date_of_filing` | At filing | As `filing_year`, `filing_month`, `filing_weekday`; the clock's start | |
| `date_of_decision` | **After** | No; the label | The outcome itself. |
| `date_first_list` | **After** | No | The first hearing comes after filing, sometimes by months. |
| `date_last_list` | **After** | No; leakage test only | The most recent hearing at collection. For a decided case it is close to the decision date. |
| `date_next_list` | **After** | No | The next scheduled hearing at collection. |
| `date_parse_failures` | **After** | No | An audit field added at load. It counts unparseable strings across all five dates, including the decision date. |

## Acts and sections (`acts_sections`)

| Column | Known | Used by the model | Reason |
|---|---|---|---|
| `ddl_case_id` | At filing | No | Join key. |
| `act` | At filing, as recorded | As `act` (standardised) and in `act_section` | The act is entered at registration. A charge sheet can add sections later, so the recorded value may be fuller than on day one. |
| `section` | At filing, as recorded | In `act_section` | As above. |
| `bailable_ipc` | At filing, as recorded | No | Derived from IPC sections; adds little beyond the section and is blank outside the IPC. |
| `number_sections_ipc` | At filing, as recorded | No | More likely than the section itself to grow when charges are framed, so left out to be safe. |
| `criminal` | At filing | As `ddl_criminal_flag` | DDL's flag. It marks cheque-bounce, traffic and excise cases as non-criminal, which is why the case type and act are also used. |

## Judges (`judge_case_merge_key`, `judges_clean`)

| Column | Known | Used by the model | Reason |
|---|---|---|---|
| `ddl_filing_judge_id` | At filing | No | Present only for criminal cases DDL could link (50-75% of them), so its presence depends on the case type. Left for later work. |
| `ddl_decision_judge_id` | **After** | No | The judge who decided the case. |
| Judge `start_date` | At filing | No | Time the filing judge had already served is knowable; not used in this proof of concept. |
| Judge `end_date` | **After** | No | When the judge left the post. Using it would leak the future; the project's Q4 analysis uses it only as an exposure measured after the fact. |
| Other judge columns | At filing | No | |

## Lookup and reference tables

`type_name_key`, `act_key`, `section_key`, `cases_court_key`, `cases_district_key` and `cases_state_key` describe codes,
not cases, so they carry no outcome information. `purpose_name_key` and `disp_name_key` decode post-filing columns and
are used only for the leakage test and the error analysis. `data/mart/q5_districts.parquet` supplies the
incomplete-closure-records flag, which selects the modelling population; it is never a model input
([label_definition.md](label_definition.md) explains why).

## Built from other cases (court history)

History features summarise **other** cases in the same court, district or state. They are point-in-time correct by
construction: yearly rates for a case filed in year Y use only events dated in Y-1 or earlier, and the pending load uses
only events dated before the first day of the filing month. History counts every case with a valid filing date, and a
decision only from its own date and only when that date is valid, so it never depends on how a case later turned out.
[features.md](features.md) gives each rule, and two tests rebuild the features with every later event deleted to check
that nothing changes.
