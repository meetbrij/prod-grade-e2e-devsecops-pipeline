// Review page for the KYC service.
// Security rule: extracted values come from untrusted documents. They are only ever put into
// the page with textContent / value, never as markup. A test fails if any markup-building API appears.
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const keyInput = $("api-key");
  keyInput.value = sessionStorage.getItem("kyc-api-key") || "";
  keyInput.addEventListener("input", () => sessionStorage.setItem("kyc-api-key", keyInput.value));

  const REASONS = {
    missing: "not found on the document",
    low_confidence: "low confidence",
    invalid_format: "unexpected format",
    implausible_date: "implausible date",
    inconsistent_dates: "dates contradict each other",
  };

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs || {})) {
      if (key === "text") node.textContent = value;
      else if (key === "class") node.className = value;
      else node.setAttribute(key, value);
    }
    for (const child of children) node.append(child);
    return node;
  }

  function authHeaders(extra) {
    const headers = Object.assign({}, extra || {});
    if (keyInput.value) headers["X-API-Key"] = keyInput.value;
    return headers;
  }

  function setStatus(message, isError) {
    const status = $("status");
    status.textContent = message || "";
    status.className = isError ? "error" : "";
  }

  async function api(path, options) {
    const response = await fetch(path, options);
    let body = null;
    try { body = await response.json(); } catch (_) { /* no JSON body */ }
    if (!response.ok) {
      const detail = body && body.detail;
      throw new Error(typeof detail === "string" ? detail : `request failed (${response.status})`);
    }
    return body;
  }

  function humanReason(reason) {
    return REASONS[reason] || reason || "needs review";
  }

  function confidenceCell(field) {
    const pct = Math.round(field.confidence * 100);
    const bar = el("div", { class: "bar" + (field.needs_review ? " low" : "") });
    const fill = el("span");
    fill.style.width = pct + "%";
    bar.append(fill);
    return el("td", {}, bar, el("span", { class: "hint", text: ` ${pct}%` }));
  }

  function fixControl(doc, field, onUpdated) {
    const input = el("input", { type: "text", "aria-label": `Corrected ${field.name}`, maxlength: "512" });
    input.value = field.value || "";
    const button = el("button", { type: "button", text: "Confirm" });
    button.addEventListener("click", async () => {
      button.disabled = true;
      try {
        const updated = await api(
          `/documents/${encodeURIComponent(doc.id)}/fields/${encodeURIComponent(field.name)}`,
          {
            method: "PATCH",
            headers: authHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ value: input.value }),
          },
        );
        setStatus("");
        onUpdated(updated);
      } catch (err) {
        setStatus(err.message, true);
        button.disabled = false;
      }
    });
    return el("div", { class: "fix" }, input, button);
  }

  function statusBadge(doc) {
    if (doc.status === "needs_review") return el("span", { class: "badge review", text: "needs review" });
    if (doc.status === "reviewed") return el("span", { class: "badge reviewed", text: "reviewed" });
    return el("span", { class: "badge ok", text: "all fields confident" });
  }

  function renderDocument(doc, onUpdated) {
    const head = el(
      "div",
      { class: "doc-head" },
      el("strong", { text: doc.document_type.replace("_", " ") }),
      statusBadge(doc),
      el("span", { class: "id", text: `${doc.id} · ${doc.model_id}` }),
    );
    const table = el(
      "table",
      {},
      el("thead", {}, el("tr", {},
        el("th", { text: "Field" }), el("th", { text: "Value" }),
        el("th", { text: "Confidence" }), el("th", { text: "Status" }))),
    );
    const body = el("tbody");
    for (const field of doc.fields) {
      const statusText = field.needs_review
        ? humanReason(field.reason)
        : field.reviewed ? "confirmed by reviewer" : "ok";
      const valueCell = el("td", { class: "value", text: field.value === null ? "—" : field.value });
      const row = el("tr", {}, el("td", { text: field.name.replace(/_/g, " ") }), valueCell,
        confidenceCell(field), el("td", { text: statusText }));
      body.append(row);
      if (field.needs_review) {
        const fixRow = el("tr", {}, el("td", { colspan: "4" }, fixControl(doc, field, onUpdated)));
        body.append(fixRow);
      }
    }
    table.append(body);
    return el("div", { class: "doc" }, head, table);
  }

  function showDocument(container, doc, refreshQueue) {
    const card = renderDocument(doc, (updated) => {
      showDocument(container, updated, refreshQueue);
      refreshQueue();
    });
    container.replaceChildren(card);
  }

  async function loadQueue() {
    const queue = $("queue");
    try {
      const docs = await api("/documents?needs_review=true", { headers: authHeaders() });
      setStatus("");
      if (docs.length === 0) {
        queue.replaceChildren(el("p", { class: "empty", text: "Nothing waiting for review." }));
        return;
      }
      queue.replaceChildren(...docs.map((doc) => {
        const holder = el("div");
        showDocument(holder, doc, loadQueue);
        return holder;
      }));
    } catch (err) {
      setStatus(err.message, true);
    }
  }

  $("upload-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const file = $("file").files[0];
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    form.append("document_type", $("document-type").value);
    const button = $("upload-button");
    button.disabled = true;
    setStatus("Extracting fields… this can take several seconds.");
    try {
      const doc = await api("/documents", { method: "POST", headers: authHeaders(), body: form });
      setStatus("");
      showDocument($("result"), doc, loadQueue);
      if (doc.needs_review) void loadQueue(); // loadQueue reports its own errors
    } catch (err) {
      $("result").replaceChildren();
      setStatus(err.message, true);
    } finally {
      button.disabled = false;
    }
  });

  $("load-queue").addEventListener("click", loadQueue);
})();
