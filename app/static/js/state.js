// Single mutable store + tiny pub/sub (§7.3).

export const initial = {
  step: "input",
  analysisId: null,
  jobId: null,
  pollTimer: null,
  pollDelay: 1000,
  lastProgress: 0,
  analysis: null,
  error: null,
  submitting: false,
};

const listeners = new Set();

export const state = { ...initial };

export function set(patch) {
  Object.assign(state, patch);
  for (const fn of listeners) fn(state);
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function clearTimer() {
  if (state.pollTimer) {
    clearTimeout(state.pollTimer);
    state.pollTimer = null;
  }
}

export function reset() {
  clearTimer();
  Object.assign(state, { ...initial });
  for (const fn of listeners) fn(state);
}
