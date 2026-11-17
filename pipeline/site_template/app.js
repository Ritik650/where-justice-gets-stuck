// The always-on static copy of the Where Justice Gets Stuck dashboard. pipeline/build_site.py writes the data and
// chart specs this script reads; the charts are the dashboard's own definitions (pipeline/charts.py) as Vega-Lite.
"use strict";

// ---------------------------------------------------------------------------------------------------- helpers
const cache = {};
const getJSON = (path) => (cache[path] ??= fetch(path).then((r) => {
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}));
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = (v) => typeof v === "number" && Number.isFinite(v);
const fmt = {
  int: (v) => (isNum(v) ? Math.round(v).toLocaleString("en-US") : "—"),
  pct: (v) => (isNum(v) ? `${Math.round(v * 100)}%` : "—"),
  pct1: (v) => (isNum(v) ? `${(v * 100).toFixed(1)}%` : "—"),
  num1: (v) => (isNum(v) ? v.toFixed(1) : "—"),
  num3: (v) => (isNum(v) ? v.toFixed(3) : "—"),
  signed3: (v) => (isNum(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(3)}` : "—"),
  signed1: (v) => (isNum(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(1)}` : "—"),
  lakh: (v) => (isNum(v) ? `${(v / 1e5).toFixed(1)} lakh` : "—"),
  crore: (v) => (isNum(v) ? `${(v / 1e7).toFixed(2)} crore` : "—"),
  text: (v) => esc(v ?? ""),
  bool: (v) => (v ? "Yes" : ""),
};
const chance = (p) => (p >= 0.995 ? "over 99%" : p < 0.005 ? "under 1%" : `${Math.round(p * 100)}%`);

async function chart(el, source) {
  try {
    const spec = typeof source === "string" ? structuredClone(await getJSON(source)) : source;
    el.innerHTML = "";
    if (spec.description) el.setAttribute("aria-label", spec.description);
    await vegaEmbed(el, spec, { actions: false, renderer: "svg" });
  } catch (err) {
    el.innerHTML = `<p class="text-caption text-muted">This chart could not be drawn (${esc(err.message)}).</p>`;
  }
}

// A chart slot with its caption, as the dashboard draws it.
function chartBox(id, caption = "") {
  return `<div class="chart bg-panel" id="${id}"></div>${caption ? `<p class="text-caption text-muted mt-2">${caption}</p>` : ""}`;
}

function table(rows, cols, { caption = "", maxHeight = "" } = {}) {
  const head = cols.map((c) => `<th class="py-2 px-3 font-medium whitespace-nowrap ${c.right ? "text-right" : ""}">${esc(c.label)}</th>`).join("");
  const body = rows.map((r) => `<tr class="border-b border-rowline hover:bg-canvas align-top">${cols.map((c) => {
    const v = c.get ? c.get(r) : r[c.key];
    const shown = (fmt[c.fmt || "text"] || fmt.text)(v);
    return `<td class="py-2 px-3 ${c.right ? "text-right whitespace-nowrap" : ""} ${c.wide ? "min-w-[16rem]" : ""}">${shown}</td>`;
  }).join("")}</tr>`).join("");
  return `<div class="overflow-x-auto bg-panel border border-hairline" ${maxHeight ? `style="max-height:${maxHeight};overflow-y:auto"` : ""}>
    <table class="w-full text-left border-collapse"${caption ? ` aria-label="${esc(caption)}"` : ""}>
      <thead class="sticky top-0"><tr class="bg-subdued border-b border-hairline text-label-sm text-muted">${head}</tr></thead>
      <tbody class="text-[13px]">${body}</tbody></table></div>`;
}

const kpi = (label, value, note = "", help = "") => `
  <div class="bg-panel border border-hairline p-4 flex flex-col justify-between" ${help ? `title="${esc(help)}"` : ""}>
    <span class="text-caption text-muted font-medium">${esc(label)}</span>
    <div class="my-2"><span class="text-kpi-metric">${esc(value)}</span></div>
    ${note ? `<span class="text-caption text-muted">${esc(note)}</span>` : ""}
  </div>`;

const findingBlock = (entry) => `
  <div class="bg-panel border border-hairline p-4 mb-5">
    <p class="text-[14px] leading-[22px]"><strong>Finding.</strong> ${esc(entry.finding)}</p>
    <p class="text-caption text-muted mt-2">Read with care: ${esc(entry.caveat)}</p>
  </div>`;

// A segmented control (the Stitch tab style). Returns the container; calls onPick(option) on change and once at start.
function segmented(container, options, initial, onPick) {
  container.classList.add("seg", "flex", "flex-wrap", "border-b", "border-hairline", "mb-5");
  container.innerHTML = options.map((o) => `<button type="button" class="px-4 py-2 text-[14px] text-muted border-b-2 border-transparent -mb-px hover:text-ink" aria-pressed="${o === initial}">${esc(o)}</button>`).join("");
  container.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    container.querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    onPick(b.textContent);
  }));
  onPick(initial);
}

// Multi-select pills (the Stitch chip style). onChange receives the selected values.
function pills(container, options, onChange) {
  container.innerHTML = options.map((o) => `<button type="button" class="pill border border-hairline px-3 py-1 text-[12px] text-body hover:border-muted" aria-pressed="false">${esc(o)}</button>`).join("");
  container.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
    b.setAttribute("aria-pressed", String(b.getAttribute("aria-pressed") !== "true"));
    onChange([...container.querySelectorAll('button[aria-pressed="true"]')].map((x) => x.textContent));
  }));
}

const select = (id, label, options, value) => `
  <label class="flex flex-col gap-1 text-label-sm text-muted min-w-[10rem]">${esc(label)}
    <select id="${id}" class="bg-panel border border-hairline text-ink text-[14px] py-2 pl-3 pr-8 focus:outline-none focus:border-ink">
      ${options.map((o) => `<option value="${esc(o.value ?? o)}" ${String(o.value ?? o) === String(value) ? "selected" : ""}>${esc(o.label ?? o)}</option>`).join("")}
    </select></label>`;

const slugify = (t) => t.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

// ---------------------------------------------------------------------------------------------------- findings
const QUESTIONS = [["District map", "q5"], ["Where cases get stuck", "q1"], ["How long justice takes", "q2"], ["Which laws clog the system", "q3"],
  ["Do judge transfers slow cases", "q4"], ["Women in court", "q6"], ["When the backlog clears", "q7"], ["How cases end", "q8"],
  ["First hearing", "q9"], ["What drives delay", "q10"]];
const MAP_METRICS = ["Median years to close", "Clearance rate, 2016-18", "New cases per lakh people, per year", "Closed within 2 years, mix-adjusted"];

async function renderFindings(page) {
  const S = await getJSON("data/summary.json");
  const F = S.figures;
  page.innerHTML = `
    <h1 class="text-headline-lg">Where Justice Gets Stuck</h1>
    <p class="text-[16px] leading-[26px] text-body mt-2 max-w-3xl">Where and why Indian lower courts are delayed, from ${(F.total_rows / 1e6).toFixed(1)} million cases filed 2010-2018 (Development Data Lab).</p>
    <p class="text-caption text-muted mt-1">Case data ends in 2018. 2026 figures are NJDG context. Nothing here describes current court performance.</p>
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4 my-6">
      ${kpi("Cases analysed", `${(F.total_rows / 1e6).toFixed(1)}M`, "", "Every case filed 2010-2018 in the DDL eCourts data.")}
      ${kpi("Open at end of 2018", fmt.crore(F.open_at_cutoff), "", "Filed 2010-2018 and undecided on 31 Dec 2018.")}
      ${kpi("Median time to close", `${fmt.int(F.q2_km_median)} days`, `Closed cases alone: ${fmt.int(F.q2_naive_median)} days`, "Kaplan-Meier, with open cases counted.")}
      ${kpi("Pending in 2026 (NJDG)", fmt.crore(F.njdg_total), "District and subordinate courts", "30 Jul 2026, Lok Sabha Q.3371.")}
    </div>
    <div id="qtabs"></div>
    <h2 class="text-[20px] font-semibold mb-4" id="qtitle"></h2>
    <div id="qbody"></div>
    <hr class="border-hairline my-10">
    <div class="grid grid-cols-1 lg:grid-cols-5 gap-8">
      <div class="lg:col-span-3 text-[14px] leading-[22px] text-body">
        <p class="font-semibold mb-2">How to read this</p>
        <ul class="list-disc ml-5 space-y-2">
          <li><strong>Open means undecided on 31 Dec 2018.</strong> Recorded decisions fall by about 90% in early 2019 because only some courts were collected again, so one shared cut-off keeps courts comparable.</li>
          <li><strong>Early years are thin.</strong> Rows per year rise ${F.cov_growth.toFixed(1)}x from 2010 to 2018 as records went digital. Flow rates use 2016-18 only.</li>
          <li><strong>Older cases are missing.</strong> Only cases filed from 2010 appear, so backlogs and disposals are both understated.</li>
          <li><strong>Two independent checks support the picture.</strong> DDL's open cases by state track NJDG's 2026 pendency shares (correlation ${F.cov_corr.toFixed(2)}), and states slow here also hold NJDG's oldest cases (rank correlation ${F.cov_age_spearman.toFixed(2)}).</li>
          <li><strong>These are associations.</strong> Nothing here proves why a court is slow.</li>
        </ul>
      </div>
      <div class="lg:col-span-2">
        <p class="font-semibold text-[14px] mb-1">Data quality</p>
        <p class="text-caption text-muted mb-3">${F.dq_rules} rules, case-weighted across states. A low score means hard-to-use records, not a poor court.</p>
        <div class="grid grid-cols-2 gap-3">${["Completeness", "Validity", "Consistency", "Linkage"].map((d) => kpi(d, fmt.pct1(S.quality[d]))).join("")}</div>
        <p class="text-[13px] mt-3 flex flex-wrap gap-4"><a class="underline" href="#/quality">Open the data-quality explorer</a>
          <a class="underline" href="downloads/data_quality_scorecard.xlsx">Scorecard (Excel)</a>
          <a class="underline" href="downloads/where_justice_gets_stuck_brief.pdf">Two-page brief (PDF)</a></p>
      </div>
    </div>`;
  segmented($("#qtabs", page), QUESTIONS.map((q) => q[0]), "District map", (label) => {
    const key = QUESTIONS.find((q) => q[0] === label)[1];
    $("#qtitle", page).textContent = S.text[key].question;
    const body = $("#qbody", page);
    body.innerHTML = findingBlock(S.text[key]);
    QUESTION_RENDERERS[key](body, S);
  });
}

const QUESTION_RENDERERS = {
  async q5(body) {
    body.insertAdjacentHTML("beforeend", `<div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
      <div class="lg:col-span-3">${select("map-metric", "Metric", MAP_METRICS, MAP_METRICS[0])}<div class="mt-3">${chartBox("q5-map",
        "Districts on 2011 boundaries. Grey means no usable data: no DDL rows, too few cases, or incomplete closure records. Boundaries: DataMeet (CC BY 4.0), for display only and not an official map.")}</div></div>
      <div class="lg:col-span-2"><div id="q5-order"></div><div id="q5-table"></div><div id="q5-flagged" class="mt-4"></div></div></div>`);
    const draw = () => chart($("#q5-map", body), `specs/q5_${slugify($("#map-metric", body).value)}.json`);
    $("#map-metric", body).addEventListener("change", draw);
    draw();
    const d = await getJSON("data/q5.json");
    const cols = [{ key: "district", label: "District (2011)" }, { key: "state", label: "State" }, { key: "km_median_days", label: "Median days", fmt: "int", right: true },
      { key: "clearance_rate", label: "Clearance", fmt: "pct", right: true }, { key: "closed_2y_adjusted", label: "Closed in 2y", fmt: "pct", right: true }];
    segmented($("#q5-order", body), ["Slowest", "Fastest"], "Slowest", (o) => { $("#q5-table", body).innerHTML = table(o === "Slowest" ? d.slowest : d.fastest, cols, { caption: `${o} districts` }); });
    $("#q5-flagged", body).innerHTML = `<details class="bg-panel border border-hairline p-3"><summary class="text-[13px] font-medium">${d.flagged.length} districts left off for incomplete closure records</summary><div class="mt-3">${table(d.flagged, [
      { key: "district", label: "District (2011)" }, { key: "state", label: "State" }, { key: "total_cases", label: "Cases", fmt: "int", right: true },
      { key: "bail_closed_2y", label: "Bail closed in 2y", fmt: "pct", right: true }, { key: "closed_2y_raw", label: "All closed in 2y", fmt: "pct", right: true }])}</div></details>`;
  },
  q1(body) {
    body.insertAdjacentHTML("beforeend", `<div id="q1-family"></div>${chartBox("q1-chart", "Cases with no decision date, by the purpose of their last listed hearing. The State profile page shows each state's stages.")}`);
    segmented($("#q1-family", body), ["All", "Criminal", "Civil"], "All", (f) => chart($("#q1-chart", body), `specs/q1_${f.toLowerCase()}.json`));
  },
  async q2(body) {
    body.insertAdjacentHTML("beforeend", `<div id="q2-dim"></div>${chartBox("q2-chart", "Kaplan-Meier curves. Cases still open count until 31 Dec 2018 and then leave the risk set, so they are never dropped. A line stops where follow-up stops.")}<div id="q2-table" class="mt-4"></div>`);
    const t = await getJSON("data/q2.json");
    const dims = { "Case type": "case-category", State: "state", "Filing year": "filing-year", "What counts as closed": "closed" };
    segmented($("#q2-dim", body), Object.keys(dims), "Case type", (label) => {
      const key = dims[label];
      chart($("#q2-chart", body), `specs/q2_${key}.json`);
      const cols = key === "closed"
        ? [{ key: "grp", label: "Definition" }, { key: "n", label: "Cases", fmt: "int", right: true }, { key: "closed", label: "Closed", fmt: "int", right: true }]
        : [{ key: "grp", label: "Group" }, { key: "n", label: "Cases", fmt: "int", right: true }, { key: "naive_median_days", label: "Median days, closed only", fmt: "int", right: true }];
      cols.push({ key: "km_median_days", label: "Median days, open counted", fmt: "int", right: true }, { key: "open_after_1y", label: "Open after 1y", fmt: "pct", right: true },
        { key: "open_after_3y", label: "Open after 3y", fmt: "pct", right: true }, { key: "open_after_5y", label: "Open after 5y", fmt: "pct", right: true });
      $("#q2-table", body).innerHTML = table(t[key], cols, { caption: "Survival summary" });
    });
  },
  async q3(body, S) {
    const F = S.figures;
    body.insertAdjacentHTML("beforeend", `${chartBox("q3-chart", "Named acts with at least 1 lakh cases. Up and right is both common and slow; a larger bubble means more open cases.")}
      <p class="font-semibold text-[14px] mt-6 mb-3">Testing the Section 138 claim</p>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">${kpi("NI Act, open end-2018 (DDL)", fmt.lakh(F.q3_ni_open))}${kpi("Same, adding case-type labels", fmt.lakh(F.q3_ni_open_widest))}
        ${kpi("Supreme Court, end-2019", fmt.lakh(F.q3_sc_benchmark), "Includes older filings")}${kpi("eCourtsIndia index, Oct 2026", `${Math.round(F.q3_blog_benchmark / 1e5)} lakh+`, "Includes appeals; not comparable")}</div>
      <p class="text-caption text-muted mt-2 mb-5">DDL is a floor: it leaves out older cases, and act records are thin for early years. The figures differ in date and scope, so read them as an order of magnitude.</p>
      <div id="q3-view"></div><div id="q3-table"></div>`);
    chart($("#q3-chart", body), "specs/q3_acts.json");
    const t = await getJSON("data/q3.json");
    segmented($("#q3-view", body), ["Acts", "Largest sections"], "Acts", (v) => {
      $("#q3-table", body).innerHTML = v === "Acts"
        ? table(t.acts, [{ key: "act_canonical", label: "Act" }, { key: "act_family", label: "Family" }, { key: "n", label: "Cases", fmt: "int", right: true },
          { key: "open_at_cutoff", label: "Open end-2018", fmt: "int", right: true }, { key: "share_of_open", label: "Share of open", fmt: "pct", right: true },
          { key: "km_median_days", label: "Median days, open counted", fmt: "int", right: true }, { key: "naive_median_days", label: "Median days, closed only", fmt: "int", right: true }], { maxHeight: "480px" })
        : table(t.sections, [{ key: "act_canonical", label: "Act" }, { key: "section_norm", label: "Section" }, { key: "n", label: "Cases", fmt: "int", right: true },
          { key: "open_at_cutoff", label: "Open end-2018", fmt: "int", right: true }, { key: "naive_median_days", label: "Median days, closed only", fmt: "int", right: true }], { maxHeight: "480px" });
    });
  },
  async q4(body, S) {
    const t = await getJSON("data/q4.json");
    body.insertAdjacentHTML("beforeend", `<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div><p class="font-semibold text-[14px] mb-2">The plain comparison looks damning</p>${chartBox("q4-a", `${fmt.int(t.pairs)} matched groups of trials. Biased: a slow case has more time in which to see a transfer.`)}</div>
      <div><p class="font-semibold text-[14px] mb-2">The fairer test shows a modest effect</p>${chartBox("q4-b", `${fmt.int(t.tenure)} matched groups of trials, closed and open alike. The judge's time left at filing cannot be caused by the case being slow.`)}</div></div>
      <div class="mt-5">${table(t.rows.sort((a, b) => a.gap - b.gap), [{ key: "type", label: "Case type" }, { key: "stays", label: "Judge stays 2+ years", fmt: "pct", right: true },
        { key: "leaves", label: "Judge leaves within 6 months", fmt: "pct", right: true }, { key: "gap", label: "Gap (points)", fmt: "signed1", right: true }])}</div>
      <p class="text-caption text-muted mt-2">Share of cases closed within two years. For scale, a judge stays a median of ${fmt.int(S.figures.q4_tenure_median_days)} days in one post.</p>`);
    chart($("#q4-a", body), "specs/q4_judges.json");
    chart($("#q4-b", body), "specs/q4_tenure.json");
  },
  async q6(body) {
    body.insertAdjacentHTML("beforeend", `<div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
      <div class="lg:col-span-2">${chartBox("q6-roles", "Share of women among cases with a classifiable name.")}<div id="q6-table" class="my-4"></div>${chartBox("q6-trend", "By filing year. Early years have fewer records.")}</div>
      <div class="lg:col-span-3"><div id="q6-role"></div>${chartBox("q6-stack", "States with at least 20,000 cases, sorted by women's share of classified names.")}</div></div>`);
    chart($("#q6-roles", body), "specs/q6_roles.json");
    chart($("#q6-trend", body), "specs/q6_trend.json");
    $("#q6-table", body).innerHTML = table(await getJSON("data/q6.json"), [{ key: "role", label: "Role" }, { key: "women_share", label: "Women", fmt: "pct", right: true },
      { key: "classified_share", label: "Names classifiable", fmt: "pct", right: true }]);
    segmented($("#q6-role", body), ["Petitioner", "Defendant", "Petitioner's advocate", "Defendant's advocate"], "Petitioner's advocate",
      (r) => chart($("#q6-stack", body), `specs/q6_${slugify(r)}.json`));
  },
  async q7(body) {
    const t = await getJSON("data/q7.json");
    body.insertAdjacentHTML("beforeend", `${chartBox("q7-chart", "2026 pendency (NJDG) divided by 2016-18 disposals (DDL). States with under 20,000 pending cases are left out of the chart.")}
      <p class="font-semibold text-[14px] mt-8 mb-1">Try a scenario</p>
      <p class="text-caption text-muted mb-4">Starts from NJDG's July 2026 pendency and each state's 2016-18 flows. A scenario to explore, not a forecast.</p>
      <div class="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div class="lg:col-span-2 space-y-4">${select("sc-state", "State", t.states.map((s) => s.njdg_state), "Bihar")}
          <label class="block text-label-sm text-muted">Change in disposals per year: <span id="sc-d-out" class="text-ink"></span>
            <input id="sc-d" type="range" min="-20" max="100" step="5" value="25" class="w-full"></label>
          <label class="block text-label-sm text-muted">Change in filings per year: <span id="sc-f-out" class="text-ink"></span>
            <input id="sc-f" type="range" min="-50" max="50" step="5" value="0" class="w-full"></label></div>
        <div class="lg:col-span-3"><div class="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-3" id="sc-kpis"></div>${chartBox("sc-chart", "")}</div></div>
      <div class="mt-6">${table(t.table, [{ key: "njdg_state", label: "State" }, { key: "pending_total", label: "Pending, 2026", fmt: "int", right: true },
        { key: "pending_over_10y", label: "Over 10 years", fmt: "int", right: true }, { key: "pending_5_to_10y", label: "5-10 years", fmt: "int", right: true },
        { key: "filed_per_year", label: "Filed per year", fmt: "int", right: true }, { key: "closed_per_year", label: "Closed per year", fmt: "int", right: true },
        { key: "clearance_rate", label: "Clearance", fmt: "pct", right: true }, { key: "years_of_disposals_njdg_stock", label: "Years of disposals", fmt: "num1", right: true },
        { key: "never_clears", label: "Filings outran disposals", fmt: "bool" }], { maxHeight: "520px" })}</div>`);
    chart($("#q7-chart", body), "specs/q7_backlog.json");
    const template = await getJSON("specs/q7_scenario.json");
    const update = () => {
      const s = t.states.find((x) => x.njdg_state === $("#sc-state", body).value);
      const extra = +$("#sc-d", body).value, filings = +$("#sc-f", body).value;
      $("#sc-d-out", body).textContent = `${extra}%`;
      $("#sc-f-out", body).textContent = `${filings}%`;
      const stock = s.pending_total, filed = s.filed_per_year * (1 + filings / 100), closed = s.closed_per_year * (1 + extra / 100), net = closed - filed;
      const needed = (filed + stock / 10) / s.closed_per_year - 1;
      $("#sc-kpis", body).innerHTML = kpi("Years to clear", net > 0 ? (stock / net).toFixed(1) : "Never", "", "Pending cases divided by disposals minus filings.")
        + kpi("Pending after 10 years", fmt.lakh(Math.max(0, stock - net * 10))) + kpi("Disposals rise to clear in 10 years", `${needed >= 0 ? "+" : ""}${Math.round(needed * 100)}%`);
      const spec = structuredClone(template);
      const name = Object.keys(spec.datasets)[0];
      spec.datasets[name] = Array.from({ length: 21 }, (_, y) => ({ year: y, pending: Math.max(0, stock - net * y) }));
      spec.description = `${s.njdg_state}: pending cases under this scenario.`;
      chart($("#sc-chart", body), spec);
    };
    ["sc-state", "sc-d", "sc-f"].forEach((id) => $(`#${id}`, body).addEventListener("input", update));
    update();
  },
  async q8(body) {
    const t = await getJSON("data/q8.json");
    body.insertAdjacentHTML("beforeend", `<div id="q8-dim"></div>${chartBox("q8-chart", "Closed cases only, sorted by share decided on merits. 'Vague or missing' covers labels such as 'disposed'.")}
      <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mt-6">
        <div><p class="font-semibold text-[14px] mb-2">How long each ending takes</p>${table(t.national, [{ key: "outcome", label: "Outcome" },
          { key: "closed_cases", label: "Closed cases", fmt: "int", right: true }, { key: "share", label: "Share", fmt: "pct", right: true },
          { key: "median_days", label: "Median days, closed only", fmt: "int", right: true }])}
          <p class="text-caption text-muted mt-2">Closed cases only, so these medians understate how long cases take.</p></div>
        <div><p class="font-semibold text-[14px] mb-2">Verdicts in criminal cases</p>${table(t.verdicts, [{ key: "grp", label: "Case type" },
          { key: "closed_cases", label: "Closed", fmt: "int", right: true }, { key: "verdict_share", label: "Closed with a verdict", fmt: "pct", right: true },
          { key: "conviction_share", label: "Convicted, of verdicts", fmt: "pct", right: true }])}</div></div>`);
    segmented($("#q8-dim", body), ["Case type", "State"], "Case type", (d) => chart($("#q8-chart", body), `specs/q8_${slugify(d).replace(/-/g, "_")}.json`));
  },
  async q9(body) {
    body.insertAdjacentHTML("beforeend", `<div class="grid grid-cols-1 md:grid-cols-2 gap-6"><div>${chartBox("q9-chart", "States with at least 20,000 cases that have a usable first-hearing date.")}</div>
      <div><p class="font-semibold text-[14px] mb-2">By case type</p><div id="q9-table"></div></div></div>`);
    chart($("#q9-chart", body), "specs/q9_states.json");
    $("#q9-table", body).innerHTML = table(await getJSON("data/q9.json"), [{ key: "grp", label: "Case type" }, { key: "median_days", label: "Median days", fmt: "int", right: true },
      { key: "p90_days", label: "90th percentile", fmt: "int", right: true }, { key: "within_30_days", label: "Within 30 days", fmt: "pct", right: true }]);
  },
  q10(body) {
    body.insertAdjacentHTML("beforeend", `<div class="grid grid-cols-1 md:grid-cols-2 gap-6">
      <div><p class="font-semibold text-[14px] mb-2">By state, compared with Maharashtra</p>${chartBox("q10-a", "Right of the line, a case closes faster than a comparable case in Maharashtra; left, slower.")}</div>
      <div><p class="font-semibold text-[14px] mb-2">By case type, compared with magistrate trials</p>${chartBox("q10-b", "Bail and traffic matters close far faster than a magistrate trial.")}
        <p class="font-semibold text-[14px] mt-6 mb-2">People involved</p>${chartBox("q10-c", "A named advocate often marks a contested case, so these are associations.")}</div></div>`);
    chart($("#q10-a", body), "specs/q10_state.json");
    chart($("#q10-b", body), "specs/q10_case_type.json");
    chart($("#q10-c", body), "specs/q10_people.json");
  },
};

// ---------------------------------------------------------------------------------------------------- state profile
async function renderState(page) {
  const index = await getJSON("data/states/index.json");
  page.innerHTML = `<div class="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-hairline pb-6 mb-6">
      <h1 class="text-headline-lg">State profile</h1>
      ${select("state-pick", "State", index.map((s) => ({ value: s.slug, label: s.state })), "bihar")}</div><div id="state-body"></div>`;
  const draw = async () => {
    const d = await getJSON(`data/states/${$("#state-pick", page).value}.json`);
    const k = d.kpis;
    const body = $("#state-body", page);
    const flaggedNote = d.flagged.length ? `<div class="bg-panel border border-hairline border-l-2 border-l-accent p-4 mb-5 text-[13px]"><strong>${d.flagged.length} districts need care.</strong>
        ${esc(d.flagged.join(", "))} appear to have incomplete closure records, which raises this state's median.${d.excl_median ? ` Without them, the median falls to ${fmt.int(d.excl_median)} days.` : ""}</div>` : "";
    const njdgNote = d.njdg_name !== d.state ? `<p class="text-caption text-muted mb-4">NJDG reports ${esc(d.state)} together with its neighbouring territory, so 2026 figures are for both.</p>` : "";
    body.innerHTML = `${flaggedNote}${njdgNote}
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">${kpi("Cases filed, 2010-18", fmt.lakh(k.filed), `India: ${fmt.crore(k.filed_india)}`)}
        ${kpi("Median days to close", isNum(k.median) ? fmt.int(k.median) : "Not reached", `India: ${fmt.int(k.median_india)}`, "Kaplan-Meier, with open cases counted.")}
        ${kpi("Still open after 5 years", fmt.pct(k.open5), `India: ${fmt.pct(k.open5_india)}`)}</div>
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 mt-4">${isNum(k.pending) ? kpi("Pending, Jul 2026", fmt.lakh(k.pending), `India: ${fmt.crore(k.pending_india)}`, "NJDG, Lok Sabha Q.3371.")
        + kpi("Pending 5+ years, 2026", fmt.pct(k.old_share), `India: ${fmt.pct(k.old_share_india)}`) + kpi("Years of disposals to clear", fmt.num1(k.years), `India: ${fmt.num1(k.years_india)}`, "2026 pendency divided by 2016-18 disposals, if filings stopped.")
        : `<p class="text-caption text-muted">NJDG's 2026 table has no separate row for this state.</p>`}</div>
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-8 mt-8">
        <div><h2 class="text-headline-sm mb-2">How long cases take</h2>${chartBox("st-surv", "Kaplan-Meier curves, with all cases in India for comparison.")}</div>
        <div><h2 class="text-headline-sm mb-2">Where open cases sit</h2>${d.stages ? chartBox("st-stage", "Cases with no decision date, by the purpose of their last listed hearing.") : `<p class="text-caption text-muted">No never-closed cases are recorded for this state.</p>`}</div>
        <div><h2 class="text-headline-sm mb-2">Districts</h2>${d.districts.length ? table(d.districts, [{ key: "district", label: "District (2011)" },
          { key: "km_median_days", label: "Median days", fmt: "int", right: true }, { key: "clearance_rate", label: "Clearance", fmt: "pct", right: true },
          { key: "closed_2y_adjusted", label: "Closed in 2y", fmt: "pct", right: true }, { key: "filed_per_lakh_year", label: "Filed per lakh, per year", fmt: "int", right: true }], { maxHeight: "420px" })
          : `<p class="text-caption text-muted">No district in this state has enough cases to rank.</p>`}</div>
        <div><h2 class="text-headline-sm mb-2">Largest open caseloads, by act</h2>${table(d.acts, [{ key: "act_canonical", label: "Act" }, { key: "n", label: "Cases", fmt: "int", right: true },
          { key: "open_at_cutoff", label: "Open end-2018", fmt: "int", right: true }], { maxHeight: "420px" })}</div>
        <div><h2 class="text-headline-sm mb-2">How cases end</h2>${chartBox("st-out", "Closed cases only, with all cases in India for comparison.")}</div>
        <div><h2 class="text-headline-sm mb-2">Data quality</h2>${table(d.quality, [{ key: "dimension", label: "Dimension" }, { key: "state", label: d.state, fmt: "pct1", right: true },
          { key: "india", label: "India", fmt: "pct1", right: true }])}<p class="text-caption text-muted mt-2">A low score means hard-to-use records, not a poor court.</p></div></div>`;
    chart($("#st-surv", body), d.survival);
    if (d.stages) chart($("#st-stage", body), d.stages);
    chart($("#st-out", body), d.outcomes);
  };
  $("#state-pick", page).addEventListener("change", draw);
  await draw();
}

// ---------------------------------------------------------------------------------------------------- data quality
async function renderQuality(page) {
  const [S, Q] = await Promise.all([getJSON("data/summary.json"), getJSON("data/quality.json")]);
  const F = S.figures;
  page.innerHTML = `<h1 class="text-headline-lg">Data quality</h1>
    <p class="text-[14px] text-body mt-2 mb-6 max-w-3xl">${F.dq_rules} rules ran over all ${(F.total_rows / 1e6).toFixed(1)} million cases, and ${F.dq_failed} found failures.
      A low score means the records are hard to use. It says nothing about how well a court performs.</p>
    <div id="dq-view"></div><div id="dq-body"></div>`;
  const body = $("#dq-body", page);
  const views = {
    Scorecard() {
      body.innerHTML = `<div class="grid grid-cols-1 lg:grid-cols-5 gap-8"><div class="lg:col-span-3">${chartBox("dq-heat", "Scores by state and dimension, best overall at the top. Each score is 100% minus the severity-weighted failure rate of that dimension's rules.")}</div>
        <div class="lg:col-span-2"><p class="font-semibold text-[14px] mb-2">Quality by filing year</p>${chartBox("dq-lines", "National scores for cases filed in each year. Linkage rises sharply from 2014 because act records are thin before then.")}
        <p class="text-[13px] mt-4"><a class="underline" href="downloads/data_quality_scorecard.xlsx">Download the Excel scorecard</a></p>
        <p class="text-caption text-muted">Its scores are live formulas, so changing a severity weight recalculates every score.</p></div></div>`;
      chart($("#dq-heat", body), "specs/dq_heat.json");
      chart($("#dq-lines", body), "specs/dq_lines.json");
    },
    Rules() {
      body.innerHTML = `<div class="flex flex-wrap items-end gap-6 mb-4"><div><p class="text-label-sm text-muted mb-1">Dimension</p><div id="r-dim" class="flex flex-wrap gap-2"></div></div>
        <div><p class="text-label-sm text-muted mb-1">Severity</p><div id="r-sev" class="flex flex-wrap gap-2"></div></div>
        <label class="flex items-center gap-2 text-[13px]"><input id="r-failed" type="checkbox" class="accent-ink"> Only rules that found failures</label></div>
        <div id="r-table"></div><div class="mt-4">${select("r-sql", "See a rule's SQL", Q.rules.map((r) => ({ value: r.rule_id, label: `${r.rule_id}  ${r.title}` })), Q.rules[0].rule_id)}
        <pre id="r-sql-text" class="bg-panel border border-hairline p-4 mt-2 text-[12px] overflow-x-auto whitespace-pre-wrap"></pre></div>`;
      const state = { dim: [], sev: [] };
      const draw = () => {
        let rows = Q.rules;
        if (state.dim.length) rows = rows.filter((r) => state.dim.includes(r.dimension));
        if (state.sev.length) rows = rows.filter((r) => state.sev.includes(r.severity));
        if ($("#r-failed", body).checked) rows = rows.filter((r) => r.failures > 0);
        $("#r-table", body).innerHTML = table(rows, [{ key: "rule_id", label: "Rule" }, { key: "title", label: "What fails", wide: true }, { key: "dimension", label: "Dimension" },
          { key: "severity", label: "Severity" }, { key: "status", label: "Status" }, { key: "failures", label: "Failures", fmt: "int", right: true },
          { key: "failure_rate", label: "Rate", fmt: "pct1", right: true }, { key: "treatment", label: "Treatment", wide: true }], { maxHeight: "560px" });
      };
      pills($("#r-dim", body), [...new Set(Q.rules.map((r) => r.dimension))].sort(), (v) => { state.dim = v; draw(); });
      pills($("#r-sev", body), ["High", "Medium", "Low", "Info"], (v) => { state.sev = v; draw(); });
      $("#r-failed", body).addEventListener("change", draw);
      const showSql = () => { $("#r-sql-text", body).textContent = Q.rules.find((r) => r.rule_id === $("#r-sql", body).value)?.sql || ""; };
      $("#r-sql", body).addEventListener("change", showSql);
      draw();
      showSql();
    },
    "Issue log"() {
      body.innerHTML = `<div class="flex flex-wrap items-end gap-6 mb-4"><label class="flex flex-col gap-1 text-label-sm text-muted">Search issues
          <input id="i-search" type="search" placeholder="for example, bail or 138" class="bg-panel border border-hairline text-ink text-[14px] py-2 px-3 w-72 focus:outline-none focus:border-ink"></label>
        <div><p class="text-label-sm text-muted mb-1">Severity</p><div id="i-sev" class="flex flex-wrap gap-2"></div></div>
        <div><p class="text-label-sm text-muted mb-1">Status</p><div id="i-status" class="flex flex-wrap gap-2"></div></div></div>
        <div id="i-table"></div><p class="text-caption text-muted mt-2" id="i-count"></p>`;
      const state = { sev: [], status: [] };
      const draw = () => {
        const q = $("#i-search", body).value.trim().toLowerCase();
        let rows = Q.issues;
        if (q) rows = rows.filter((r) => [r.issue, r.evidence, r.treatment].some((x) => String(x || "").toLowerCase().includes(q)));
        if (state.sev.length) rows = rows.filter((r) => state.sev.includes(r.severity));
        if (state.status.length) rows = rows.filter((r) => state.status.includes(r.status));
        $("#i-table", body).innerHTML = table(rows, [{ key: "issue_id", label: "ID" }, { key: "source", label: "Source" }, { key: "issue", label: "Issue", wide: true },
          { key: "severity", label: "Severity" }, { key: "status", label: "Status" }, { key: "evidence", label: "Evidence or samples", wide: true },
          { key: "treatment", label: "Treatment", wide: true }], { maxHeight: "620px" });
        $("#i-count", body).textContent = `${rows.length} issues shown. Samples use DDL's case ID only; the linkable eCourts number was dropped at load.`;
      };
      pills($("#i-sev", body), ["High", "Medium", "Low", "Info"], (v) => { state.sev = v; draw(); });
      pills($("#i-status", body), ["Open", "Mitigated", "Accepted"], (v) => { state.status = v; draw(); });
      $("#i-search", body).addEventListener("input", draw);
      draw();
    },
    Coverage() {
      body.innerHTML = `<div class="grid grid-cols-1 lg:grid-cols-5 gap-8"><div class="lg:col-span-3"><p class="font-semibold text-[14px] mb-2">How complete each state's records are</p>
          ${chartBox("cv-heat", `Filings in each year as a share of the state's 2018 filings. Rows per year grow ${F.cov_growth.toFixed(1)} times nationally as records went digital.`)}</div>
        <div class="lg:col-span-2"><p class="font-semibold text-[14px] mb-2">DDL against NJDG</p>${chartBox("cv-share", `Each state's share of open cases in DDL against its share of NJDG's 2026 pendency (correlation ${F.cov_corr.toFixed(2)}).`)}
          <p class="font-semibold text-[14px] mt-6 mb-2">Why every result uses one cut-off</p>${chartBox("cv-cliff", "Recorded decisions fall by about 90% in early 2019 because only some courts were collected again later.")}</div></div>`;
      chart($("#cv-heat", body), "specs/dq_coverage.json");
      chart($("#cv-share", body), "specs/dq_share.json");
      chart($("#cv-cliff", body), "specs/dq_cliff.json");
    },
  };
  segmented($("#dq-view", page), Object.keys(views), "Scorecard", (v) => views[v]());
}

// ---------------------------------------------------------------------------------------------------- delay-risk model
async function renderModel(page) {
  let M;
  try { M = await getJSON("data/model.json"); } catch {
    page.innerHTML = `<h1 class="text-headline-lg">Delay risk model</h1><p class="text-[14px] mt-3">The model's tables are not in this build.</p>`;
    return;
  }
  const S = await getJSON("data/summary.json");
  const s = M.summary, gap = s.gaps.m2_vs_b1_court, h = M.headline, year = s.test_year;
  page.innerHTML = `<h1 class="text-headline-lg">Delay risk model</h1>
    <p class="text-[16px] leading-[26px] text-body mt-2 max-w-3xl">Predicts, on the day a case is filed, whether it will be decided within 24 months, and measures how much that adds over each court's own history.</p>
    <div class="bg-panel border border-hairline border-l-2 border-l-accent p-4 my-5 text-[13px]"><strong>Research only.</strong> A proof of concept on ${Math.round(s.sample.sampled / 1e5)} lakh cases filed 2010-${year}.
      It must never be used to decide anything about an individual case, litigant or judge.
      <a class="underline" href="${S.repository}/blob/main/reports/ml_poc_report.md">Full report</a> | <a class="underline" href="${S.repository}/blob/main/docs/model_card.md">Model card</a></div>
    <div class="grid grid-cols-2 lg:grid-cols-4 gap-4">
      ${kpi(`Test ROC-AUC, ${year} filings`, fmt.num3(h.m2.roc_auc_seen), `Brier score ${fmt.num3(h.m2_cal.brier_seen)}, calibrated`, "LightGBM (M2). 0.5 is chance; 1.0 ranks every case correctly.")}
      ${kpi("Court history alone (B1)", fmt.num3(h.b1.roc_auc_seen), "Court's disposal rate last year")}
      ${kpi("Gain over court history", fmt.signed3(gap.gap), `95% interval ${fmt.signed3(gap.ci_low)} to ${fmt.signed3(gap.ci_high)}`, "1,000 bootstrap resamples of whole courts.")}
      ${kpi("Courts never seen in training", fmt.num3(h.m2.roc_auc_unseen), `${fmt.int(s.rows.test_unseen)} cases`, "Ten percent of courts were held out of training entirely.")}</div>
    <div class="grid grid-cols-1 lg:grid-cols-5 gap-8 mt-8">
      <div class="lg:col-span-3"><h2 class="text-headline-sm mb-2">Model comparison</h2>${table(M.metrics, [{ key: "model", label: "Model" }, { key: "roc_auc_seen", label: "ROC-AUC", fmt: "num3", right: true },
        { key: "pr_auc_seen", label: "PR-AUC", fmt: "num3", right: true }, { key: "brier_seen", label: "Brier score", fmt: "num3", right: true },
        { key: "roc_auc_unseen", label: "Unseen courts", fmt: "num3", right: true }])}
        <p class="text-caption text-muted mt-2">Court features alone reach ${fmt.num3(s.court_only_auc)}; case features alone ${fmt.num3(s.case_only_auc)}.
        ${s.case_only_auc >= s.court_only_auc ? "More of what predicts delay is what a case is than where it is filed." : "More of what predicts delay is where a case is filed than what it is."}</p></div>
      <div class="lg:col-span-2"><h2 class="text-headline-sm mb-2">Calibration</h2>${chartBox("m-cal", `Ten groups of ${year} test cases by predicted chance. Points on the grey diagonal are well calibrated.`)}</div></div>
    <h2 class="text-headline-sm mt-10 mb-3">What-if: a typical case in one court</h2>
    <div class="flex flex-wrap gap-4" id="wi-pick"></div>
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-8 mt-4"><div id="wi-result"></div><div class="lg:col-span-2">${chartBox("wi-chart", "")}</div></div>
    <p class="text-caption text-muted mt-2" id="wi-note"></p>
    <h2 class="text-headline-sm mt-10 mb-3">Where the model is weakest</h2><div id="sl-dim"></div><div id="sl-table"></div>
    <p class="text-caption text-muted mt-2">Slices with at least 1,000 test cases and 100 of each outcome, weakest first. Run <code>${esc(s.m2_run_id)}</code>, evaluation <code>${esc(s.evaluation_run_id)}</code> in reports/experiments.csv.</p>`;
  chart($("#m-cal", page), "specs/model_calibration.json");
  segmented($("#sl-dim", page), ["State", "Case type", "Court level"], "State", (d) => {
    const rows = M.slices.filter((r) => r.dimension === d).sort((a, b) => a.auc_m2 - b.auc_m2);
    $("#sl-table", page).innerHTML = table(rows, [{ key: "slice", label: d }, { key: "n", label: "Test cases", fmt: "int", right: true },
      { key: "positive_rate", label: "Decided within 24 months", fmt: "pct", right: true }, { key: "auc_m2", label: "Model ROC-AUC", fmt: "num3", right: true },
      { key: "auc_b1", label: "Court history ROC-AUC", fmt: "num3", right: true }, { key: "auc_gap", label: "Gain", fmt: "signed3", right: true }], { maxHeight: "460px" });
  });
  // The what-if: state > district > court > case type, each list narrowed by the one before.
  const [W, template] = await Promise.all([getJSON("data/whatif.json"), getJSON("specs/model_whatif.json")]);
  const pick = $("#wi-pick", page);
  const states = Object.keys(W).sort();
  // One selection; changing a level clears the levels below it, which then fall back to their defaults.
  const sel = { state: states.includes("Maharashtra") ? "Maharashtra" : states[0], district: null, court: null, type: null };
  const draw = () => {
    const districts = Object.keys(W[sel.state]).sort();
    if (!districts.includes(sel.district)) sel.district = districts[0];
    const courtMap = W[sel.state][sel.district];
    const courts = Object.entries(courtMap).map(([id, c]) => ({ value: id, label: `${c.name} (${c.level}, no. ${id.split("-").pop()})` }))
      .sort((a, b) => a.label.localeCompare(b.label));
    if (!courtMap[sel.court]) sel.court = courts[0].value;
    const types = Object.keys(courtMap[sel.court].types).sort();
    // Bail closes in days almost everywhere, so a magistrate trial or a civil suit is the more telling default.
    if (!types.includes(sel.type)) sel.type = ["Criminal trial (magistrate)", "Civil suit"].find((t) => types.includes(t)) || types[0];
    pick.innerHTML = select("wi-state", "State", states, sel.state) + select("wi-district", "District", districts, sel.district)
      + select("wi-court", "Court", courts, sel.court) + select("wi-type", "Case type", types, sel.type);
    const on = (id, apply) => $(`#${id}`, pick).addEventListener("change", (e) => { apply(e.target.value); draw(); });
    on("wi-state", (v) => { Object.assign(sel, { state: v, district: null, court: null, type: null }); });
    on("wi-district", (v) => { Object.assign(sel, { district: v, court: null, type: null }); });
    on("wi-court", (v) => { Object.assign(sel, { court: v, type: null }); });
    on("wi-type", (v) => { sel.type = v; });
    const ty = sel.type;
    const [pm, pb1, pb2, obs, n] = courtMap[sel.court].types[ty];
    $("#wi-result", page).innerHTML = kpi("Chance of a decision within 24 months", chance(pm), `Model (M2), filed July ${year}`);
    const values = [{ what: "Model (M2)", value: pm, focus: "model" }, { what: "Court's history (B1)", value: pb1, focus: "context" },
      { what: "Court's history for this case type (B2)", value: pb2, focus: "context" }];
    if (obs !== null) values.push({ what: `Observed in the ${year} sample (${fmt.int(n)} cases)`, value: obs, focus: "context" });
    const spec = structuredClone(template);
    spec.datasets[Object.keys(spec.datasets)[0]] = values;
    spec.height = 34 * values.length + 30;
    chart($("#wi-chart", page), spec);
    $("#wi-note", page).textContent = `A typical ${ty.toLowerCase()} case: the most common act, section and parties for this type in training, filed in July ${year} with the court's history as of the end of ${year - 1}. B1 and B2 are disposal rates mapped onto the same chance with 2015 data.`;
  };
  draw();
}

// ---------------------------------------------------------------------------------------------------- methods
async function renderMethods(page) {
  const m = await getJSON("data/methods.json");
  page.innerHTML = `<div class="grid grid-cols-1 lg:grid-cols-4 gap-8"><article class="prose lg:col-span-3">${marked.parse(m.markdown)}</article>
    <aside><p class="font-semibold text-[14px] mb-2">Downloads</p><ul class="text-[13px] space-y-2">
      <li><a class="underline" href="downloads/where_justice_gets_stuck_brief.pdf">Two-page brief (PDF)</a></li>
      <li><a class="underline" href="downloads/data_quality_scorecard.xlsx">Excel scorecard</a></li></ul></aside></div>`;
}

// ---------------------------------------------------------------------------------------------------- router
const PAGES = { findings: renderFindings, state: renderState, quality: renderQuality, model: renderModel, methods: renderMethods };
const rendered = {};

async function route() {
  const name = (location.hash.replace(/^#\/?/, "") || "findings").split("/")[0];
  const key = PAGES[name] ? name : "findings";
  document.querySelectorAll("section[data-page]").forEach((s) => { s.hidden = s.dataset.page !== key; });
  document.querySelectorAll("#nav a").forEach((a) => {
    const on = a.dataset.nav === key;
    a.classList.toggle("text-accent", on);
    a.classList.toggle("border-accent", on);
    a.classList.toggle("font-semibold", on);
    a.classList.toggle("text-muted", !on);
    a.toggleAttribute("aria-current", on);
  });
  if (!rendered[key]) {
    rendered[key] = true;
    const section = document.querySelector(`section[data-page="${key}"]`);
    section.innerHTML = `<p class="text-caption text-muted">Loading...</p>`;
    try { await PAGES[key](section); } catch (err) {
      section.innerHTML = `<p class="text-[14px]">This page could not load its data (${esc(err.message)}).</p>`;
      rendered[key] = false;
    }
  }
  window.scrollTo(0, 0);
}

(async () => {
  const S = await getJSON("data/summary.json").catch(() => null);
  if (S) {
    $("#sources").textContent = S.sources;
    $("#live-link").href = S.live;
    $("#code-link").href = S.repository;
    $("#footer-links").innerHTML = [["Report on the model", `${S.repository}/blob/main/reports/ml_poc_report.md`], ["Methods", "#/methods"],
      ["Data dictionary", `${S.repository}/blob/main/docs/data_dictionary.md`], ["Code", S.repository]]
      .map(([t, u]) => `<a class="text-body hover:text-accent underline decoration-hairline" href="${u}">${t}</a>`).join("");
  }
  window.addEventListener("hashchange", route);
  route();
})();
