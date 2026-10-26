// Pure formatting helpers. No DOM access, no state (§7.2, §7.5).

const SAFE_PROTOCOLS = new Set(["http:", "https:"]);

export function safeUrl(raw) {
  if (!raw) return null;
  try {
    const url = new URL(String(raw), window.location.origin);
    return SAFE_PROTOCOLS.has(url.protocol) ? url.toString() : null;
  } catch {
    return null;
  }
}

export function domainOf(raw) {
  const safe = safeUrl(raw);
  if (!safe) return "";
  try {
    return new URL(safe).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}

/** Tiny element builder. Text always goes through textContent (§7.5). */
export function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (value === true) {
      node.setAttribute(key, "");
    } else {
      node.setAttribute(key, String(value));
    }
  }
  node.append(...children.filter((child) => child !== null && child !== undefined && child !== false));
  return node;
}

export function formatBytes(bytes) {
  const size = Number(bytes) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatHours(hours) {
  const value = Number(hours);
  if (!Number.isFinite(value)) return "—";
  if (value < 1) return `${Math.round(value * 60)} min`;
  return Number.isInteger(value) ? `${value}h` : `${value.toFixed(1)}h`;
}

export function formatMinutes(minutes) {
  const value = Number(minutes) || 0;
  if (value < 60) return `${value} min`;
  const hours = value / 60;
  return Number.isInteger(hours) ? `${hours}h` : `${hours.toFixed(1)}h`;
}

export function formatPercent(fraction) {
  const value = Number(fraction);
  if (!Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function relativeDate(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return String(iso).slice(0, 10);
  const seconds = Math.round((Date.now() - then.getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  if (seconds < 86400 * 7) return `${Math.floor(seconds / 86400)}d ago`;
  return absoluteDate(then);
}

export function absoluteDate(iso) {
  const value = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  return value.toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function absoluteTime(iso) {
  const value = new Date(iso);
  if (Number.isNaN(value.getTime())) return "";
  return value.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function capitalize(value) {
  const text = String(value ?? "");
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

export function humanize(value) {
  return capitalize(String(value ?? "").replace(/_/g, " "));
}

/** Fixed vocabulary — never take a label straight from the API and use it as a class. */
export const PRIORITIES = ["critical", "high", "medium", "low"];
export const BANDS = ["strong", "competitive", "stretch", "foundational_gap"];
export const ITEM_TYPES = ["read", "practice", "build", "assess"];

export function safeClass(value, allowlist, fallback = "") {
  const key = String(value ?? "");
  return allowlist.includes(key) ? key : fallback;
}
