// Toasts, banners, dialogs, focus, skeletons (§6.9, §6.11).

import { el } from "./format.js";

const TOAST_MS = 5000;

export function toast(message, { kind = "info", timeout = TOAST_MS } = {}) {
  const host = document.getElementById("toasts");
  if (!host) return;
  const node = el("div", { class: `sm-toast sm-toast--${kind}`, role: "status" }, String(message));
  host.append(node);
  if (timeout > 0) {
    setTimeout(() => {
      node.remove();
    }, timeout);
  }
}

export function banner({ kind = "info", title = null, message, actions = [] }) {
  const role = kind === "error" ? "alert" : "status";
  const node = el("div", { class: `sm-banner sm-banner--${kind}`, role });
  if (title) node.append(el("strong", { text: title }));
  if (message) node.append(el("p", { text: message }));
  if (actions.length) {
    const row = el("div", { class: "sm-banner__actions" });
    for (const action of actions) {
      row.append(action);
    }
    node.append(row);
  }
  return node;
}

export function confirmDialog({ title, body, confirmLabel = "Delete", cancelLabel = "Cancel" }) {
  return new Promise((resolve) => {
    const dialog = el("dialog", { class: "sm-dialog" });
    const cancel = el(
      "button",
      { type: "button", class: "sm-button sm-button--secondary" },
      cancelLabel,
    );
    const confirm = el("button", { type: "button", class: "sm-button sm-button--danger" }, confirmLabel);

    let settled = false;
    const close = (value) => {
      if (settled) return;
      settled = true;
      resolve(value);
      dialog.close();
      dialog.remove();
    };

    cancel.addEventListener("click", () => close(false));
    confirm.addEventListener("click", () => close(true));
    dialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      close(false);
    });
    // A click on the backdrop lands on the dialog element itself.
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) close(false);
    });

    dialog.append(
      el("h2", { class: "sm-dialog__title", text: title }),
      el("p", { class: "sm-dialog__body", text: body }),
      el("div", { class: "sm-dialog__actions" }, cancel, confirm),
    );
    document.body.append(dialog);
    dialog.showModal();
    confirm.focus();
  });
}

export function focusHeading(selector) {
  const node = document.querySelector(selector);
  if (!node) return;
  if (!node.hasAttribute("tabindex")) node.setAttribute("tabindex", "-1");
  node.focus({ preventScroll: true });
}

export function scrollToTop() {
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
}

export function skeleton(lines = 3) {
  const stack = el("div", { class: "sm-skeleton-stack", "aria-hidden": "true" });
  for (let index = 0; index < lines; index += 1) {
    stack.append(el("div", { class: "sm-skeleton" }));
  }
  return stack;
}

export function setButtonLoading(button, loading, loadingLabel = "Working…") {
  if (!button) return;
  if (loading) {
    button.dataset.label = button.textContent;
    button.textContent = loadingLabel;
    button.classList.add("is-loading");
    button.setAttribute("aria-busy", "true");
    button.disabled = true;
  } else {
    if (button.dataset.label) button.textContent = button.dataset.label;
    button.classList.remove("is-loading");
    button.removeAttribute("aria-busy");
    button.disabled = false;
  }
}
