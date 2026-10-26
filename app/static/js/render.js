// DOM builders for results, trend charts, and history rows (§6.7, §6.9, §7.5).
// Every model-derived string goes through textContent via el(); no innerHTML anywhere.

import {
  BANDS,
  ITEM_TYPES,
  PRIORITIES,
  el,
  formatHours,
  formatMinutes,
  formatPercent,
  humanize,
  relativeDate,
  absoluteDate,
  absoluteTime,
  safeClass,
  safeUrl,
  domainOf,
} from "./format.js";

const BAND_FALLBACK = {
  strong: "Strong match",
  competitive: "Competitive",
  stretch: "Stretch",
  foundational_gap: "Foundational gaps",
};

const PRIORITY_LABEL = { critical: "Critical", high: "High", medium: "Medium", low: "Low" };
const IMPORTANCE_LABEL = { required: "Required", preferred: "Preferred", mentioned: "Mentioned" };
const STATUS_LABEL = {
  queued: "Queued",
  running: "Running",
  completed: "Completed",
  partial: "Partial",
  failed: "Failed",
};

const SVG_NS = "http://www.w3.org/2000/svg";

function svgEl(tag, props = {}) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined) continue;
    node.setAttribute(key, String(value));
  }
  return node;
}

function bandKey(value) {
  return safeClass(value, BANDS);
}

function bandLabel(value, explicit) {
  return explicit || BAND_FALLBACK[value] || humanize(value);
}

// ── small pieces ──────────────────────────────────────────────────────────

function statusPill(status) {
  const key = String(status ?? "queued");
  return el(
    "span",
    { class: `sm-status sm-status--${key}` },
    STATUS_LABEL[key] ?? humanize(key),
  );
}

function meter(value, label, { slim = false } = {}) {
  const clamped = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  return el("progress", {
    class: `sm-meter${slim ? " sm-meter--slim" : ""}`,
    max: "100",
    value: String(clamped),
    "aria-label": label,
    text: `${clamped}%`,
  });
}

function statTile({ label, value, unit = null, meta = null, hero = false, text = false }) {
  const valueNode = el(
    "p",
    { class: `sm-stat__value${text ? " sm-stat__value--text" : ""}` },
    String(value),
    unit ? el("span", { class: "sm-stat__unit", text: unit }) : null,
  );
  return el(
    "article",
    { class: `sm-stat${hero ? " sm-stat--hero" : ""}` },
    el("p", { class: "sm-stat__label", text: label }),
    valueNode,
    meta ? el("p", { class: "sm-stat__meta", text: meta }) : null,
  );
}

// ── score ─────────────────────────────────────────────────────────────────

function breakdownTable(rows) {
  const body = el("tbody");
  for (const row of rows ?? []) {
    body.append(
      el(
        "tr",
        {},
        el("th", { scope: "row", text: row.display_name }),
        el("td", { text: IMPORTANCE_LABEL[row.importance] ?? humanize(row.importance) }),
        el("td", { class: "sm-table__num", text: Number(row.weight).toFixed(1) }),
        el("td", { class: "sm-table__num", text: formatPercent(row.strength) }),
        el("td", { text: humanize(row.status) }),
      ),
    );
  }
  return el(
    "table",
    { class: "sm-table sm-table--compact sm-breakdown-table" },
    el("caption", { text: "How each skill contributed" }),
    el(
      "thead",
      {},
      el(
        "tr",
        {},
        el("th", { scope: "col", text: "Skill" }),
        el("th", { scope: "col", text: "Asked for" }),
        el("th", { scope: "col", class: "sm-table__num", text: "Weight" }),
        el("th", { scope: "col", class: "sm-table__num", text: "Your strength" }),
        el("th", { scope: "col", text: "Result" }),
      ),
    ),
    body,
  );
}

function scoreDetails(score) {
  return el(
    "details",
    { class: "sm-details" },
    el("summary", { text: "How this was calculated" }),
    el(
      "div",
      { class: "sm-details__body" },
      el("p", { text: score.formula }),
      el("p", {
        text: `Adjacent skills earn ${formatPercent(score.adjacent_credit)} of a required skill's weight.`,
      }),
      breakdownTable(score.breakdown),
    ),
  );
}

function scoreCard(score) {
  const band = bandKey(score.band);
  const counts = score.counts ?? {};
  const coverage = Number(score.coverage) || 0;

  return el(
    "section",
    {
      class: `sm-card sm-score-card${band ? ` sm-score-card--${band}` : ""}`,
      "aria-labelledby": "results-score-heading",
    },
    el(
      "div",
      { class: "sm-score-card__top" },
      el(
        "div",
        { class: "sm-score-card__value" },
        el("span", { class: "sm-score-card__number", text: String(score.value) }),
        el("span", { class: "sm-score-card__outof", text: "/ 100" }),
      ),
      el(
        "div",
        {},
        el("h2", {
          id: "results-score-heading",
          text: bandLabel(score.band, score.band_label),
        }),
        el("p", { class: "sm-muted", text: "Weighted coverage of the skills this job asks for." }),
      ),
    ),
    el(
      "div",
      { class: "sm-meter-block" },
      el(
        "div",
        { class: "sm-meter-block__head" },
        el("span", { text: "Requirement coverage" }),
        el("strong", { text: formatPercent(coverage) }),
      ),
      meter(coverage * 100, `Requirement coverage ${formatPercent(coverage)}`),
    ),
    el(
      "dl",
      { class: "sm-stat-row" },
      el("div", { class: "sm-stat" }, el("dt", { text: "Matched" }), el("dd", { text: String(counts.matched ?? 0) })),
      el("div", { class: "sm-stat" }, el("dt", { text: "Partial" }), el("dd", { text: String(counts.partial ?? 0) })),
      el("div", { class: "sm-stat" }, el("dt", { text: "Missing" }), el("dd", { text: String(counts.missing ?? 0) })),
    ),
    scoreDetails(score),
  );
}

export function renderScore(score) {
  return scoreCard(score);
}

// ── skills ────────────────────────────────────────────────────────────────

function skillRow(row) {
  const status = safeClass(row.status, ["matched", "partial", "missing"], "missing");
  return el(
    "li",
    { class: "sm-skill-row" },
    el(
      "span",
      { class: "sm-skill-row__name" },
      el("span", { class: `sm-dot sm-dot--${status}`, "aria-hidden": "true" }),
      el("span", { text: row.display_name }),
      el("span", {
        class: "sm-skill-row__importance",
        text: IMPORTANCE_LABEL[row.importance] ?? humanize(row.importance),
      }),
    ),
    el(
      "span",
      { class: "sm-skill-row__meter" },
      meter(row.strength * 100, `${row.display_name} strength ${formatPercent(row.strength)}`, { slim: true }),
      el("span", { class: "sm-skill-row__value", text: formatPercent(row.strength) }),
    ),
  );
}

function skillsCard(score) {
  const rows = [...(score.breakdown ?? [])].sort((a, b) => Number(b.strength) - Number(a.strength));
  return el(
    "section",
    { class: "sm-card", "aria-labelledby": "results-skills-heading" },
    el(
      "div",
      { class: "sm-card__head" },
      el(
        "div",
        {},
        el("h2", { id: "results-skills-heading", text: "Skill match" }),
        el("p", { class: "sm-card__sub", text: "How strongly your resume covers each skill the job asks for." }),
      ),
    ),
    el("ul", { class: "sm-skill-list" }, ...rows.map(skillRow)),
    el(
      "p",
      { class: "sm-legend" },
      el("span", {}, el("span", { class: "sm-dot sm-dot--matched", "aria-hidden": "true" }), "Matched"),
      el("span", {}, el("span", { class: "sm-dot sm-dot--partial", "aria-hidden": "true" }), "Partial"),
      el("span", {}, el("span", { class: "sm-dot sm-dot--missing", "aria-hidden": "true" }), "Missing"),
    ),
  );
}

// ── gaps ──────────────────────────────────────────────────────────────────

function gapCard(gap) {
  const priority = safeClass(gap.priority, PRIORITIES, "low");
  const card = el(
    "li",
    { class: `sm-gap sm-gap--${priority}` },
    el(
      "div",
      { class: "sm-gap__head" },
      el("span", {
        class: `sm-badge sm-badge--${priority}`,
        text: PRIORITY_LABEL[gap.priority] ?? humanize(gap.priority),
      }),
      el("h3", { text: gap.display_name }),
      el("span", {
        class: "sm-badge sm-badge--ghost",
        text: IMPORTANCE_LABEL[gap.jd_importance] ?? humanize(gap.jd_importance),
      }),
    ),
    el("p", { class: "sm-gap__reason", text: gap.gap_reason }),
    el(
      "dl",
      { class: "sm-gap__stats" },
      el("div", {}, el("dt", { text: "Score impact" }), el("dd", { text: `+${Math.round((Number(gap.impact) || 0) * 100)} pts` })),
      el("div", {}, el("dt", { text: "Time to close" }), el("dd", { text: formatHours(gap.estimated_hours) })),
      el("div", {}, el("dt", { text: "Your strength" }), el("dd", { text: formatPercent(gap.resume_strength) })),
      el("div", {}, el("dt", { text: "Category" }), el("dd", { text: humanize(gap.category) })),
    ),
  );

  if (Array.isArray(gap.aliases_checked) && gap.aliases_checked.length) {
    card.append(
      el(
        "details",
        { class: "sm-details" },
        el("summary", { text: "Aliases we checked" }),
        el("div", { class: "sm-details__body" }, el("p", { text: gap.aliases_checked.join(", ") })),
      ),
    );
  }
  return card;
}

export function renderGaps(gaps) {
  const section = el("section", { class: "sm-section", "aria-labelledby": "results-gaps-heading" });
  section.append(
    el(
      "div",
      { class: "sm-section-head" },
      el(
        "div",
        {},
        el("h2", { id: "results-gaps-heading", text: "Skill gaps" }),
        el("p", {
          class: "sm-card__sub",
          text: "Ordered by impact: the higher the priority, the more closing it raises your score.",
        }),
      ),
      el("span", { class: "sm-badge sm-badge--ghost", text: `${gaps.length} to close` }),
    ),
  );

  if (!gaps.length) {
    section.append(
      el(
        "div",
        { class: "sm-banner sm-banner--success", role: "status" },
        el("p", { text: "No gaps found — your resume already covers every skill this job asks for." }),
      ),
    );
    return section;
  }

  const visible = gaps.slice(0, 6);
  const rest = gaps.slice(6);
  section.append(el("ol", { class: "sm-gap-list" }, ...visible.map(gapCard)));

  if (rest.length) {
    const hiddenList = el("ol", { class: "sm-gap-list", hidden: true }, ...rest.map(gapCard));
    const toggle = el(
      "button",
      { type: "button", class: "sm-button sm-button--secondary sm-button--small" },
      `Show ${rest.length} more`,
    );
    toggle.addEventListener("click", () => {
      hiddenList.hidden = false;
      toggle.remove();
    });
    section.append(hiddenList, el("div", { class: "sm-actions" }, toggle));
  }
  return section;
}

// ── roadmap ───────────────────────────────────────────────────────────────

function resourceItem(resource) {
  const href = safeUrl(resource.url);
  const label = href
    ? el("a", { href, target: "_blank", rel: "noopener noreferrer" }, resource.label)
    : el("span", { text: resource.label });
  const meta = [resource.provider || domainOf(resource.url), resource.free ? "free" : null]
    .filter(Boolean)
    .join(" · ");
  return el("li", {}, label, meta ? el("span", { class: "sm-muted", text: meta }) : null);
}

function taskItem(item) {
  const type = safeClass(item.type, ITEM_TYPES, "read");
  return el(
    "li",
    { class: "sm-task" },
    el(
      "div",
      { class: "sm-task__head" },
      el("span", { class: `sm-task__type sm-task__type--${type}`, text: type }),
      el("h4", { text: item.title }),
      el("span", { class: "sm-muted sm-task__time", text: formatMinutes(item.est_minutes) }),
    ),
    item.details ? el("p", { class: "sm-task__details", text: item.details }) : null,
    item.resources?.length
      ? el("ul", { class: "sm-resource-list" }, ...item.resources.map(resourceItem))
      : null,
  );
}

function weekItem(week) {
  const headingId = `results-week-${week.week_number}-title`;
  return el(
    "li",
    { class: "sm-week" },
    el("div", { class: "sm-week__marker", "aria-hidden": "true", text: String(week.week_number) }),
    el(
      "div",
      { class: "sm-week__body" },
      el(
        "div",
        { class: "sm-week__head" },
        el("span", { class: "sm-week__number", text: `Week ${week.week_number}` }),
        el("h3", { id: headingId, text: week.theme }),
        el("span", { class: "sm-badge sm-badge--ghost", text: formatHours(week.hours) }),
      ),
      el("p", { class: "sm-week__objective", text: week.objective }),
      week.focus_skills?.length
        ? el(
            "p",
            { class: "sm-tags" },
            ...week.focus_skills.map((skill) => el("span", { class: "sm-tag", text: skill })),
          )
        : null,
      el("ul", { class: "sm-task-list" }, ...(week.items ?? []).map(taskItem)),
    ),
  );
}

export function renderRoadmap(roadmap, { weeks, hoursPerWeek, generatedAt } = {}) {
  const section = el("section", { class: "sm-section", "aria-labelledby": "results-roadmap-heading" });
  const weekList = roadmap?.weeks ?? [];
  const totalHours = weekList.reduce((sum, week) => sum + (Number(week.hours) || 0), 0);

  section.append(
    el(
      "div",
      { class: "sm-section-head" },
      el(
        "div",
        {},
        el("h2", {
          id: "results-roadmap-heading",
          text: `Your ${weeks ?? weekList.length}-week learning roadmap`,
        }),
        el("p", {
          class: "sm-card__sub",
          text: [hoursPerWeek ? `${hoursPerWeek} hours per week` : null, generatedAt ? `generated ${relativeDate(generatedAt)}` : null]
            .filter(Boolean)
            .join(" · "),
        }),
      ),
      weekList.length ? el("span", { class: "sm-badge sm-badge--ghost", text: `${totalHours}h total` }) : null,
    ),
  );

  if (!weekList.length) {
    section.append(
      el(
        "div",
        { class: "sm-banner sm-banner--warn", role: "status" },
        el("p", { text: "No roadmap was generated yet." }),
      ),
    );
    return section;
  }

  section.append(el("ol", { class: "sm-week-list" }, ...weekList.map(weekItem)));
  return section;
}

// ── page-level results ────────────────────────────────────────────────────

function warningBanner(warning, { onRetryRoadmap } = {}) {
  const degraded = warning.code === "DEGRADED_MODE";
  const roadmapFailed = warning.code === "ROADMAP_FAILED";
  const banner = el(
    "div",
    { class: `sm-banner sm-banner--${degraded ? "info" : roadmapFailed ? "warn" : "info"}`, role: "status" },
    el("p", { text: warning.message }),
  );
  if (roadmapFailed && onRetryRoadmap) {
    const button = el(
      "button",
      { type: "button", class: "sm-button sm-button--secondary sm-button--small" },
      "Retry roadmap",
    );
    button.addEventListener("click", () => onRetryRoadmap(button));
    banner.append(el("div", { class: "sm-banner__actions" }, button));
  }
  return banner;
}

function resultsHeader(analysis) {
  return el(
    "header",
    { class: "sm-page-head sm-result-head" },
    el(
      "div",
      { class: "sm-result-head__text" },
      el("p", { class: "sm-eyebrow" }, "Analysis · ", statusPill(analysis.status)),
      el("h1", { id: "results-title", text: analysis.role_label }),
      el(
        "p",
        { class: "sm-subtitle" },
        el("span", {
          text: [analysis.company, absoluteTime(analysis.created_at)].filter(Boolean).join(" · "),
        }),
      ),
    ),
  );
}

function summaryTiles(analysis) {
  const score = analysis.score;
  const counts = score.counts ?? {};
  const rows = score.breakdown ?? [];
  const gaps = analysis.gaps ?? [];
  const totalHours = gaps.reduce((sum, gap) => sum + (Number(gap.estimated_hours) || 0), 0);

  return el(
    "section",
    { class: "sm-kpi-grid", "aria-label": "Match at a glance" },
    statTile({
      label: "Match score",
      value: score.value,
      unit: "/100",
      meta: bandLabel(score.band, score.band_label),
      hero: true,
    }),
    statTile({
      label: "Skills matched",
      value: counts.matched ?? 0,
      unit: `/ ${rows.length}`,
      meta: `${counts.partial ?? 0} partial · ${counts.missing ?? 0} missing`,
    }),
    statTile({ label: "Open gaps", value: gaps.length, meta: "Prioritised by impact" }),
    statTile({
      label: "Hours to close",
      value: Math.round(totalHours),
      unit: "h",
      meta: "Estimated from the gap list",
    }),
  );
}

export function renderResults(root, analysis, { onRetryRoadmap, onDelete, onNewAnalysis } = {}) {
  const blocks = [resultsHeader(analysis)];

  if (analysis.status === "failed" && analysis.error?.message) {
    blocks.push(
      el(
        "div",
        { class: "sm-banner sm-banner--error", role: "alert" },
        el("strong", { text: "This analysis didn’t finish." }),
        el("p", { text: analysis.error.message }),
      ),
    );
  }

  if (analysis.status === "queued" || analysis.status === "running") {
    blocks.push(
      el(
        "div",
        { class: "sm-banner sm-banner--info", role: "status" },
        el(
          "p",
          {},
          el("a", { href: `/api/analyses/${encodeURIComponent(analysis.id)}` }, "This analysis is still running."),
          " Reload this page in a few seconds to see the result.",
        ),
      ),
    );
  }

  for (const warning of analysis.warnings ?? []) {
    blocks.push(warningBanner(warning, { onRetryRoadmap }));
  }

  if (analysis.score) {
    blocks.push(summaryTiles(analysis));
    blocks.push(
      el(
        "div",
        { class: "sm-grid-2 sm-grid-2--wide" },
        scoreCard(analysis.score),
        skillsCard(analysis.score),
      ),
    );
  }

  blocks.push(renderGaps(analysis.gaps ?? []));
  blocks.push(
    renderRoadmap(analysis.roadmap, {
      weeks: analysis.roadmap_weeks,
      hoursPerWeek: analysis.hours_per_week,
      generatedAt: analysis.roadmap?.generated_at,
    }),
  );

  blocks.push(
    el(
      "p",
      { class: "sm-muted sm-fineprint" },
      el("span", { text: `Scored with ${analysis.score?.formula ?? "weighted skill coverage"}.` }),
      analysis.cost?.usd
        ? el("span", {
            text: ` Cost $${Number(analysis.cost.usd).toFixed(4)} · ${analysis.cost.tokens_in + analysis.cost.tokens_out} tokens.`,
          })
        : null,
    ),
  );

  const actions = el(
    "div",
    { class: "sm-actions" },
    (() => {
      const button = el("button", { type: "button", class: "sm-button sm-button--secondary" }, "New analysis");
      button.addEventListener("click", () => onNewAnalysis?.());
      return button;
    })(),
    (() => {
      const button = el("button", { type: "button", class: "sm-button sm-button--ghost" }, "Print");
      button.addEventListener("click", () => window.print());
      return button;
    })(),
    (() => {
      const button = el("button", { type: "button", class: "sm-button sm-button--ghost sm-danger" }, "Delete analysis");
      button.addEventListener("click", () => onDelete?.(analysis));
      return button;
    })(),
  );
  blocks.push(actions);

  root.replaceChildren(...blocks);
}

export function renderError(root, error, { onRetry, onNewAnalysis } = {}) {
  const retry = el("button", { type: "button", class: "sm-button sm-button--primary" }, "Try again");
  retry.addEventListener("click", () => onRetry?.());
  const fresh = el("button", { type: "button", class: "sm-button sm-button--secondary" }, "Start a new analysis");
  fresh.addEventListener("click", () => onNewAnalysis?.());

  const panel = el(
    "div",
    { class: "sm-banner sm-banner--error", role: "alert", tabindex: "-1" },
    el("h1", { id: "error-title", text: "The analysis didn’t finish." }),
    el("p", { text: error?.message || "Something went wrong on our side." }),
    el("div", { class: "sm-banner__actions" }, retry, fresh),
  );

  if (error?.code || error?.requestId) {
    panel.append(
      el(
        "details",
        { class: "sm-details" },
        el("summary", { text: "Technical details" }),
        el(
          "div",
          { class: "sm-details__body" },
          error.code ? el("p", { text: `Code: ${error.code}` }) : null,
          error.requestId ? el("p", { text: `Request ID: ${error.requestId}` }) : null,
        ),
      ),
    );
  }

  root.replaceChildren(panel);
  panel.focus();
}

// ── trend chart ───────────────────────────────────────────────────────────

function shortDay(iso) {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return String(iso ?? "").slice(0, 10);
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function trendTooltipText(item) {
  const band = bandLabel(item.match_band);
  return `${item.match_score} · ${band}`;
}

function trendAriaLabel(item) {
  return `${absoluteDate(item.created_at)}${item.role_label ? `, ${item.role_label}` : ""}: match ${
    item.match_score
  } out of 100, ${bandLabel(item.match_band)}.`;
}

/**
 * Draw a single-series match-score trend.
 * @param {HTMLElement|null} root
 * @param {Array<object>} items API summaries, newest first
 * @returns {boolean} true when a chart was drawn
 */
export function renderTrend(root, items, { emptyMessage = "Run another analysis to see your score trend." } = {}) {
  if (!root) return false;

  const scored = (items ?? [])
    .filter((item) => item.match_score !== null && item.match_score !== undefined)
    .slice(0, 20)
    .reverse();

  if (scored.length < 2) {
    root.replaceChildren(el("p", { class: "sm-trend__empty", text: emptyMessage }));
    return false;
  }

  const chart = el("figure", { class: "sm-chart" });
  chart.append(
    el("figcaption", {
      class: "sm-visually-hidden",
      text: `Match score over ${scored.length} analyses, oldest to newest. Values are also listed in the analysis history.`,
    }),
  );

  const trend = el("div", { class: "sm-trend" });
  const plot = el("div", { class: "sm-trend__plot" });
  plot.append(el("div", { class: "sm-trend__grid", "aria-hidden": "true" }));

  const xAt = (index) => 2 + (index / (scored.length - 1)) * 96;
  const yAt = (score) => 96 - Math.max(0, Math.min(100, Number(score) || 0)) * 0.92;

  const points = scored.map((item, index) => ({
    item,
    x: xAt(index),
    y: yAt(item.match_score),
  }));

  const line = svgEl("svg", {
    class: "sm-trend__line",
    viewBox: "0 0 100 100",
    preserveAspectRatio: "none",
    "aria-hidden": "true",
    focusable: "false",
  });
  const d = points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`).join(" ");
  const area = `${d} L${points[points.length - 1].x.toFixed(2)} 100 L${points[0].x.toFixed(2)} 100 Z`;
  line.append(
    svgEl("path", { class: "sm-trend__area", d: area }),
    svgEl("path", { class: "sm-trend__line-stroke", d }),
  );
  plot.append(line);

  const tooltip = el("div", { class: "sm-trend__tooltip", hidden: true });
  const showTooltip = (point) => {
    tooltip.replaceChildren(
      el("strong", { text: trendTooltipText(point.item) }),
      el("span", {
        text: [shortDay(point.item.created_at), point.item.role_label].filter(Boolean).join(" · "),
      }),
    );
    tooltip.style.left = `${point.x}%`;
    tooltip.style.top = `${point.y}%`;
    tooltip.classList.toggle("sm-trend__tooltip--below", point.y < 30);
    tooltip.classList.toggle("sm-trend__tooltip--start", point.x < 12);
    tooltip.classList.toggle("sm-trend__tooltip--end", point.x > 88);
    tooltip.hidden = false;
  };
  const hideTooltip = () => {
    tooltip.hidden = true;
  };

  for (const point of points) {
    const dot = el("button", {
      type: "button",
      class: "sm-trend__pt",
      "aria-label": trendAriaLabel(point.item),
    });
    dot.style.left = `${point.x}%`;
    dot.style.top = `${point.y}%`;
    dot.addEventListener("pointerenter", () => showTooltip(point));
    dot.addEventListener("pointerleave", hideTooltip);
    dot.addEventListener("focus", () => showTooltip(point));
    dot.addEventListener("blur", hideTooltip);
    plot.append(dot);
  }

  const last = points[points.length - 1];
  const lastValue = el("span", {
    class: `sm-trend__value${last.y < 14 ? " sm-trend__value--below" : ""}`,
    "aria-hidden": "true",
    text: String(last.item.match_score),
  });
  lastValue.style.left = `${last.x}%`;
  lastValue.style.top = `${last.y}%`;
  plot.append(lastValue);
  plot.append(tooltip);
  trend.append(plot);

  const axis = el("div", { class: "sm-trend__xaxis", "aria-hidden": "true" });
  const labelIndices = scored.length > 2 ? [0, Math.floor((scored.length - 1) / 2), scored.length - 1] : [0, scored.length - 1];
  // Several analyses on one day share a label; show the day once so the axis
  // never reads "Oct 23 ... Oct 23" as if it were two different dates.
  const seenLabels = new Set();
  for (const index of labelIndices) {
    const label = el("span", { text: shortDay(scored[index].created_at) });
    if (seenLabels.has(label.textContent)) continue;
    seenLabels.add(label.textContent);
    label.style.left = `${points[index].x}%`;
    axis.append(label);
  }
  trend.append(axis);
  chart.append(trend);

  root.replaceChildren(chart);
  return true;
}

// ── dashboard recent list ─────────────────────────────────────────────────

/**
 * Keep "Recent analyses" in step with the API after an in-page analysis, without
 * reloading the dashboard. Mirrors the server-rendered card markup.
 * @param {HTMLElement|null} root
 * @param {Array<object>} items API summaries, newest first
 */
export function renderRecentList(root, items) {
  if (!root) return;

  const recent = (items ?? []).slice(0, 5);
  if (!recent.length) {
    root.replaceChildren(
      el(
        "div",
        { class: "sm-empty sm-empty--compact" },
        el("p", { class: "sm-empty__title", text: "No analyses yet" }),
        el("p", {
          class: "sm-muted",
          text: "Your first result will appear here with its score and gaps.",
        }),
      ),
    );
    return;
  }

  const list = el("ul", { class: "sm-analysis-list", id: "recent-list" });
  for (const item of recent) {
    const gaps = Number(item.gap_count) || 0;
    const foot = [];
    if (item.match_score === null || item.match_score === undefined) {
      foot.push(el("span", { class: "sm-badge sm-badge--ghost", text: "Not scored" }));
    } else {
      const band = bandKey(item.match_band);
      foot.push(
        el("span", {
          class: `sm-score-chip${band ? ` sm-score-chip--${band}` : ""}`,
          text: String(item.match_score),
        }),
        el("span", {
          class: "sm-analysis-card__band",
          text: bandLabel(item.match_band, item.band_label),
        }),
      );
    }
    foot.push(
      el("span", {
        class: "sm-analysis-card__gaps",
        text: `${gaps} gap${gaps === 1 ? "" : "s"}`,
      }),
    );

    list.append(
      el(
        "li",
        { class: "sm-analysis-card" },
        el(
          "a",
          {
            class: "sm-analysis-card__link",
            href: `/?analysis=${encodeURIComponent(item.id)}`,
          },
          el(
            "span",
            { class: "sm-analysis-card__top" },
            statusPill(item.status),
            el("time", {
              class: "sm-muted",
              datetime: item.created_at ?? "",
              text: absoluteDate(item.created_at),
            }),
          ),
          el("span", {
            class: "sm-analysis-card__title",
            text: item.role_label || "Untitled role",
          }),
          el("span", {
            class: "sm-analysis-card__company",
            text: item.company || "No company given",
          }),
          el("span", { class: "sm-analysis-card__foot" }, ...foot),
        ),
      ),
    );
  }

  root.replaceChildren(list);
}

// ── history ───────────────────────────────────────────────────────────────

export function renderHistoryRow(item) {
  const status = String(item.status ?? "queued");
  const scoreCell =
    item.match_score === null || item.match_score === undefined
      ? el("td", {}, el("span", { class: "sm-muted", text: "—" }))
      : el(
          "td",
          {},
          el("span", {
            class: `sm-score-chip${item.match_band ? ` sm-score-chip--${safeClass(item.match_band, BANDS)}` : ""}`,
            text: String(item.match_score),
          }),
          el("span", { class: "sm-table__secondary", text: bandLabel(item.match_band) }),
        );

  return el(
    "tr",
    { "data-analysis-row": item.id },
    el(
      "th",
      { scope: "row" },
      el("a", {
        class: "sm-table__primary",
        href: `/?analysis=${encodeURIComponent(item.id)}`,
        text: item.role_label,
      }),
      item.company ? el("span", { class: "sm-table__secondary", text: item.company }) : null,
    ),
    scoreCell,
    el("td", { class: "sm-table__num", text: String(item.gap_count ?? 0) }),
    el("td", {}, el("span", { class: `sm-status sm-status--${status}` }, STATUS_LABEL[status] ?? humanize(status))),
    el("td", {}, el("time", { datetime: item.created_at, text: relativeDate(item.created_at) })),
  );
}
