// Field rules and message lookup (§6.5, §7.2). Messages are the spec's verbatim copy.

export function validateResumeText(text, { min }) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return "Paste your resume to continue.";
  if (trimmed.length < min) {
    return `Add at least ${min} characters so there's enough to analyze.`;
  }
  return null;
}

export function validateJobText(text, { min }) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return "Paste the job description to continue.";
  if (trimmed.length < min) {
    return `Add at least ${min} characters so there's enough to analyze.`;
  }
  return null;
}

const ALLOWED = ["pdf", "docx"];

export function extensionOf(filename) {
  const name = String(filename ?? "");
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot + 1).toLowerCase();
}

export function validateFile(file, { maxMb }) {
  if (!file) return "Choose a file to continue.";
  const extension = extensionOf(file.name);
  if (extension === "doc") {
    return "Legacy .doc files aren't supported. Save as .docx or paste the text.";
  }
  if (!ALLOWED.includes(extension)) {
    return "Only PDF and DOCX files are supported.";
  }
  if (file.size > maxMb * 1024 * 1024) {
    return `That file is larger than ${maxMb} MB. Try a smaller PDF or paste the text.`;
  }
  if (file.size === 0) return "That file is empty. Try another one, or paste the text.";
  return null;
}

/** Counter copy plus a severity hint for the `is-warning` / `is-over` classes. */
export function counterState(length, { min, max }) {
  let level = "";
  if (length >= max) level = "is-over";
  else if (length < min) level = "is-warning";
  const suffix = length === 1 ? "character" : "characters";
  let text = `${length.toLocaleString()} ${suffix} · minimum ${min}`;
  if (level === "is-over") text += ` · limit ${max.toLocaleString()}`;
  return { text, level };
}
