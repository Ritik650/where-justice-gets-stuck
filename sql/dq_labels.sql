-- Label checks for the delay-risk model, in the block format of sql/dq_rules.sql. src/ml/dq.py parses this file and
-- runs every check over the `case_label` view (sql/labels.sql), restricted to the modelling population: usable, not
-- in a flagged district, and eligible for the 24-month label. The body is a predicate; TRUE means the row fails.
--
-- status   Invariant: must never fail; src/ml/dq.py stops the build if one does.
--          Accepted:  a known, documented case the label definition handles on purpose; counted and reported.
--          Info:      not a problem, counted so the edge cases in docs/label_definition.md carry real numbers.

-- id: LB01
-- status: Invariant
-- title: Label window ends after the observation end
-- treatment: Impossible by construction. A failure would mean some labels are not fully observed.
date_of_filing + {horizon} > DATE '{t_end}'

-- id: LB02
-- status: Invariant
-- title: Positive label with no decision date
-- treatment: Impossible by construction.
label_24m = 1 AND date_of_decision IS NULL

-- id: LB03
-- status: Invariant
-- title: Positive label, decided after the window
-- treatment: Impossible by construction.
label_24m = 1 AND date_of_decision > date_of_filing + {horizon}

-- id: LB04
-- status: Invariant
-- title: Negative label, decided within the window
-- treatment: Impossible by construction.
label_24m = 0 AND date_of_decision <= date_of_filing + {horizon}

-- id: LB05
-- status: Invariant
-- title: Decided within 12 months but not within 24
-- treatment: Impossible: the 12-month label must imply the 24-month one.
label_12m = 1 AND label_24m = 0

-- id: LB06
-- status: Invariant
-- title: Negative duration for the Cox model
-- treatment: Impossible once V01 is excluded.
duration_days < 0

-- id: LB07
-- status: Accepted
-- title: Undecided, but an outcome is recorded (rule X04)
-- treatment: Labelled pending (0), as the main analysis counts them open. Could be a missing decision date.
dq_x04

-- id: LB08
-- status: Accepted
-- title: Decided within the window by transfer or committal (rule X09)
-- treatment: Labelled decided (1), matching official disposal counts. A transfer closes the file, not the dispute.
dq_x09 AND label_24m = 1

-- id: LB09
-- status: Info
-- title: Decided, but after the window
-- treatment: Labelled 0. These cases took longer than the window, which is what the label measures.
date_of_decision > date_of_filing + {horizon}

-- id: LB10
-- status: Info
-- title: Decided on the day of filing
-- treatment: Labelled 1. Mostly bail and petty matters.
date_of_decision = date_of_filing

-- id: LB11
-- status: Info
-- title: Decided on the last day of the window
-- treatment: Labelled 1: the window includes its last day.
date_of_decision = date_of_filing + {horizon}

-- id: LB12
-- status: Info
-- title: Never decided at all
-- treatment: Labelled 0. The case was still open when its court's records were collected.
date_of_decision IS NULL
