(() => {
  "use strict";

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || "";

  async function fetchJSON(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && typeof options.body !== "string") {
      headers.set("Content-Type", "application/json");
      options.body = JSON.stringify(options.body);
    }
    if (options.method && options.method !== "GET") headers.set("X-CSRF-Token", csrf());
    const response = await fetch(url, {...options, headers});
    const contentType = response.headers.get("content-type") || "";
    const payload = contentType.includes("application/json") ? await response.json() : null;
    if (!response.ok) {
      const error = new Error(payload?.detail?.message || payload?.detail || `Błąd HTTP ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function icon(name, label = "") {
    const wrap = document.createElement("span");
    wrap.className = "icon-wrap";
    if (label) {
      wrap.setAttribute("role", "img");
      wrap.setAttribute("aria-label", label);
    } else {
      wrap.setAttribute("aria-hidden", "true");
    }
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "opos-icon");
    svg.setAttribute("viewBox", "0 0 24 24");
    const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
    use.setAttribute("href", `/static/icons/opos.svg#icon-${name}`);
    svg.append(use);
    wrap.append(svg);
    return wrap;
  }

  function toast(message) {
    const region = document.getElementById("toast-region");
    if (!region) return;
    const node = document.createElement("div");
    node.className = "toast";
    node.textContent = message;
    region.append(node);
    window.setTimeout(() => node.remove(), 3200);
  }

  document.addEventListener("submit", (event) => {
    const message = event.target?.dataset?.confirm;
    if (message && !window.confirm(message)) event.preventDefault();
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest(".js-delete-template");
    if (!button) return;
    if (!window.confirm("Usunąć ten szablon? Kopie w rozpiskach pozostaną bez zmian.")) return;
    button.disabled = true;
    try {
      await fetchJSON(`/armies/${button.dataset.armyId}/templates/${button.dataset.templateId}`, {method: "DELETE"});
      button.closest(".template-card")?.remove();
      toast("Szablon usunięty.");
    } catch (error) {
      button.disabled = false;
      toast(error.message);
    }
  });

  window.OPOS = {csrf, fetchJSON, icon, toast};
})();
