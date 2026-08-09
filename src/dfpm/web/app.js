"use strict";

const TOKEN = document.querySelector('meta[name="dfpm-token"]').content;
const $ = (selector) => document.querySelector(selector);

let state = null;
let busy = false;
/* Which discipline the catalog is filtered to, or null for all of them. It is
   kept out of `state` because that is replaced wholesale on every refresh, and
   a refresh should not throw away what somebody was looking at. */
let discipline = null;

/* ---------- tiny DOM helper: every value is set as text, never as markup ---------- */

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.title) node.title = options.title;
  if (options.type) node.type = options.type;
  if (options.src) node.src = options.src;
  if (options.alt !== undefined) node.alt = options.alt;
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

/* An empty panel reads as something being broken. Saying nothing is wrong,
   in the same voice the rest of dfpm uses, is the whole job here. */
function emptyState(text, illustrated = true) {
  const node = el("div", { className: "empty-state" }, [
    illustrated ? el("img", { className: "empty-mascot", src: "brix-sleeping.png", alt: "" }) : null,
    el("p", { text }),
  ]);
  return node;
}

/* The three classification axes that are not the browsing one, as labelled
   lists. A dozen more chips would be noise; under a heading saying what the
   list is, the same terms answer a question. */
const META_ROWS = [
  ["capabilities", "Does"],
  ["evidence", "Reads"],
  ["use_cases", "Used for"],
];

function metaRows(entry) {
  const rows = [];
  for (const [field, label] of META_ROWS) {
    const terms = entry[field] || [];
    if (!terms.length) continue;
    rows.push(el("dt", { text: label }), el("dd", { text: terms.map((item) => item.label).join(" · ") }));
  }
  return rows.length ? el("dl", { className: "meta-rows" }, rows) : null;
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

function findingsFor(packageId, version) {
  return state.findings.filter(
    (item) => item.package === packageId && item.version === version && item.status !== "passing"
  );
}

/* One matcher for both lists. A package matches on the obvious things, and
   also on the aliases the vocabulary carries, so "evtx" reaches a tool
   classified against Windows event logs without anybody having typed that. */
function matching(entries, query) {
  const wanted = (query || "").trim().toLowerCase();
  if (!wanted) return entries;
  return entries.filter((entry) => searchText(entry).includes(wanted));
}

function searchText(entry) {
  if (entry._searchText === undefined) {
    const parts = [entry.id, entry.name, entry.kind, entry.description, entry.about];
    // Every classification axis the vocabulary defines, rather than a list
    // written out here. Which axes exist is the vocabulary's business, and a
    // new one should become searchable by being added there and nowhere else.
    for (const field of Object.keys(state.vocabulary || {})) {
      for (const item of entry[field] || []) parts.push(item.label, ...aliasesFor(field, item.key));
    }
    for (const platform of entry.platforms || []) parts.push(`${platform.os}/${platform.arch}`);
    if (entry.platform) parts.push(`${entry.platform.os}/${entry.platform.arch}`);
    for (const command of entry.commands || entry.entrypoints || []) parts.push(command);
    if (entry.project && entry.project.license) parts.push(entry.project.license);
    entry._searchText = parts.filter(Boolean).join(" ").toLowerCase();
  }
  return entry._searchText;
}

function aliasesFor(field, key) {
  const terms = (state && state.vocabulary && state.vocabulary[field]) || [];
  const term = terms.find((item) => item.key === key);
  return term && term.aliases ? term.aliases : [];
}

function installedDate(value) {
  // Written out rather than left as an ISO timestamp, and built explicitly so
  // it reads the same wherever the interface is opened.
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const when = new Date(value);
  if (!value || Number.isNaN(when.getTime())) return null;
  return `${when.getDate()} ${months[when.getMonth()]} ${when.getFullYear()}`;
}

/* dfpm never touches PATH, so "what do I actually type" is the question an
   installed tool raises most often. It gets the prominent spot, and a copy
   button, rather than being described in prose. */
function runBlock(commands) {
  if (!commands.length) return null;
  const text = commands.map((name) => `dfpm run ${name}`).join("\n");
  return el("div", { className: "run-row" }, [
    el("code", { className: "run-command", text }),
    el("button", {
      className: "copy-button",
      type: "button",
      text: "Copy",
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(text);
          toast(commands.length > 1 ? "Commands copied" : "Command copied");
        } catch {
          toast("Your browser blocked clipboard access", true);
        }
      },
    }),
  ]);
}

function renderInstalled() {
  const container = $("#installed-list");
  container.replaceChildren();
  const showing = matching(state.packages, $("#installed-search").value);
  if (!state.packages.length) {
    container.append(emptyState("Nothing is installed yet. Open the catalog to install one."));
    return;
  }
  if (!showing.length) {
    container.append(emptyState("Nothing installed matches that.", false));
    return;
  }

  for (const pack of showing) {
    const problems = findingsFor(pack.id, pack.version);
    const facts = [
      installedDate(pack.installedAt) ? `Installed ${installedDate(pack.installedAt)}` : null,
      pack.installedSize,
      pack.location,
    ].filter(Boolean).join(" · ");

    container.append(
      el("article", { className: "tool-card" }, [
        el("header", {}, [
          badge(pack.name, "gold"),
          el("div", {}, [
            el("h3", { text: `${pack.name} ${pack.version || ""}`.trim() }),
            el("small", { text: `${pack.id} · ${pack.kind || "package"}` }),
          ]),
        ]),
        pack.description ? el("p", { text: pack.description }) : null,
        runBlock(pack.entrypoints || []),
        el("div", { className: "tags" }, [
          healthChip(problems),
          // What is installed does not change; what the catalog offers does.
          // Saying so here is the whole reason the two are kept apart.
          pack.updateAvailable ? chip(`${pack.updateAvailable} available`, "accent") : null,
          pack.platform ? chip(`${pack.platform.os}/${pack.platform.arch}`) : null,
          pack.project && pack.project.license ? chip(pack.project.license) : null,
        ]),
        facts ? el("p", { className: "install-facts", text: facts }) : null,
        el("div", { className: "card-actions" }, [button("Uninstall", "danger", () => previewUninstall(pack))]),
      ])
    );
  }
}

/* A package whose runtime is missing is installed and cannot run, which is
   neither healthy nor broken. Reporting it as healthy would be a lie told at
   exactly the moment somebody is trying to find out why nothing happens. */
function healthChip(problems) {
  const failed = problems.filter((item) => item.status === "failed").length;
  const blocked = problems.filter((item) => item.status === "blocked").length;
  const unverified = problems.filter((item) => item.status === "unverified").length;
  if (failed) return chip(`${failed} problem${failed === 1 ? "" : "s"}`, "bad");
  if (blocked) return chip("Needs a runtime", "warn");
  if (unverified) return chip("Unverified artifact", "warn");
  return chip("Healthy", "ok");
}

function renderDisciplines() {
  const bar = $("#catalog-filters");
  bar.replaceChildren();
  const terms = (state.vocabulary && state.vocabulary.disciplines) || [];
  if (!terms.length) return;

  const counts = new Map();
  for (const entry of state.catalog)
    for (const item of entry.disciplines || []) counts.set(item.key, (counts.get(item.key) || 0) + 1);

  // Every discipline is offered, including the ones nothing is catalogued
  // under. Somebody new to the field is reading this to find out what the
  // field contains, and an empty one is an answer rather than a gap.
  bar.append(filterButton(null, "All", state.catalog.length));
  for (const term of terms) bar.append(filterButton(term.key, term.label, counts.get(term.key) || 0));
}

function filterButton(key, label, count) {
  const node = el("button", {
    className: discipline === key ? "active" : "",
    text: `${label} (${count})`,
    onClick: () => { discipline = key; renderCatalog(); },
  });
  node.type = "button";
  if (count === 0) {
    node.disabled = true;
    node.title = "Nothing in the catalog covers this discipline yet";
  }
  return node;
}

function renderCatalog() {
  renderDisciplines();
  const container = $("#catalog-list");
  container.replaceChildren();

  if (state.catalogError) {
    container.append(emptyState(state.catalogError, false));
    return;
  }
  if (!state.catalog.length) {
    container.append(emptyState("The catalog directory holds no manifests."));
    return;
  }

  const chosen = discipline
    ? state.catalog.filter((entry) => (entry.disciplines || []).some((item) => item.key === discipline))
    : state.catalog;
  const showing = matching(chosen, $("#catalog-search").value);
  if (!showing.length) {
    container.append(emptyState("Nothing in the catalog matches that.", false));
    return;
  }

  const installed = new Map(state.packages.map((pack) => [pack.id, pack]));
  for (const entry of showing) {
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
        // The catalog is where a package is still being decided on, so it says
        // as much as it knows. What is already installed is shown differently,
        // because the question there is how it is doing, not what it is.
        el("p", { text: entry.about || entry.description }),
        el("div", { className: "tags" }, [
          alreadyInstalled ? chip("Installed", "ok") : null,
          replaces ? chip(`replaces ${replaces}`) : null,
          ...(entry.disciplines || []).map((item) => chip(item.label, "accent")),
          ...(entry.platforms || []).map((item) => chip(`${item.os}/${item.arch}`)),
          entry.project && entry.project.license ? chip(entry.project.license) : null,
          ...(entry.commands || []).map((command) => chip(command)),
        ]),
        metaRows(entry),
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
    container.append(emptyState("Nothing is installed, so there is nothing to check."));
    return;
  }
  const table = el("div", { className: "plain-table" }, [
    el("div", { className: "finding-row table-head" }, [
      el("span", { text: "RESULT" }),
      el("span", { text: "PACKAGE" }),
      el("span", { text: "DETAIL" }),
    ]),
  ]);
  const marks = {
    passing: ["ok", "PASS"],
    blocked: ["warn", "WAIT"],
    unverified: ["warn", "WARN"],
    failed: ["bad", "FAIL"],
  };
  for (const finding of state.findings) {
    const [tone, label] = marks[finding.status] || marks.failed;
    table.append(
      el("div", { className: "finding-row" }, [
        el("span", { className: `mark ${tone}`, text: label }),
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
    ["Catalog", "The entries this interface can install from", "catalog"],
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
      plan.replaces
        ? el("div", { className: "system-note" }, [
            el("b", { text: `Version ${plan.replaces.version} is deleted once this one is working` }),
            el("p", {
              text:
                `Its folder — ${plan.replaces.root} — holds ${plan.replaces.files} file(s) and goes entirely. ` +
                (plan.replaces.grew
                  ? `It was installed with ${plan.replaces.installedFiles}, so anything the tool downloaded since goes too.`
                  : ""),
            }),
          ])
        : null,
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
$("#catalog-search").addEventListener("input", () => renderCatalog());
$("#installed-search").addEventListener("input", () => renderInstalled());
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
