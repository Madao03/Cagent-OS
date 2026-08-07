/**
 * shell.js — shared sidebar navigation + UI normalization for all pages.
 *
 * Loaded by chat.html / brief.html / knowledge.html via <script src>.
 * Responsibilities:
 *   1. Wire sidebar nav items to real navigation (chat → "/", etc.)
 *   2. Mark WIP features in the sidebar (每日简报 / 知识库 suffix)
 *   3. Normalize top-right "Model: ..." tag to match actual backend
 *
 * Safe to include multiple times (idempotent).
 */

(function () {
  "use strict";

  // Which features are still mock UI — get "(建设中)" suffix in sidebar
  const WIP_PAGES = ["每日简报", "知识库"];
  // The actual model used by the backend (matches what chat.js sets)
  const MODEL_DISPLAY = "DeepSeek V4 Pro";

  // ── Sidebar nav definition — single source of truth ──
  // Rendered by shell.js on every page. Never duplicate in HTML.
  const NAV_ITEMS = [
    { key: "chat", label: "对话面板", icon: "chat", disabled: false, page: "/" },
    { key: "brief", label: "每日简报", icon: "calendar", disabled: true, page: "/brief" },
    { key: "dashboard", label: "定制化看板", icon: "monitor", disabled: true, page: null },
    { key: "opinions", label: "观点库", icon: "brain", disabled: true, page: null },
    { key: "knowledge", label: "共享知识库", icon: "doc", disabled: false, page: "/knowledge" },
    { key: "roadmap", label: "开发路线图", icon: "design-flow", disabled: false, page: "/roadmap" },
    { key: "feedback", label: "反馈中心", icon: "ai_bulb", disabled: true, page: null },
    { key: "about", label: "关于", icon: "info", disabled: false, page: "/about" },
  ];

  function _currentPage() {
    const p = window.location.pathname;
    if (p.includes("about.html") || p.includes("/about")) return "about";
    if (p.includes("knowledge.html") || p.includes("/knowledge")) return "knowledge";
    if (p.includes("brief.html") || p.includes("/brief")) return "brief";
    if (p.includes("roadmap.html") || p.includes("/roadmap")) return "roadmap";
    return "chat";
  }

  function _renderSidebarNav(navEl) {
    const current = _currentPage();
    let html = "";
    for (const item of NAV_ITEMS) {
      const active = item.key === current ? " active" : "";
      const disabled = item.disabled ? " disabled" : "";
      const sup = item.disabled ? '<sup class="sidebar-nav-tag">建设中</sup>' : "";
      const style = item.disabled ? ' style="opacity:0.6;cursor:default;"' : "";
      html += `<a class="sidebar-nav-item${active}${disabled}" data-dom-id="nav-${item.key}" data-nav-key="${item.key}" href="#"${style} title="${item.disabled ? "建设中" : ""}">` +
        `<span data-icon="${item.icon}" class="sidebar-nav-icon" aria-hidden="true"></span>` +
        `<span class="sidebar-nav-label">${item.label}${sup}</span>` +
        `</a>`;
    }
    navEl.innerHTML = html;
  }

  function applySidebarLabels() {
    const navEl = document.querySelector(".app-sidebar-nav");
    if (navEl) _renderSidebarNav(navEl);
    // ★ Ensure logo is consistent across all pages
    _ensureLogo();
  }

  function _ensureLogo() {
    const logoDiv = document.querySelector(".app-sidebar-logo");
    if (!logoDiv) return;
    // If logo already has content, skip
    if (logoDiv.querySelector(".logo-title")) return;
    // Inject logo HTML
    logoDiv.innerHTML =
      '<span class="sidebar-logo-icon" aria-hidden="true"><span style="display:inline-block;width:28px;height:28px;border-radius:6px;background:linear-gradient(135deg,#4B3FE3,#6A6FFF);text-align:center;line-height:28px;color:#fff;font-weight:700;font-size:14px;font-family:var(--font-family-mono,monospace)">C</span></span>' +
      '<span class="app-sidebar-logo-text">' +
        '<span class="logo-title">CagentOS</span>' +
        '<span class="logo-subtitle">投研工作台</span>' +
      '</span>';
  }

  function normalizeModelTag() {
    document.querySelectorAll(".ds-tag.ds-tag-primary").forEach((tag) => {
      const t = (tag.textContent || "").toLowerCase();
      if (t.startsWith("model:")) {
        tag.textContent = `Model: ${MODEL_DISPLAY}`;
      }
    });
    // Also sync the input bar's model selector on chat page
    const modelSel = document.querySelector(".chat-model-selector");
    if (modelSel) modelSel.textContent = MODEL_DISPLAY;
  }

  function wireSidebar() {
    // Inject collapse button if missing (some pages don't have it in HTML)
    const logoDiv = document.querySelector(".app-sidebar-logo");
    if (logoDiv && !document.querySelector(".sidebar-collapse-btn")) {
      const btn = document.createElement("button");
      btn.className = "sidebar-collapse-btn";
      btn.setAttribute("aria-label", "收起侧边栏");
      btn.title = "收起侧边栏";
      btn.innerHTML = '<span data-icon="arrow-collapse" class="sidebar-collapse-icon" aria-hidden="true"></span>';
      logoDiv.appendChild(btn);
    }

    const collapseBtn = document.querySelector(".sidebar-collapse-btn");
    if (collapseBtn && !collapseBtn.dataset.wired) {
      collapseBtn.dataset.wired = "1";
      collapseBtn.addEventListener("click", () => {
        const sidebar = document.querySelector(".app-sidebar");
        const shell = document.querySelector(".app-shell");
        if (!sidebar || !shell) return;
        const isCollapsed = sidebar.classList.toggle("collapsed");
        shell.classList.toggle("sidebar-collapsed", isCollapsed);
        collapseBtn.setAttribute("aria-label", isCollapsed ? "展开侧边栏" : "收起侧边栏");
        collapseBtn.title = isCollapsed ? "展开侧边栏" : "收起侧边栏";
        try { localStorage.setItem("cagentos-sidebar-collapsed", isCollapsed ? "1" : "0"); } catch(e) {}
      });
    }
    // Restore previous state
    try {
      if (localStorage.getItem("cagentos-sidebar-collapsed") === "1") {
        const sidebar = document.querySelector(".app-sidebar");
        const shell = document.querySelector(".app-shell");
        const btn = document.querySelector(".sidebar-collapse-btn");
        if (sidebar && shell) {
          sidebar.classList.add("collapsed");
          shell.classList.add("sidebar-collapsed");
          if (btn) { btn.setAttribute("aria-label", "展开侧边栏"); btn.title = "展开侧边栏"; }
        }
      }
    } catch(e) {}
  }

  // Wire nav clicks AFTER render (items are injected by _renderSidebarNav)
  function wireNavClicks() {
    document.querySelectorAll(".sidebar-nav-item").forEach((item) => {
      const key = item.getAttribute("data-nav-key");
      if (!key) return;
      item.addEventListener("click", (e) => {
        e.preventDefault();
        if (item.classList.contains("disabled")) return;
        if (key === "chat") window.location.href = "/";
        else if (key === "brief") window.location.href = "/brief";
        else if (key === "knowledge") window.location.href = "/knowledge";
        else if (key === "about") { try { sessionStorage.removeItem("cagentos_from_welcome"); } catch(e) {} window.location.href = "/about"; }
      });
    });
  }

  function boot() {
    applySidebarLabels();
    normalizeModelTag();
    wireSidebar();
    wireNavClicks();
    // Debug: verify active state
    setTimeout(() => {
      const items = document.querySelectorAll(".sidebar-nav-item");
      const page = _currentPage();
      console.log("[shell.js] page=" + page + ", nav items:", items.length);
      items.forEach(el => console.log("[shell.js]", el.getAttribute("data-nav-key"), "active=" + el.classList.contains("active"), "classes=" + el.className));
    }, 0);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
