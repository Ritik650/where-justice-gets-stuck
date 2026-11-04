"""Standardisation rules that turn messy free-text labels into a small set of categories.

Each table is an ordered list of (category, regex): the first match wins. Act names are matched after
lowercasing and removing everything except letters and digits, so "I.P.C.", "ipc" and "I P C" compare
equal and "CodeofCivilProcedure" (a common spelling in the raw data) needs no special handling.
Stage and type labels keep their spaces because short codes such as "st" and "os" need word boundaries.
"""
from __future__ import annotations

import re

ACT_OTHER_LITERAL = "Other / unmapped"
ACT_RULES: list[tuple[str, str, str]] = [
    # (canonical act, family, regex on the squeezed label). Specific acts come before generic words.
    ("Code of Criminal Procedure", "Criminal procedure", r"criminalprocedure|codeofcriminal|crimprocedure|crpc|^crp|dandprakriya|prakriyasanhita"),
    ("Code of Civil Procedure", "Civil procedure", r"civilprocedure|codeofcivil|civilpro|^cpc|cpc$"),
    ("Ranbir Penal Code (J&K)", "Penal", r"^rpc|ranbirpenal"),
    ("Indian Penal Code", "Penal", r"indianpenal|penalcode|^ipc|ipc$|dandsanhita|dandvidhan|indianpanel|panelcode"),
    ("Negotiable Instruments Act", "Commercial", r"negotiabl|negotiabe|negotiale|(^|[0-9]|of|the|us|sec)niact|^nia$|^ni$|^nact$|^ni138|138ni|chequebounce|instrumentsact|instrumentact"),
    ("Motor Vehicles Act", "Road traffic", r"motorveh|motorvech|motervehicle|motorvhicle|motorvihicle|^mv$|mvact|^mvc|motoraccident|roadsafety|motortransport"),
    ("Hindu Marriage Act", "Family", r"hindumarriage|hindumarrige|hindumarraige|^hma|hmact"),
    ("Protection of Women from Domestic Violence Act", "Family", r"domesticviolence|domesticvoilence|protectionofwomen|^dvact|^pwdv"),
    ("Dowry Prohibition Act", "Family", r"dowry"),
    ("Family Courts Act", "Family", r"familycourt"),
    ("Guardians and Wards Act", "Family", r"guardian"),
    ("Succession Acts", "Family", r"succession"),
    ("Special Marriage / Divorce Acts", "Family", r"specialmarriage|divorce|parsimarriage|muslimwomen|muslimmarriage|christianmarriage|maintenanceorders"),
    ("Maintenance and Welfare of Parents Act", "Family", r"maintenanceandwelfare|seniorcitizen"),
    ("Child Marriage Act", "Family", r"childmarriage"),
    ("Animal Protection Acts", "Regulatory offences", r"crueltytoanimal|animalpreservation|cowslaughter|animal|cattle"),
    ("Tobacco Control Act (COTPA)", "Regulatory offences", r"cotpa|cigarette|tobacco|prohibitionofsmoking"),
    (ACT_OTHER_LITERAL, "Other", r"whitephosphorus|indecentrepresentation"),
    ("State Prohibition Acts", "Excise and liquor", r"prohibition"),
    ("State Excise / Abkari Acts", "Excise and liquor", r"excise|abkari|liquor"),
    ("Narcotic Drugs and Psychotropic Substances Act", "Special criminal", r"narcotic|ndps"),
    ("Arms Act", "Special criminal", r"armsact|^arms|armact"),
    ("Explosive Substances Act", "Special criminal", r"explosive"),
    ("Juvenile Justice Act", "Special criminal", r"juvenile"),
    ("Protection of Children from Sexual Offences Act", "Special criminal", r"pocso|protectionofchildren|sexualoffence"),
    ("SC/ST (Prevention of Atrocities) Act", "Special criminal", r"atrocit|attrocit|scheduledcaste|^scst|schedulecaste"),
    ("Immoral Traffic (Prevention) Act", "Special criminal", r"immoraltraffic|^itpa"),
    ("Prevention of Corruption Act", "Special criminal", r"corruption"),
    ("Information Technology Act", "Special criminal", r"informationtechnology|^itact"),
    ("Prevention of Damage to Public Property Act", "Special criminal", r"damagetopublic|publicproperty"),
    ("Foreigners / Passport Acts", "Special criminal", r"foreigner|passport"),
    ("Gambling / Gaming Acts", "Regulatory offences", r"gambling|gaming|lottery"),
    (ACT_OTHER_LITERAL, "Other", r"insurancecorporation"),
    ("Police Acts", "Regulatory offences", r"policeact|^police|policeorder|kpact|^kp$"),
    ("Railways Act", "Regulatory offences", r"railway"),
    ("Electricity Act", "Regulatory offences", r"electricity"),
    ("Forest / Wildlife Acts", "Regulatory offences", r"forest|wildlife|woodsandtimber"),
    ("Mines and Minerals Act", "Regulatory offences", r"minesandminerals|minesminerals|mineral"),
    ("Essential Commodities Act", "Regulatory offences", r"essentialcommod"),
    ("Food Safety / Adulteration Acts", "Regulatory offences", r"foodadult|foodsafety|adulteration"),
    ("Legal Metrology / Weights and Measures", "Regulatory offences", r"metrology|weightsandmeasure|weightandmeasure|weightmeasure"),
    ("Registration of Births and Deaths Act", "Regulatory offences", r"birthsanddeaths|birthanddeath|birthsdeaths"),
    ("Labour Laws", "Labour", r"industrialdispute|wages|factories|factory|workmen|employee|labour|shopsand|shopand|shopestt|gratuity|bonus"),
    ("Municipal / Local Body Acts", "Regulatory offences", r"municipal|muncipal|corporationact|panchayat|townplanning|townandcountry|mmcact|bmcact|^mmc|^bmc"),
    ("Specific Relief Act", "Civil and property", r"specificrelief|specificreleif"),
    ("Transfer of Property Act", "Civil and property", r"transferofproperty|transferofpropety"),
    ("Indian Contract Act", "Civil and property", r"contractact|indiancontract"),
    ("Land Acquisition Act", "Civil and property", r"landacquisition|landaquisition|landacq"),
    ("Rent Control / Tenancy Acts", "Civil and property", r"^rent|rentcontrol|rentact|rentand|rentrestrict|tenancy|tenant|landlord|leasesand"),
    ("Land Revenue Acts", "Civil and property", r"landrevenue|revenueact|revenuecode|landreforms|consolidation"),
    ("Partition Act", "Civil and property", r"partition"),
    ("Registration / Stamp Acts", "Civil and property", r"stampact|registrationact|indianstamp"),
    ("Consumer Protection Act", "Commercial", r"consumer"),
    ("Payment and Settlement Systems Act", "Commercial", r"paymentandsettlement"),
    ("Court Fees Acts", "Civil and property", r"courtfee|suitsvaluation"),
    ("Money recovery (no act named)", "Civil and property", r"recoveryofmoney|moneysuit|moneyrecovery"),
    ("Arbitration and Conciliation Act", "Commercial", r"arbitration"),
    ("Companies / Insolvency Acts", "Commercial", r"companiesact|companyact|insolvency"),
    ("Cooperative Societies Acts", "Commercial", r"cooperative|cooprative|mcsact|^mcs"),
    ("Banking / Recovery Acts", "Commercial", r"bankingregulation|sarfaesi|securitization|securitisation|recoveryofdebt|moneylend"),
    ("Indian Evidence Act", "Evidence and limitation", r"evidenceact|indianevidence"),
    ("Limitation Act", "Evidence and limitation", r"limitation"),
]
# Acts a district court would almost never hear, each with tens of thousands of cases. They sit near the
# top of an alphabetical list, so they look like a default dropdown pick rather than the real act.
ACT_IMPLAUSIBLE = re.compile(
    r"absorbedareas|acquiredterritories|andhrapradeshandmysore|andhrapradeshlegislativecouncil|allindiaservices"
    r"|allindiainstitute|allindiacouncil|calcuttahighcourtjurisdictional|civildefence"
)
ACT_NOT_A_NAME = re.compile(
    r"^(act)?(under|u)?(s|sec|section|o|order)?$|^all$|^actus(ec)?$|^undersection|^undersec|^usec|^othercivil|^otherlaw"
    r"|^civilcases?$|^order$|^sec$"
)
ACT_RULES_COMPILED = [(name, fam, re.compile(rx)) for name, fam, rx in ACT_RULES]
ACT_BLANK = "Blank or unusable label"
ACT_IMPLAUSIBLE_NAME = "Implausible act (likely dropdown default)"
ACT_OTHER = "Other / unmapped"


def squeeze(label: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (label or "").lower())


def map_act(label: str | None) -> tuple[str, str]:
    s = squeeze(label)
    if len(s) < 2 or s in {"na", "nil", "none", "null", "act", "other", "others", "unknown"}:
        return ACT_BLANK, "Unknown"
    if ACT_IMPLAUSIBLE.search(s):
        return ACT_IMPLAUSIBLE_NAME, "Unknown"
    for name, fam, rx in ACT_RULES_COMPILED:
        if rx.search(s):
            return name, fam
    if ACT_NOT_A_NAME.search(s):
        return ACT_BLANK, "Unknown"
    return ACT_OTHER, "Other"


# Stages run roughly in the order a trial moves. "Not a stage" holds labels that say nothing about
# progress (for example "unready board" or a court not sitting), which is a data-quality finding too.
STAGE_NONE = "11 Not a stage / blank"
STAGE_ORDER = [
    "1 Admission / first hearing", "2 Summons / notice / service", "3 Appearance of parties",
    "4 Pleadings / charge", "5 Evidence", "6 Arguments", "7 Judgment / orders",
    "8 Interim / miscellaneous", "9 Lok Adalat / settlement", "10 Unspecified hearing", STAGE_NONE,
]
STAGE_RULES: list[tuple[str, str]] = [
    ("9 Lok Adalat / settlement", r"lok.?adalat|lok.?nyayalaya|mediation|conciliation|compromise|\blok\b|settlement|^a\.?d\.?r\.?$"),
    (STAGE_NONE, r"no sitting|not heard|holiday|sine die|vacant|on leave|no court|^others?$|^\W*$|list / special|office note|office report|information|listed to|notified to|new case"),
    ("7 Judgment / orders", r"judg|judj|verdict|pronounce|\border|^f\.? ?o\.?$|final form|for disposal|^disposal|disposal$|sentence|decree|^decided|^award"),
    ("6 Arguments", r"argu|final hearing|rebut"),
    ("5 Evidence", r"evid|witness|\bp\.? ?w\b|\bp\.? ?e\.?$|\bd\.? ?e\.?$|examinat|\bexam\b|cross|\b313\b|statement of accus|sworn|\btrial\b|deposition|further statement|questioning|statement of part|accused stat[e]?ment|soleman|solemn|documents"),
    ("4 Pleadings / charge", r"charge|plea\b|framing|\bissues?\b|written statement|\bw\.? ?s\.?$|police paper|\b207\b|\bcop(y|ies|ying)\b|rejoinder|replication|^cons[ie]*d[ei]*ration|cogni[zs]ance|case diary|removal of defects"),
    ("2 Summons / notice / service", r"summ|notice|service|process|warrant|n\.? ?b\.? ?w|\bb\.? ?w\b|abscond|proclamation|attachment|\bsteps?\b|await|^report|for report|enquiry|inquiry|compliance|\bf\.? ?r\.?\b|final report|batta|publication|\bss\b"),
    ("3 Appearance of parties", r"app[ea]+r|apper|attendance|production|presence|surety|\bsr\b|accused absent"),
    ("1 Admission / first hearing", r"admis|addmission|first hearing|filing|registration|scrutiny|verification"),
    ("8 Interim / miscellaneous", r"\bmisc|\bi\.? ?a\.?\b|interim|injunction|\bstay|bail|application|\bapp\b|reply|\bsay\b|objection|counter|show cause|execution|recovery|revision|appeal|amend|petition|commission|legal aid|payment|\bfine\b|\brecord\b|remand|deposit|custody|transfer|commit+al|commitment"),
    ("10 Unspecified hearing", r"hearing|heard|\bhrg\b|\bdate\b|\bcall\b|adjourn|further proceeding|put up"),
]
STAGE_RULES_COMPILED = [(n, re.compile(rx)) for n, rx in STAGE_RULES]


def map_stage(label: str | None) -> str:
    # "notice_unready" and "notice (unready)" mean a notice matter on the unready board.
    s = re.sub(r"[_\s(]*unready[)\s]*", " ", (label or "").strip().lower()).strip()
    if not s:
        return STAGE_NONE
    for name, rx in STAGE_RULES_COMPILED:
        if rx.search(s):
            return name
    return STAGE_NONE


# Case types. Whether a case is criminal comes from DDL's `criminal` flag; this category describes the
# proceeding itself.
TYPE_RULES: list[tuple[str, str]] = [
    ("Bail", r"bail|^blapl|^b\.?\s?a\.?$|\bb\.?a\.?\s?(no|case)|anticipatory"),
    ("Motor accident claim", r"m\.?\s?a\.?\s?c\.?\s?[tpcmo]|motor accident|accident claim|\bm\.?\s?v\.?\s?c\b|mcop|\bmvop|\bmacc|macma|\bmact|claim case|\bm\.?\s?a\.?\s?c\b"),
    ("Cheque bounce (NI Act)", r"n\.?\s?i\.?\s?act|\b138\b|cheque|\bnact\b|negotiable|\bn\.?i\.?\s?(case|cc|comp)|^ni\b|^sc nia"),
    ("Traffic / petty offence", r"mot[ao]r veh|railway act|^summ?$|m\.?\s?v\.?\s?act|traffic|challan|petty|\bs\.?t\.?c\b|summary|\bsum\b|^m\.?\s?v\.?$"),
    ("Sessions trial", r"session|^s\.?\s?c\.?$|^s\.?\s?t\.?$|ndps|pocso|spl\.?\s?case|special (case|trial)|\bsc ele\b|^st\b|^sc atr|juvenile"),
    ("Family / matrimonial", r"matrimonial|marriage|divorce|h\.?\s?m\.?\s?a|hmop|guardian|family|maintenance|\bmnt\b|\b125\b|^m\.?\s?c\.?$|^mjc|domestic|\bd\.?\s?v\.?\b|^dvc|pwdva|^mnt|maint[ae]|^dmc|h\.?m\.?o\.?p|f\.?c\.?o\.?p|m\.?j\.?\s?case"),
    ("Execution", r"exec|^exe?\b|^ex\.|\bex\.?\s?p|^e\.?\s?p\.?$|\bexe\s?r|darkhast|dkst|^fdp|^d\.?\s?a\.?$"),
    ("Civil suit", r"suit|\bo\.?\s?s\.?\b|original|^c\.?\s?s\.?$|\bcs\b|\br\.?\s?c\.?\s?s\b|\bs\.?\s?c\.?\s?s\b|\bt\.?\s?s\.?\b|\bm\.?\s?s\.?\b|money|partition|title|^spl\.?\s?\.?c\.?s|^spcs|^spl\.?c$"),
    ("Criminal misc. / appeal", r"cr.*misc|cri.*misc|crl.*misc|crmp|\bcrma\b|cri\.?\s?m\.?\s?a|cr.*appeal|cri.*appeal|crl.*appeal|cr.*rev|cri.*rev|crl.*rev|\bcr\.?a\b|\bcrr\b|^mcrc|m\.?\s?cr|misc.*crim"),
    ("Criminal trial (magistrate)", r"crim|\bcri\b|\bcri\.|\bcr\b|\bcr\.|crl|\bcrm\b|\br\.?\s?c\.?\s?t\b|\bs\.?\s?c\.?\s?c\b|\br\.?\s?c\.?\s?c\b|summon|\bg\.?\s?r\b|\bn\.?\s?gr\b|\brct\b|p\.?\s?c\.?\s?r|final report|^f\.?\s?r\.?$|\bct\.?\s?case|warrant|excise|\bc\.?\s?c\.?\b|complaint|police|electricity|\bprc\b|\bchi\b|\bipc\b|\bucr\b|^s\.?\s?s\.?\b|^cha$|^cro$|^comi?$|^comp$|^c r case|^u\.?i\.?$"),
    ("Civil misc. / appeal", r"misc|arbitration|arbtn|succession|land acq|\bl\.?\s?a\.?\b|civil|appeal|petition|^o\.?p\.?\b|^c\.?a\.?$|^a\.?s\.?$|^r\.?\s?a\.?$|\br\.?\s?c\.?\s?a\b|^c\.?m\.?a?\.?$|\btrf\b|transfer|caveat|insolvency|rent|\bcoma\b|^l\.?a\.?[rc]$|^l i r|^m\.?c\.?a\.?$|^cp$|^cma|notice of motion|^tc$|^co$|^remp|^rp$|^ia$|^aoa|^w\.?c\.?$|^m\.?a\.?$|^arb|^ip$|misl|^op"),
]
TYPE_RULES_COMPILED = [(n, re.compile(rx)) for n, rx in TYPE_RULES]
TYPE_OTHER = "Other / unmapped"


def map_type(label: str | None) -> str:
    s = (label or "").strip().lower()
    for name, rx in TYPE_RULES_COMPILED:
        if rx.search(s):
            return name
    return TYPE_OTHER


# Dispositions: DDL already reduced these to 52 values. A transfer closes a file without resolving the
# dispute, which is why it is kept apart for the survival sensitivity check.
DISPOSITION_GROUPS: dict[str, str] = {
    "acquitted": "Merits", "convicted": "Merits", "allowed": "Merits", "dismissed": "Merits", "reject": "Merits",
    "judgement": "Merits", "decided": "Merits", "fine": "Merits", "partly decreed": "Merits",
    "contest-allowed": "Merits", "award": "Merits", "ex-parte": "Merits", "appeal accepted": "Merits",
    "probation": "Merits", "prison": "Merits", "quash": "Merits",
    "plead guilty": "Admission / plea", "confession": "Admission / plea", "plea bargaining": "Admission / plea",
    "compromise": "Settled / ADR", "settled": "Settled / ADR", "compounded": "Settled / ADR",
    "referred to lok adalat": "Settled / ADR", "disposal in lok adalat": "Settled / ADR",
    "uncontested": "Settled / ADR",
    "withdrawn": "Withdrawn / lapsed", "not press": "Withdrawn / lapsed", "abated": "Withdrawn / lapsed",
    "died": "Withdrawn / lapsed", "cancelled": "Withdrawn / lapsed", "closed": "Withdrawn / lapsed",
    "untrace": "Withdrawn / lapsed", "258 crpc": "Withdrawn / lapsed", "p.o. consign": "Withdrawn / lapsed",
    "absconded": "Withdrawn / lapsed", "sine die": "Withdrawn / lapsed",
    "transferred": "Transferred / committed", "committed": "Transferred / committed",
    "converted": "Transferred / committed", "remanded": "Transferred / committed",
    "bail granted": "Interim order", "bail refused": "Interim order", "bail rejected": "Interim order",
    "stayed": "Interim order",
    "disposed": "Generic 'disposed'", "disposed-otherwise": "Generic 'disposed'", "otherwise": "Generic 'disposed'",
    "other": "Generic 'disposed'", "procedural": "Generic 'disposed'",
    "disposition var missing": "Missing",
}


def map_disposition(label: str | None) -> str:
    if not label:
        return "Missing"
    return DISPOSITION_GROUPS.get(label.strip().lower(), "Generic 'disposed'")
