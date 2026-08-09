"use strict";

const TOKEN = document.querySelector('meta[name="dfpm-token"]').content;
const $ = (selector) => document.querySelector(selector);

let state = null;
let busy = false;

/* ---------- tiny DOM helper: every value is set as text, never as markup ---------- */

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.title) node.title = options.title;
  if (options.type) node.type = options.type;
  if (options.disabled) node.disabled = true;
  if (options.onClick) node.addEventListener("click", options.onClick);
  for (const child of children) if (child) node.append(child);
  return node;
}

function button(text, className, onClick, options = {}) {
  return el("button", { className: `pixel-button ${className}`.trim(), type: "button", text, onClick, ...options });
}

function fact(label, value) {
  const shown = value === null || value === undefined || value === "" ? "—" : String(value);
  return el("div", {}, [el("small", { text: label }), el("strong", { text: shown })]);
}

function chip(text, tone) {
  return el("span", { className: tone || "", text });
}

function badge(name, tone) {
  return el("div", { className: `tool-badge ${tone}`, text: (name[0] || "?").toUpperCase() });
}

/* ---------- server ---------- */

async function call(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined
      ? { "x-dfpm-token": TOKEN }
      : { "x-dfpm-token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({ error: "The server sent a response that could not be read." }));
  if (!response.ok) throw new Error(payload.error || `Request failed with status ${response.status}`);
  return payload;
}

async function refresh() {
  try {
    state = await call("/api/state");
    setStatus(true, "Connected", "Local interface");
    render();
  } catch (error) {
    setStatus(false, "Disconnected", "Is dfpm still running?");
    toast(error.message, true);
  }
}

function setStatus(ok, text, detail) {
  $("#status-light").classList.toggle("bad", !ok);
  $("#status-text").textContent = text;
  $("#status-detail").textContent = detail;
}

/* ---------- rendering ---------- */

function render() {
  renderInstalled();
  renderCatalog();
  renderHealth();
  renderLocations();
}

function failuresFor(packageId, version) {
  return state.findings.filter((item) => item.package === packageId && item.version === version && item.status === "failed");
}

function renderInstalled() {
  const container = $("#installed-list");
  container.replaceChildren();
  if (!state.packages.length) {
    container.append(el("div", { className: "empty-state", text: "Nothing is installed yet. Open the reviewed catalog to install a package." }));
    return;
  }

  for (const pack of state.packages) {
    const failures = failuresFor(pack.id, pack.version);
    const commands = pack.entrypoints || [];
    const summary = [
      commands.length ? `Runs as ${commands.join(" and ")}.` : null,
      `${pack.files ?? "?"} file${pack.files === 1 ? "" : "s"} installed ${(pack.installedAt || "").slice(0, 10)}.`,
    ].filter(Boolean).join(" ");

    container.append(
      el("article", { className: "tool-card" }, [
        el("header", {}, [
          badge(pack.name, "gold"),
          el("div", {}, [
            el("h3", { text: `${pack.name} ${pack.version || ""}`.trim() }),
            el("small", { text: `${pack.id} · ${pack.kind || "package"}` }),
          ]),
        ]),
        el("p", { text: summary }),
        el("div", { className: "tags" }, [
          failures.length ? chip(`${failures.length} problem${failures.length === 1 ? "" : "s"}`, "bad") : chip("Healthy", "ok"),
          pack.platform ? chip(`${pack.platform.os}/${pack.platform.arch}`) : null,
          pack.project && pack.project.license ? chip(pack.project.license) : null,
        ]),
        el("div", { className: "card-actions" }, [button("Uninstall", "danger", () => previewUninstall(pack))]),
      ])
    );
  }
}

function renderCatalog() {
  const container = $("#catalog-list");
  container.replaceChildren();

  if (state.catalogError) {
    container.append(el("div", { className: "empty-state", text: state.catalogError }));
    return;
  }
  if (!state.catalog.length) {
    container.append(el("div", { className: "empty-state", text: "The catalog directory holds no manifests." }));
    return;
  }

  const installed = new Map(state.packages.map((pack) => [pack.id, pack]));
  for (const entry of state.catalog) {
    const existing = installed.get(entry.id);
    const alreadyInstalled = Boolean(existing && existing.version === entry.version);
    const replaces = existing && existing.version !== entry.version ? existing.version : null;
    container.append(
      el("article", { className: "tool-card" }, [
        el("header", {}, [
          badge(entry.name, "navy"),
          el("div", {}, [
            el("h3", { text: `${entry.name} ${entry.version}` }),
            el("small", { text: `${entry.id} · ${entry.kind}` }),
          ]),
        ]),
        el("p", { text: entry.description }),
        el("div", { className: "tags" }, [
          alreadyInstalled ? chip("Installed", "ok") : null,
          replaces ? chip(`replaces ${replaces}`) : null,
          entry.platform ? chip(`${entry.platform.os}/${entry.platform.arch}`) : null,
          entry.project && entry.project.license ? chip(entry.project.license) : null,
        ]),
        el("div", { className: "card-actions" }, [
          alreadyInstalled
            ? button("Installed", "", null, { disabled: true, title: "This version is already installed" })
            : button(replaces ? "Update" : "Install", "primary", () => previewInstall(entry)),
        ]),
      ])
    );
  }
}

function renderHealth() {
  const container = $("#health-list");
  container.replaceChildren();
  if (!state.findings.length) {
    container.append(el("div", { className: "empty-state", text: "No managed packages to check." }));
    return;
  }
  const table = el("div", { className: "plain-table" }, [
    el("div", { className: "finding-row table-head" }, [
      el("span", { text: "RESULT" }),
      el("span", { text: "PACKAGE" }),
      el("span", { text: "DETAIL" }),
    ]),
  ]);
  for (const finding of state.findings) {
    const passing = finding.status === "passing";
    table.append(
      el("div", { className: "finding-row" }, [
        el("span", { className: `mark ${passing ? "ok" : "bad"}`, text: passing ? "PASS" : "FAIL" }),
        el("b", { text: `${finding.package} ${finding.version}` }),
        el("span", { text: finding.detail }),
      ])
    );
  }
  container.append(table);
}

function renderLocations() {
  const container = $("#locations-list");
  container.replaceChildren();
  const rows = [
    ["Tools and versions", "Program files owned and managed by dfpm", "tools"],
    ["Downloaded files", "Verified downloads kept so packages can be reinstalled offline", "cache"],
    ["Command shortcuts", "Small launchers pointing at the active version", "bin"],
    ["Package records", "What is installed, where it came from, and when", "state"],
    ["Reviewed catalog", "Manifests this interface can install from", "catalog"],
  ];
  for (const [title, description, key] of rows) {
    container.append(
      el("article", { className: "no-action" }, [
        el("div", {}, [el("h3", { text: title }), el("p", { text: description })]),
        el("code", { text: state.paths[key] }),
      ])
    );
  }
}

/* ---------- plans and confirmation ---------- */

async function previewInstall(entry) {
  try {
    const { plan } = await call("/api/install/plan", { package: entry.id, version: entry.version });
    const body = el("div", {}, [
      el("div", { className: "facts" }, [
        fact("Package", `${plan.name} ${plan.version}`),
        fact("Platform", plan.platform),
        fact("License", plan.license),
        fact("Download size", plan.size === null ? null : `${plan.size.toLocaleString()} bytes`),
      ]),
      el("div", { className: "facts" }, [fact("Source", plan.source), fact("SHA-256", plan.sha256)]),
      el("div", { className: "facts" }, [fact("Destination", plan.destination), fact("System-wide changes", "None")]),
      el("div", { className: "system-note" }, [
        el("b", { text: "What happens when you confirm" }),
        el("p", { text: "dfpm downloads this artifact, refuses it unless the digest matches exactly, extracts it only if the result fits the volume, checks the expected files are present, and only then installs it." }),
      ]),
    ]);
    openModal("Install plan", `Install ${plan.name} ${plan.version}?`, body, "Install", () =>
      run("/api/install", { package: entry.id, version: entry.version })
    );
  } catch (error) {
    toast(error.message, true);
  }
}

async function previewUninstall(pack) {
  try {
    const { plan } = await call("/api/uninstall/plan", { package: pack.id });
    const body = el("div", {}, [
      el("div", { className: "facts" }, [
        fact("Version", plan.version),
        fact("Removes", `${plan.files} file(s)`),
        fact("Commands removed", plan.commands.join(", ")),
        fact("Cache", "Kept, so it can be reinstalled offline"),
      ]),
      el("p", { className: "path", text: plan.root }),
      plan.grew
        ? el("div", { className: "system-note" }, [
            el("b", { text: "This folder holds more than the install put there" }),
            el("p", {
              text:
                `Installed with ${plan.installedFiles} file(s); ${plan.files} are there now. ` +
                "A tool that updates its own rules does this. Everything in the folder is removed.",
            }),
          ])
        : null,
      el("p", { text: "Downloads stay in the cache, so this package can be reinstalled without network access." }),
    ]);
    openModal("Removal plan", `Remove ${plan.name}?`, body, "Remove", () =>
      run("/api/uninstall", { package: pack.id })
    );
  } catch (error) {
    toast(error.message, true);
  }
}

let confirmAction = null;

function openModal(kicker, title, body, confirmLabel, action) {
  $("#modal-kicker").textContent = kicker;
  $("#modal-title").textContent = title;
  $("#modal-body").replaceChildren(body);
  $("#modal-confirm").textContent = confirmLabel;
  confirmAction = action;
  $("#modal-shade").classList.add("open");
}

function closeModal() {
  $("#modal-shade").classList.remove("open");
  confirmAction = null;
}

async function run(path, body) {
  if (busy) return;
  busy = true;
  const confirmButton = $("#modal-confirm");
  const previousLabel = confirmButton.textContent;
  confirmButton.disabled = true;
  confirmButton.textContent = "Working…";
  try {
    const result = await call(path, body);
    closeModal();
    toast(result.message || "Done.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    busy = false;
    confirmButton.disabled = false;
    confirmButton.textContent = previousLabel;
    await refresh();
  }
}

let toastTimer = null;

function toast(text, isError = false) {
  const node = $("#toast");
  $("#toast-mark").textContent = isError ? "!" : "✓";
  $("#toast-mark").style.color = isError ? "var(--danger)" : "var(--green)";
  $("#toast-text").textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), isError ? 8000 : 4000);
}

/* ---------- wiring ---------- */

document.querySelectorAll(".nav-link").forEach((link) => {
  link.addEventListener("click", () => {
    document.querySelectorAll(".nav-link").forEach((other) => other.classList.toggle("active", other === link));
    document.querySelectorAll(".page").forEach((page) => page.classList.toggle("active", page.id === `page-${link.dataset.page}`));
    window.scrollTo(0, 0);
  });
});

$("#refresh").addEventListener("click", refresh);
$("#modal-cancel").addEventListener("click", closeModal);
$("#modal-close").addEventListener("click", closeModal);
$("#modal-confirm").addEventListener("click", () => { if (confirmAction) confirmAction(); });
$("#modal-shade").addEventListener("click", (event) => { if (event.target === $("#modal-shade")) closeModal(); });
document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModal(); });

function applyAppearance(appearance) {
  document.documentElement.dataset.appearance = appearance;
  const dark = appearance === "dark";
  $("#theme-icon").textContent = dark ? "☀" : "☾";
  $("#theme-label").textContent = dark ? "Light mode" : "Dark mode";
  $('meta[name="theme-color"]').content = dark ? "#0d0d0d" : "#ffffff";
  localStorage.setItem("dfpm-appearance", appearance);
}

$("#theme-button").addEventListener("click", () => {
  applyAppearance(document.documentElement.dataset.appearance === "dark" ? "light" : "dark");
});

applyAppearance(localStorage.getItem("dfpm-appearance") || "light");
refresh();
