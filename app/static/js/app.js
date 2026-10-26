// Boots the app, owns the state machine, wires events, drives polling (§7.2–§7.4).

import * as api from "./api.js";
import { clearTimer, reset, set, state } from "./state.js";
import { renderError, renderRecentList, renderResults, renderTrend } from "./render.js";
import {
  confirmDialog,
  focusHeading,
  scrollToTop,
  setButtonLoading,
  toast,
} from "./ui.js";
import { counterState, validateFile, validateJobText, validateResumeText } from "./validation.js";
import { formatBytes } from "./format.js";

const MAX_DELAY = 5000;
const INITIAL_DELAY = 1000;
const TERMINAL = new Set(["succeeded", "failed", "interrupted"]);
const POLL_ERROR_WINDOW_MS = 60_000;
const CANCEL_APPEARS_AFTER_MS = 10_000;
const LONG_ROADMAP_HINT_MS = 60_000;

const STAGE_PROGRESS = {
  extract_resume: 15,
  extract_jd: 40,
  score: 55,
  generate_roadmap: 75,
};

/** Read once from the data-* attributes on <body> (§7.6). */
function readConfig() {
  const body = document.body;
  const num = (name, fallback) => {
    const value = Number(body.dataset[name]);
    return Number.isFinite(value) && value > 0 ? value : fallback;
  };
  return Object.freeze({
    maxUploadMb: num("maxUploadMb", 5),
    maxResumeChars: num("maxResumeChars", 20000),
    maxJdChars: num("maxJdChars", 12000),
    minChars: num("minChars", 200),
    roadmapWeeks: num("roadmapWeeks", 6),
    hoursPerWeek: num("hoursPerWeek", 8),
    llmEnabled: body.dataset.llmEnabled === "true",
  });
}

const CONFIG = readConfig();

// ── element lookups (all optional: the same module runs on the help page) ──

const dom = {};

function cacheDom() {
  const byId = (id) => document.getElementById(id);
  dom.form = byId("analysis-form");
  dom.resumeText = byId("resume_text");
  dom.jdText = byId("jd_text");
  dom.jdTitle = byId("jd_title");
  dom.jdCompany = byId("jd_company");
  dom.weeks = byId("roadmap_weeks");
  dom.hours = byId("hours_per_week");
  dom.fileInput = byId("resume_file");
  dom.dropzone = byId("dropzone");
  dom.fileChip = byId("file-chip");
  dom.fileError = byId("file-error");
  dom.resumeError = byId("resume-error");
  dom.jdError = byId("jd-error");
  dom.formError = byId("form-error");
  dom.resumeHint = byId("resume-hint");
  dom.jdHint = byId("jd-hint");
  dom.submit = byId("submit-button");
  dom.tabs = byId("resume-tabs");
  dom.panels = { paste: byId("panel-paste"), upload: byId("panel-upload") };
  dom.screens = {
    input: byId("input-screen"),
    analyzing: byId("analyzing-screen"),
    results: byId("results-screen"),
    error: byId("error-screen"),
  };
  dom.resultsRoot = byId("results-root");
  dom.errorRoot = byId("error-root");
  dom.serverResults = byId("server-results");
  dom.progressBar = byId("progress-bar");
  dom.progressFill = byId("progress-fill");
  dom.progressValue = byId("progress-value");
  dom.progressTitle = byId("progress-title");
  dom.progressSubtitle = byId("progress-subtitle");
  dom.stageList = byId("stage-list");
  dom.backgroundButton = byId("background-button");
  dom.cancelButton = byId("cancel-button");
}

// ── screens ───────────────────────────────────────────────────────────────

function showScreen(name) {
  for (const [key, node] of Object.entries(dom.screens)) {
    if (node) node.hidden = key !== name;
  }
  if (dom.serverResults) dom.serverResults.hidden = name !== "input";
  set({ step: name });
}

// ── tabs (§6.5) ───────────────────────────────────────────────────────────

function selectedTab() {
  const active = dom.tabs?.querySelector('[role="tab"][aria-selected="true"]');
  return active?.dataset.panel ?? "paste";
}

function selectTab(panelName, { focus = false } = {}) {
  if (!dom.tabs) return;
  const tabs = [...dom.tabs.querySelectorAll('[role="tab"]')];
  for (const tab of tabs) {
    const active = tab.dataset.panel === panelName;
    tab.setAttribute("aria-selected", String(active));
    tab.classList.toggle("is-selected", active);
    tab.tabIndex = active ? 0 : -1;
    if (active && focus) tab.focus();
  }
  for (const [key, node] of Object.entries(dom.panels)) {
    if (node) node.hidden = key !== panelName;
  }
  // The tab decides whether a pasted resume or a file is required, so the submit
  // button must be re-evaluated after the switch, not only by the caller.
  syncSubmitState();
}

function wireTabs() {
  if (!dom.tabs) return;
  const tabs = [...dom.tabs.querySelectorAll('[role="tab"]')];

  dom.tabs.addEventListener("click", (event) => {
    const tab = event.target.closest('[role="tab"]');
    if (tab) selectTab(tab.dataset.panel);
  });

  dom.tabs.addEventListener("keydown", (event) => {
    const index = tabs.indexOf(document.activeElement);
    if (index === -1) return;
    const last = tabs.length - 1;
    let next = null;
    if (event.key === "ArrowRight") next = index === last ? 0 : index + 1;
    else if (event.key === "ArrowLeft") next = index === 0 ? last : index - 1;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = last;
    if (next === null) return;
    event.preventDefault();
    selectTab(tabs[next].dataset.panel, { focus: true });
  });
}

// ── file selection ────────────────────────────────────────────────────────

let selectedFile = null;

function setSelectedFile(file) {
  selectedFile = file;
  if (!dom.fileChip) return;

  if (!file) {
    dom.fileChip.hidden = true;
    dom.fileChip.replaceChildren();
    return;
  }

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "sm-chip__remove";
  remove.setAttribute("aria-label", `Remove ${file.name}`);
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    setSelectedFile(null);
    if (dom.fileInput) dom.fileInput.value = "";
    dom.fileInput?.focus();
  });

  dom.fileChip.replaceChildren(
    document.createTextNode(`${file.name} · ${formatBytes(file.size)}`),
    remove,
  );
  dom.fileChip.hidden = false;
}

function wireFileInput() {
  if (!dom.fileInput) return;

  dom.fileInput.addEventListener("change", () => {
    const file = dom.fileInput.files?.[0] ?? null;
    const message = file ? validateFile(file, { maxMb: CONFIG.maxUploadMb }) : null;
    showFieldError(dom.fileError, message);
    setSelectedFile(message ? null : file);
    if (message) dom.fileInput.value = "";
    syncSubmitState();
  });

  if (!dom.dropzone) return;

  const stop = (event) => {
    event.preventDefault();
    event.stopPropagation();
  };

  for (const type of ["dragenter", "dragover"]) {
    dom.dropzone.addEventListener(type, (event) => {
      stop(event);
      dom.dropzone.classList.add("is-dragover");
    });
  }
  for (const type of ["dragleave", "dragend", "drop"]) {
    dom.dropzone.addEventListener(type, (event) => {
      stop(event);
      dom.dropzone.classList.remove("is-dragover");
    });
  }

  dom.dropzone.addEventListener("drop", (event) => {
    const file = event.dataTransfer?.files?.[0];
    if (!file) return;
    const message = validateFile(file, { maxMb: CONFIG.maxUploadMb });
    showFieldError(dom.fileError, message);
    if (message) {
      setSelectedFile(null);
      return;
    }
    // Assign the dropped file to the input so the form submits it normally.
    const transfer = new DataTransfer();
    transfer.items.add(file);
    dom.fileInput.files = transfer.files;
    setSelectedFile(file);
    syncSubmitState();
  });
}

// ── validation ────────────────────────────────────────────────────────────

const touched = new Set();

function showFieldError(node, message) {
  if (!node) return;
  const field = node.closest("[role='tabpanel']") ?? node.parentElement;
  if (!message) {
    node.hidden = true;
    node.textContent = "";
    field?.classList.remove("has-error");
    return;
  }
  node.textContent = message;
  node.hidden = false;
  field?.classList.add("has-error");
}

function resumeFieldState() {
  if (selectedTab() === "upload") {
    if (selectedFile) return { message: null, valid: true };
    return { message: "Choose a file to continue.", valid: false };
  }
  const message = validateResumeText(dom.resumeText?.value, { min: CONFIG.minChars });
  return { message, valid: !message };
}

function jdFieldState() {
  const message = validateJobText(dom.jdText?.value, { min: CONFIG.minChars });
  return { message, valid: !message };
}

function syncSubmitState() {
  if (!dom.submit) return;
  const resume = resumeFieldState();
  const job = jdFieldState();
  dom.submit.disabled = !(resume.valid && job.valid) || state.submitting;
}

function wireValidation() {
  const bindCounter = (textarea, hint, max) => {
    if (!textarea || !hint) return;
    const update = () => {
      const { text, level } = counterState(textarea.value.length, { min: CONFIG.minChars, max });
      hint.textContent = text;
      hint.className = `sm-hint${level ? ` ${level}` : ""}`;
    };
    update();
    textarea.addEventListener("input", () => {
      update();
      const field = textarea === dom.resumeText ? "resume" : "job";
      if (touched.has(field)) {
        // Live validation only after the first attempt (§6.5).
        const message = field === "resume"
          ? (selectedTab() === "paste" ? resumeFieldState().message : null)
          : jdFieldState().message;
        showFieldError(field === "resume" ? dom.resumeError : dom.jdError, message);
      }
      syncSubmitState();
    });
    textarea.addEventListener("blur", () => {
      touched.add(textarea === dom.resumeText ? "resume" : "job");
      const message = textarea === dom.resumeText
        ? (selectedTab() === "paste" ? resumeFieldState().message : null)
        : jdFieldState().message;
      showFieldError(textarea === dom.resumeText ? dom.resumeError : dom.jdError, message);
      syncSubmitState();
    });
  };

  bindCounter(dom.resumeText, dom.resumeHint, CONFIG.maxResumeChars);
  bindCounter(dom.jdText, dom.jdHint, CONFIG.maxJdChars);

  for (const clearButton of document.querySelectorAll("[data-clear]")) {
    clearButton.addEventListener("click", () => {
      const target = document.getElementById(clearButton.dataset.clear);
      if (!target) return;
      target.value = "";
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.focus();
    });
  }

  syncSubmitState();
}

// ── submit ────────────────────────────────────────────────────────────────

function buildPayload() {
  const payload = {
    jd_text: dom.jdText?.value ?? "",
    jd_title: dom.jdTitle?.value?.trim() || null,
    jd_company: dom.jdCompany?.value?.trim() || null,
    roadmap_weeks: Number(dom.weeks?.value || CONFIG.roadmapWeeks),
    hours_per_week: Number(dom.hours?.value || CONFIG.hoursPerWeek),
  };
  if (selectedTab() === "upload" && selectedFile) {
    payload.file = selectedFile;
  } else {
    payload.resume_text = dom.resumeText?.value ?? "";
  }
  return payload;
}

function startProgressCopy() {
  if (dom.progressSubtitle) {
    dom.progressSubtitle.textContent = [dom.jdTitle?.value?.trim(), dom.jdCompany?.value?.trim()]
      .filter(Boolean)
      .join(" · ");
  }
  renderProgress({ stage: null, progress: 0 });
}

async function handleSubmit(event) {
  event.preventDefault();
  if (state.submitting) return;

  touched.add("resume");
  touched.add("job");
  const resume = resumeFieldState();
  const job = jdFieldState();
  showFieldError(dom.resumeError, resume.message);
  showFieldError(dom.jdError, job.message);
  showFieldError(dom.formError, null);

  if (!resume.valid || !job.valid) {
    const firstInvalid = resume.valid ? dom.jdText : (selectedTab() === "upload" ? dom.fileInput : dom.resumeText);
    firstInvalid?.focus();
    return;
  }

  set({ submitting: true, lastProgress: 0, pollDelay: INITIAL_DELAY });
  setButtonLoading(dom.submit, true, "Starting…");

  const payload = buildPayload();
  const formData = new FormData();
  for (const [key, value] of Object.entries(payload)) {
    if (value === null || value === undefined) continue;
    if (key === "file") formData.append("file", value, value.name);
    else formData.append(key, String(value));
  }

  try {
    const created = await api.postAnalysisFile(formData);
    set({ analysisId: created.analysis_id, jobId: created.job_id, submitting: false });
    startProgressCopy();
    showScreen("analyzing");
    focusHeading("#progress-title");
    armCancelButton();
    pollJob(created.job_id);
  } catch (error) {
    set({ submitting: false });
    setButtonLoading(dom.submit, false);
    syncSubmitState();
    if (error.code === "DUPLICATE_ANALYSIS" && error.details?.analysis_id) {
      toast("That identical analysis already exists — opening it.", { kind: "info" });
      openAnalysis(error.details.analysis_id);
      return;
    }
    showFieldError(dom.formError, error.message);
    toast(error.message, { kind: "error" });
  }
}

// ── progress ──────────────────────────────────────────────────────────────

function renderProgress(job) {
  const stage = job?.stage ?? null;
  const serverProgress = Number(job?.progress ?? 0);
  const mapped = stage ? Math.max(serverProgress, STAGE_PROGRESS[stage] ?? 0) : serverProgress;
  const progress = Math.max(state.lastProgress, mapped);
  set({ lastProgress: progress });

  if (dom.progressFill) dom.progressFill.style.width = `${progress}%`;
  if (dom.progressValue) dom.progressValue.textContent = `${progress}%`;
  if (dom.progressBar) dom.progressBar.setAttribute("aria-valuenow", String(progress));

  const order = ["extract_resume", "extract_jd", "score", "generate_roadmap"];
  const currentIndex = stage ? order.indexOf(stage) : -1;
  for (const node of dom.stageList?.querySelectorAll(".sm-stage") ?? []) {
    const index = order.indexOf(node.dataset.stage);
    const done = currentIndex === -1 ? false : index < currentIndex;
    const active = index === currentIndex && job?.status !== "succeeded";
    node.classList.toggle("is-done", done);
    node.classList.toggle("is-active", active);
    if (done) node.setAttribute("data-state", "done");
    else if (active) node.setAttribute("data-state", "active");
    else node.removeAttribute("data-state");
  }
}

let cancelTimer = null;
let hintTimer = null;

function armCancelButton() {
  if (cancelTimer) clearTimeout(cancelTimer);
  if (hintTimer) clearTimeout(hintTimer);
  if (dom.cancelButton) dom.cancelButton.hidden = true;

  cancelTimer = setTimeout(() => {
    if (dom.cancelButton) dom.cancelButton.hidden = false;
  }, CANCEL_APPEARS_AFTER_MS);

  hintTimer = setTimeout(() => {
    if (state.step !== "analyzing" || state.lastProgress < 55) return;
    const activeRow = dom.stageList?.querySelector('.sm-stage[data-stage="generate_roadmap"]');
    if (activeRow && !activeRow.querySelector(".sm-stage__hint")) {
      const hint = document.createElement("span");
      hint.className = "sm-stage__hint";
      hint.textContent = "Still working — the model is writing a detailed plan.";
      activeRow.append(hint);
    }
  }, LONG_ROADMAP_HINT_MS);
}

// ── polling (§7.4) ────────────────────────────────────────────────────────

export async function pollJob(jobId) {
  const startedAt = Date.now();
  let errorSince = null;

  async function tick() {
    let job;
    try {
      job = await api.getJob(jobId);
      errorSince = null;
    } catch (error) {
      if (error.status === 404) return fail("JOB_NOT_FOUND", error);
      errorSince ??= Date.now();
      if (Date.now() - errorSince < POLL_ERROR_WINDOW_MS) return schedule();
      return fail("POLL_TIMEOUT", error);
    }

    renderProgress(job);

    if (TERMINAL.has(job.status)) return finish(job);
    schedule();
  }

  function schedule() {
    clearTimer();
    set({ pollTimer: setTimeout(tick, state.pollDelay) });
    set({ pollDelay: Math.min(Math.round(state.pollDelay * 1.4), MAX_DELAY) });
  }

  async function finish(job) {
    clearTimer();
    if (job.status === "succeeded") {
      await openAnalysis(job.analysis_id);
      return;
    }
    set({
      step: "error",
      error: { code: job.error_code, message: job.error_message, requestId: null },
    });
    showError();
  }

  function fail(code, error) {
    clearTimer();
    set({ step: "error", error: { code, message: error?.message ?? code, requestId: error?.requestId } });
    showError();
  }

  tick();
}

// ── results ───────────────────────────────────────────────────────────────

function setCrumbs(label) {
  const crumbs = document.querySelector(".sm-crumbs");
  if (!crumbs) return;

  const link = (href, text) => {
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.textContent = text;
    return anchor;
  };
  const separator = () => {
    const span = document.createElement("span");
    span.setAttribute("aria-hidden", "true");
    span.textContent = "/";
    return span;
  };
  const current = document.createElement("span");
  current.textContent = label || "New analysis";

  const parts = [link("/", "Dashboard"), separator()];
  if (label) parts.push(link("/history", "History"), separator());
  parts.push(current);
  crumbs.replaceChildren(...parts);
}

const ACTIVE_NAV = { dashboard: "/", history: "/history", help: "/help" };

/** Keep the sidebar's current-page mark in step with the screen on show. */
function setActiveNav(page) {
  const target = ACTIVE_NAV[page] ?? null;
  for (const link of document.querySelectorAll(".sm-nav__link")) {
    const path = new URL(link.href, window.location.origin).pathname.replace(/\/+$/, "") || "/";
    const active = path === target;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
}

function openAnalysis(analysisId) {
  return api
    .getAnalysis(analysisId)
    .then((analysis) => {
      set({ analysis, analysisId: analysis.id, analysisStatus: analysis.status });
      history.replaceState(null, "", `/?analysis=${encodeURIComponent(analysis.id)}`);
      showResults(analysis);
      return analysis;
    })
    .catch((error) => {
      set({ step: "error", error });
      showError();
      return null;
    });
}

function showResults(analysis) {
  // The server-rendered copy exists only for the no-JS / pre-hydration path; once the
  // SPA has the data, one copy in the DOM keeps print output single (§6.12).
  dom.serverResults?.remove();
  dom.serverResults = null;

  setCrumbs(analysis.role_label);
  document.title = `${analysis.role_label} — SkillMirror`;
  showScreen("results");
  renderResults(dom.resultsRoot, analysis, {
    onRetryRoadmap: (button) => retryRoadmap(analysis, button),
    onDelete: (target) => deleteAnalysis(target),
    onNewAnalysis: () => startOver(),
    onRefresh: () => openAnalysis(analysis.id),
  });
  scrollToTop();
  focusHeading("#results-title");
}

function showError() {
  showScreen("error");
  renderError(dom.errorRoot, state.error, {
    onRetry: () => startOver({ keepInputs: true }),
    onNewAnalysis: () => startOver(),
  });
  scrollToTop();
}

async function retryRoadmap(analysis, button) {
  setButtonLoading(button, true, "Queueing…");
  try {
    const created = await api.retryRoadmap(analysis.id, {
      weeks: analysis.roadmap_weeks,
      hours_per_week: analysis.hours_per_week,
    });
    set({ jobId: created.job_id, analysisId: analysis.id, lastProgress: 55, pollDelay: INITIAL_DELAY });
    showScreen("analyzing");
    renderProgress({ stage: "generate_roadmap", progress: 55 });
    focusHeading("#progress-title");
    pollJob(created.job_id);
  } catch (error) {
    setButtonLoading(button, false);
    toast(error.message, { kind: "error" });
  }
}

async function deleteAnalysis(analysis) {
  const confirmed = await confirmDialog({
    title: "Delete this analysis?",
    body: "The resume text and roadmap will be removed from this machine.",
    confirmLabel: "Delete",
  });
  if (!confirmed) return;
  try {
    await api.deleteAnalysis(analysis.id);
    toast("Analysis deleted.", { kind: "success" });
    startOver();
  } catch (error) {
    toast(error.message, { kind: "error" });
  }
}

function startOver({ keepInputs = false } = {}) {
  const saved = keepInputs
    ? {
        resume: dom.resumeText?.value ?? "",
        jd: dom.jdText?.value ?? "",
        title: dom.jdTitle?.value ?? "",
        company: dom.jdCompany?.value ?? "",
      }
    : null;

  clearTimer();
  if (cancelTimer) clearTimeout(cancelTimer);
  if (hintTimer) clearTimeout(hintTimer);
  reset();

  if (saved) {
    if (dom.resumeText) dom.resumeText.value = saved.resume;
    if (dom.jdText) dom.jdText.value = saved.jd;
    if (dom.jdTitle) dom.jdTitle.value = saved.title;
    if (dom.jdCompany) dom.jdCompany.value = saved.company;
    dom.resumeText?.dispatchEvent(new Event("input", { bubbles: true }));
    dom.jdText?.dispatchEvent(new Event("input", { bubbles: true }));
  } else if (dom.form) {
    dom.form.reset();
    setSelectedFile(null);
    dom.resumeText?.dispatchEvent(new Event("input", { bubbles: true }));
    dom.jdText?.dispatchEvent(new Event("input", { bubbles: true }));
  }

  history.replaceState(null, "", "/");
  setCrumbs(null);
  setActiveNav("dashboard");
  document.title = "SkillMirror";
  showScreen("input");
  scrollToTop();
  syncSubmitState();
  // A just-finished analysis should already be in "Recent analyses" when the
  // dashboard comes back into view.
  wireOverview();
  refreshSummary();
  focusHeading("#page-title");
}

// ── cancel / background ───────────────────────────────────────────────────

function wireProgressControls() {
  dom.backgroundButton?.addEventListener("click", () => {
    if (state.jobId) {
      toast("Running in the background. Reopen this analysis from History when it's done.");
    }
    clearTimer();
    startOver({ keepInputs: true });
    showScreen("input");
  });

  dom.cancelButton?.addEventListener("click", async () => {
    if (!state.jobId) return;
    try {
      await api.cancelJob(state.jobId);
      toast("Analysis cancelled.");
    } catch (error) {
      toast(error.message, { kind: "error" });
    }
    clearTimer();
    startOver({ keepInputs: true });
  });
}

// ── shell / dashboard overview ────────────────────────────────────────────

function wireShell() {
  const toggle = document.getElementById("nav-toggle");
  const close = document.getElementById("nav-close");
  const sidebar = document.getElementById("sidebar");
  const scrim = document.getElementById("nav-scrim");
  if (!toggle || !sidebar) return;

  const mobile = window.matchMedia("(max-width: 1024px)");
  const isOpen = () => sidebar.classList.contains("is-open");

  const setOpen = (open, { restoreFocus = true } = {}) => {
    if (open && !mobile.matches) return;
    sidebar.classList.toggle("is-open", open);
    document.body.classList.toggle("is-nav-open", open);
    toggle.setAttribute("aria-expanded", String(open));
    if (scrim) scrim.hidden = !open;
    if (open) {
      (close ?? sidebar.querySelector("a, button"))?.focus();
    } else if (restoreFocus && sidebar.contains(document.activeElement)) {
      toggle.focus();
    }
  };

  toggle.addEventListener("click", () => setOpen(!isOpen()));
  close?.addEventListener("click", () => setOpen(false));
  scrim?.addEventListener("click", () => setOpen(false));

  for (const link of sidebar.querySelectorAll(".sm-nav__link")) {
    link.addEventListener("click", () => {
      if (mobile.matches) setOpen(false, { restoreFocus: false });
    });
  }

  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !isOpen()) return;
    setOpen(false);
  });

  mobile.addEventListener("change", (event) => {
    if (!event.matches) {
      sidebar.classList.remove("is-open");
      document.body.classList.remove("is-nav-open");
      toggle.setAttribute("aria-expanded", "false");
      if (scrim) scrim.hidden = true;
    }
  });
}

let overviewRequest = 0;

/**
 * The KPI tiles are computed by the server. After an in-page analysis the
 * dashboard is shown again without a reload, so re-read that markup rather
 * than duplicating the summary maths in JavaScript.
 */
let summaryRequest = 0;

async function refreshSummary() {
  const nodes = [...document.querySelectorAll("[data-summary]")];
  if (!nodes.length) return;

  const request = ++summaryRequest;
  try {
    const response = await fetch("/", {
      headers: { Accept: "text/html" },
      cache: "no-store",
    });
    if (!response.ok) return;
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    if (request !== summaryRequest) return;

    for (const node of nodes) {
      const key = node.dataset.summary;
      const fresh = doc.querySelector(`[data-summary="${CSS.escape(key)}"]`);
      if (!fresh) continue;
      node.replaceChildren(...[...fresh.childNodes].map((child) => child.cloneNode(true)));
      if (node.hidden !== fresh.hidden) node.hidden = fresh.hidden;
    }
  } catch {
    // Keep the values already on screen; they were correct when rendered.
  }
}

async function wireOverview() {
  const trendRoot = document.getElementById("trend-root");
  const historyTrendRoot = document.getElementById("history-trend-root");
  if (!trendRoot && !historyTrendRoot) return;

  const request = ++overviewRequest;
  let items;
  try {
    const page = await api.listAnalyses({ limit: 20 });
    items = page?.items ?? [];
  } catch {
    // The overview is an enhancement; the server-rendered lists still stand.
    return;
  }
  // A newer refresh (for example after a finished analysis) always wins.
  if (request !== overviewRequest) return;

  if (trendRoot) {
    const drawn = renderTrend(trendRoot, items, {
      emptyMessage: "Run two analyses to see how your match scores compare.",
    });
    const card = document.getElementById("trend-card");
    if (card) card.hidden = !drawn;
  }

  const recentRoot = document.getElementById("recent-root");
  if (recentRoot) renderRecentList(recentRoot, items);

  if (historyTrendRoot) {
    const drawn = renderTrend(historyTrendRoot, items, {
      emptyMessage: "Score two analyses to unlock the trend.",
    });
    const card = document.getElementById("history-trend-card");
    if (card) card.hidden = !drawn;
  }
}

// ── history page ──────────────────────────────────────────────────────────

function wireHistory() {
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete-analysis]");
    if (!button) return;
    event.preventDefault();
    const confirmed = await confirmDialog({
      title: "Delete this analysis?",
      body: "The resume text and roadmap will be removed from this machine.",
      confirmLabel: "Delete",
    });
    if (!confirmed) return;
    setButtonLoading(button, true, "Deleting…");
    try {
      const id = button.dataset.deleteAnalysis;
      await api.deleteAnalysis(id);
      // The table and the mobile card list each hold a copy of this row.
      for (const node of document.querySelectorAll(`[data-analysis-row="${CSS.escape(id)}"]`)) {
        node.remove();
      }
      toast("Analysis deleted.", { kind: "success" });
      if (!document.querySelector("[data-analysis-row]")) window.location.reload();
    } catch (error) {
      setButtonLoading(button, false);
      toast(error.message, { kind: "error" });
    }
  });
}

// ── boot ──────────────────────────────────────────────────────────────────

export function init() {
  cacheDom();
  wireShell();
  wireHistory();
  wireOverview();

  if (!dom.form) return;

  wireTabs();
  wireFileInput();
  wireValidation();
  wireProgressControls();

  dom.form.addEventListener("submit", handleSubmit);
  for (const tab of dom.tabs?.querySelectorAll('[role="tab"]') ?? []) {
    tab.addEventListener("click", () => {
      syncSubmitState();
      showFieldError(dom.resumeError, null);
      showFieldError(dom.fileError, null);
    });
  }

  // A reload of /?analysis={id} is server-rendered; the SPA replaces it with the live view.
  const fromUrl = new URLSearchParams(window.location.search).get("analysis");
  if (fromUrl) {
    openAnalysis(fromUrl);
    return;
  }

  showScreen("input");
  syncSubmitState();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init, { once: true });
} else {
  init();
}
