"use strict";

/* Landing site for dfpm. Everything shown here is real: the catalog is read
   from catalog.json, which is what `dfpm catalog --json` prints for the
   manifests in this repository, and the commands mirror `dfpm --help`.

   The feed is fetched rather than written out here so this page and the local
   interface describe a package the same way. A copy kept by hand is a copy
   that goes stale the first time a manifest changes. */

const CATALOG_FEED = "catalog.json";

const state = { packages: [], vocabulary: null, discipline: null, error: null };

const COMMANDS = [
  ["dfpm paths", "Show where dfpm stores files."],
  ["dfpm catalog", "List available packages."],
  ["dfpm install <package>", "Install a package, replacing any version already installed."],
  ["dfpm download <package>", "Download a package's release file without installing it."],
  ["dfpm uninstall <package>", "Remove installed files dfpm recorded."],
  ["dfpm cache", "Inspect and clean the verified download cache."],
  ["dfpm run <command>", "Run a command from an installed package."],
  ["dfpm which <command>", "Show which file a command runs."],
  ["dfpm gui", "Open a local interface for managing installed packages."],
  ["dfpm list", "List installed packages."],
  ["dfpm doctor", "Check installed packages without changing them."],
];

const $ = (selector) => document.querySelector(selector);

function el(tag, options = {}, children = []) {
  const node = document.createElement(tag);
  if (options.className) node.className = options.className;
  if (options.text !== undefined) node.textContent = options.text;
  if (options.href) { node.href = options.href; node.target = "_blank"; node.rel = "noopener noreferrer"; }
  if (options.onClick) node.addEventListener("click", options.onClick);
  for (const child of children) if (child) node.append(child);
  return node;
}

/* ---------- content ---------- */

function chip(text, tone) {
  return el("span", { className: tone || "", text });
}

function badge(name, tone) {
  return el("div", { className: `tool-badge ${tone}`, text: (name[0] || "?").toUpperCase() });
}

/* Tones are decoration and belong to the page, not to the catalog. Picking one
   from the name keeps a tool the same colour between visits without a manifest
   having to carry a field about how a website looks. */
const TONES = ["navy", "gold", "silver"];

/* Somebody reading the catalog has not chosen anything yet, so the entry should
   answer as much as it can. The three axes that are not the browsing one read
   better as labelled lists than as another dozen chips. */
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

function tone(entry) {
  let total = 0;
  for (const character of entry.id) total = (total + character.codePointAt(0)) % 1024;
  return TONES[total % TONES.length];
}

function renderCatalogCount() {
  // Counted from the feed rather than written into the page, so adding a
  // manifest does not leave a number behind that quietly stops being true.
  const total = state.packages.length;
  $("#catalog-count").textContent = state.error
    ? "Catalog unavailable"
    : `${total} package${total === 1 ? "" : "s"} available`;
}

async function loadCatalog() {
  try {
    const response = await fetch(CATALOG_FEED, { cache: "no-cache" });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const feed = await response.json();
    state.packages = feed.packages || [];
    state.vocabulary = feed.vocabulary || null;
  } catch (error) {
    // Opening the file straight from disk trips this, because a browser will
    // not fetch alongside a file:// page. Say what to do rather than leaving
    // an empty panel that looks like an empty catalog.
    state.error = `The catalog could not be loaded (${error.message}). This page reads ${CATALOG_FEED} and needs to be served over HTTP.`;
  }
  renderCatalog();
}

function renderDisciplines() {
  const bar = $("#catalog-filters");
  bar.replaceChildren();
  const terms = (state.vocabulary && state.vocabulary.disciplines) || [];
  if (!terms.length) return;

  const counts = new Map();
  for (const entry of state.packages)
    for (const item of entry.disciplines || []) counts.set(item.key, (counts.get(item.key) || 0) + 1);

  // Every discipline is offered, including the ones nothing is catalogued
  // under. Somebody who cannot yet name a tool is reading this to find out
  // what the field contains, and an empty discipline is an answer rather
  // than a gap.
  bar.append(filterButton(null, "All", state.packages.length));
  for (const term of terms) bar.append(filterButton(term.key, term.label, counts.get(term.key) || 0));
}

function filterButton(key, label, count) {
  const node = el("button", {
    className: state.discipline === key ? "active" : "",
    text: `${label} (${count})`,
    onClick: () => { state.discipline = key; renderCatalog(); },
  });
  node.type = "button";
  if (count === 0) {
    node.disabled = true;
    node.title = "Nothing in the catalog covers this discipline yet";
  }
  return node;
}

function renderCatalog() {
  renderCatalogCount();
  renderDisciplines();
  const container = $("#catalog-list");
  container.replaceChildren();

  if (state.error) {
    container.append(el("div", { className: "empty-state", text: state.error }));
    return;
  }
  if (!state.packages.length) {
    container.append(el("div", { className: "empty-state", text: "The catalog holds no packages yet." }));
    return;
  }

  const showing = state.discipline
    ? state.packages.filter((entry) => (entry.disciplines || []).some((item) => item.key === state.discipline))
    : state.packages;
  if (!showing.length) {
    container.append(el("div", { className: "empty-state", text: "No package in the catalog covers that discipline." }));
    return;
  }

  for (const entry of showing) {
    const project = entry.project || {};
    const platforms = (entry.platforms || []).map((item) => `${item.os}/${item.arch}`);
    const disciplines = entry.disciplines || [];
    container.append(
      el("article", { className: "tool-card" }, [
        el("header", {}, [
          badge(entry.name, tone(entry)),
          el("div", {}, [
            el("h3", { text: `${entry.name} ${entry.version}` }),
            el("small", { text: `${entry.id} · ${entry.kind}` }),
          ]),
        ]),
        el("p", { text: entry.about || entry.description }),
        el("div", { className: "tags" }, [
          ...disciplines.map((item) => chip(item.label, "accent")),
          ...platforms.map((item) => chip(item)),
          project.license ? chip(project.license) : null,
          ...(entry.commands || []).map((command) => chip(command)),
        ]),
        metaRows(entry),
        el("footer", {}, [
          el("span", { text: platforms.length > 1 ? `${platforms.length} builds, each digest pinned` : "Digest pinned and verified" }),
          project.repository ? el("a", { text: "Project site →", href: project.repository }) : null,
        ]),
      ])
    );
  }
}

function renderCommands() {
  const table = $("#command-table");
  table.replaceChildren(
    el("div", { className: "command-row table-head" }, [el("span", { text: "COMMAND" }), el("span", { text: "WHAT IT DOES" })])
  );
  for (const [command, description] of COMMANDS) {
    table.append(el("div", { className: "command-row" }, [el("code", { text: command }), el("span", { text: description })]));
  }
}

/* ---------- pixel assets, which are optional until they exist ---------- */

function loadAssets() {
  for (const slot of document.querySelectorAll("[data-asset]")) {
    const source = slot.dataset.asset;
    const probe = new Image();
    probe.onload = () => {
      slot.style.backgroundImage = `url("${source}")`;
      slot.classList.add("has-asset");
    };
    probe.onerror = () => slot.classList.add("asset-pending");
    probe.src = source;
  }
}

function parallax() {
  const layers = [...document.querySelectorAll(".hero-parallax .layer")];
  if (!layers.length || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let ticking = false;
  const apply = () => {
    const offset = window.scrollY;
    for (const layer of layers) layer.style.transform = `translate3d(0, ${offset * Number(layer.dataset.speed)}px, 0)`;
    ticking = false;
  };
  window.addEventListener("scroll", () => {
    if (!ticking) { ticking = true; window.requestAnimationFrame(apply); }
  }, { passive: true });
}

/* ---------- navigation, copying, theme ---------- */

function navigate(page) {
  document.querySelectorAll(".page").forEach((section) => section.classList.toggle("active", section.id === `${page}-page`));
  document.querySelectorAll(".nav-link").forEach((link) => link.classList.toggle("active", link.dataset.page === page));
  window.scrollTo(0, 0);
}

let toastTimer = null;

function toast(text) {
  const node = $("#toast");
  node.querySelector("p").textContent = text;
  node.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove("show"), 2400);
}

function wireCopyButtons() {
  for (const block of document.querySelectorAll("pre[data-copy]")) {
    const button = el("button", {
      className: "copy-button",
      text: "Copy",
      onClick: async () => {
        try {
          await navigator.clipboard.writeText(block.firstChild.textContent.trim());
          toast("Copied to your clipboard");
        } catch {
          toast("Your browser blocked clipboard access");
        }
      },
    });
    button.type = "button";
    block.append(button);
  }
}

function applyAppearance(appearance) {
  document.documentElement.dataset.appearance = appearance;
  const dark = appearance === "dark";
  $("#theme-icon").textContent = dark ? "☀" : "☾";
  $("#theme-label").textContent = dark ? "Light mode" : "Dark mode";
  $('meta[name="theme-color"]').content = dark ? "#0d0d0d" : "#ffffff";
  localStorage.setItem("dfpm-appearance", appearance);
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-page]");
  if (!target) return;
  event.preventDefault();
  navigate(target.dataset.page);
});

$("#theme-button").addEventListener("click", () => {
  applyAppearance(document.documentElement.dataset.appearance === "dark" ? "light" : "dark");
});

applyAppearance(localStorage.getItem("dfpm-appearance") || "light");
loadCatalog();
renderCommands();
wireCopyButtons();
loadAssets();
parallax();
