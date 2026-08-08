"use strict";

/* Landing site for dfpm. Everything shown here is real: the catalog mirrors
   catalog/*.json in the repository, and the commands mirror `dfpm --help`. */

const CATALOG = [
  {
    id: "yara",
    name: "YARA",
    version: "4.5.5",
    kind: "tool",
    letter: "Y",
    tone: "gold",
    plain: "Investigators write rules describing suspicious strings and byte patterns. YARA checks files or memory and reports what matches.",
    platform: "windows/x64",
    license: "BSD-3-Clause",
    project: "https://github.com/VirusTotal/yara",
    commands: ["yara", "yarac"],
  },
];

const COMMANDS = [
  ["dfpm paths", "Show where dfpm stores files."],
  ["dfpm catalog", "List available packages."],
  ["dfpm install <package>", "Install a package, replacing any version already installed."],
  ["dfpm uninstall <package>", "Remove installed files dfpm recorded."],
  ["dfpm cache", "Inspect and clean the verified download cache."],
  ["dfpm run <command>", "Run a command from an installed package."],
  ["dfpm which <command>", "Show which file a command runs."],
  ["dfpm gui", "Open a local interface for managing installed packages."],
  ["dfpm list", "List installed packages."],
  ["dfpm doctor", "Check managed files without changing them."],
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

function renderCatalog() {
  const container = $("#catalog-list");
  container.replaceChildren();
  for (const entry of CATALOG) {
    container.append(
      el("article", { className: "tool-card" }, [
        el("header", {}, [
          el("div", { className: `tool-badge ${entry.tone}`, text: entry.letter }),
          el("div", {}, [
            el("h3", { text: `${entry.name} ${entry.version}` }),
            el("small", { text: `${entry.id} · ${entry.kind} · ${entry.platform}` }),
          ]),
        ]),
        el("p", { text: entry.plain }),
        el("div", { className: "tags" }, [
          el("span", { text: entry.license }),
          ...entry.commands.map((command) => el("span", { text: command })),
        ]),
        el("footer", {}, [
          el("span", { text: "Digest pinned and verified" }),
          el("a", { text: "Project site →", href: entry.project }),
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
renderCatalog();
renderCommands();
wireCopyButtons();
loadAssets();
parallax();
