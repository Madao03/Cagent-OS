/**
 * knowledge.js — Phase 4c wiring for the knowledge base page.
 *
 * Wires the search box + button to GET /api/v1/rag/search, clears the
 * baked-in mock article, and renders live RAG results in its place.
 *
 * Also polls /api/v1/rag/status on boot to show real chunk count and
 * embedding model in the header strip.
 */

(function () {
  "use strict";

  const API_BASE = "";

  // ─── DOM helpers ─────────────────────────────────────────────
  function el(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  // ─── Status: chunk count + model info ────────────────────────
  async function loadStatus() {
    const target = document.getElementById("kb-rag-status");
    if (!target) return;
    try {
      const resp = await Auth.fetch(`${API_BASE}/api/v1/rag/status`);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const data = await resp.json();
      if (!data.available) {
        target.textContent = `RAG 不可用 — ${data.reason || "请检查 API key 和 data/vectors/"}`;
        return;
      }
      target.textContent = `RAG · ${data.chunks} chunks · embedding: ${data.embedding_model} · dims: ${data.dimensions}`;
    } catch (err) {
      target.textContent = `RAG 状态获取失败: ${err}`;
    }
  }

  // ─── Triage ledger: load real entries + wire A/B/C filter tabs ──

  let _allTriageEntries = [];  // cache for filter
  let _activeLevel = "ALL";    // current filter: ALL | A | B | C | L1 | L2 | L3

  function getTriageListContainer() {
    return document.getElementById("kb-triage-list");
  }

  function getLevelTabs() {
    const tabBar = document.getElementById("kb-triage-tabs");
    return tabBar ? Array.from(tabBar.children) : [];
  }

  function getTriageCountElement() {
    return document.getElementById("kb-triage-count");
  }

  /**
   * Normalize raw level (L1/L2/L3/A/B/C/star count) → canonical A/B/C.
   * Used for the A/B/C filter tabs. L3 / 3 stars → A, L2 / 2 stars → B, L1 → C.
   */
  function canonicalLevel(rawLevel) {
    if (!rawLevel) return "?";
    // L1/L2/L3 mapping
    if (rawLevel === "L3") return "A";
    if (rawLevel === "L2") return "B";
    if (rawLevel === "L1") return "C";
    // Already A/B/C
    if (["A", "B", "C"].includes(rawLevel)) return rawLevel;
    return "?";
  }

  function levelBadgeClass(canonical) {
    return "priority-" + (canonical || "C");
  }

  function renderTriageList(entries) {
    const container = getTriageListContainer();
    if (!container) return;
    container.innerHTML = "";

    if (entries.length === 0) {
      const empty = el("div");
      empty.style.padding = "var(--spacer-16)";
      empty.style.textAlign = "center";
      empty.style.color = "var(--text-tertiary)";
      empty.style.fontSize = "var(--body-sm-font-size)";
      empty.textContent = _activeLevel === "ALL"
        ? "分诊台账为空。让 Researcher agent 跑一次以添加条目。"
        : `没有 ${_activeLevel} 级条目`;
      container.appendChild(empty);
      return;
    }

    entries.forEach((entry) => {
      const canon = canonicalLevel(entry.level);
      const item = el("div", "triage-item");
      item.style.cursor = "pointer";
      item.dataset.filePath = entry.file_path || "";
      item.dataset.level = canon;

      // Top row: title + level badge
      const header = el("div");
      header.style.display = "flex";
      header.style.justifyContent = "space-between";
      header.style.alignItems = "flex-start";
      header.style.marginBottom = "var(--spacer-4)";
      header.style.gap = "var(--spacer-8)";

      const title = el("span");
      title.style.fontSize = "var(--body-sm-font-size)";
      title.style.color = "var(--text-default)";
      title.style.fontWeight = "500";
      title.style.flex = "1";
      title.style.lineHeight = "1.4";
      title.textContent = entry.title || "(未命名)";
      header.appendChild(title);

      const badge = el("span", "priority-badge " + levelBadgeClass(canon));
      badge.style.flexShrink = "0";
      badge.textContent = canon;
      header.appendChild(badge);
      item.appendChild(header);

      // L1: one-line reason (TLDR) — always visible in the list
      if (entry.reason) {
        const reasonEl = el("div");
        reasonEl.style.fontSize = "12px";
        reasonEl.style.color = "var(--text-tertiary)";
        reasonEl.style.lineHeight = "1.5";
        reasonEl.style.marginBottom = "var(--spacer-4)";
        // Truncate long reasons
        const reasonText = entry.reason.length > 80
          ? entry.reason.slice(0, 80) + "…"
          : entry.reason;
        reasonEl.textContent = reasonText;
        item.appendChild(reasonEl);
      }

      // Bottom row: date + score
      const footer = el("div");
      footer.style.display = "flex";
      footer.style.justifyContent = "space-between";
      footer.style.alignItems = "center";
      footer.style.fontFamily = "var(--font-family-mono)";
      footer.style.fontSize = "var(--body-sm-font-size)";
      footer.style.color = "var(--text-tertiary)";

      const date = el("span");
      date.textContent = entry.date || "?";
      footer.appendChild(date);

      if (entry.score) {
        const scoreEl = el("span");
        scoreEl.textContent = `★ ${entry.score.replace(/\*/g, "")}`;
        footer.appendChild(scoreEl);
      }
      item.appendChild(footer);

      item.addEventListener("click", () => loadArticle(entry));
      container.appendChild(item);
    });
  }

  function updateTriageCount(count) {
    const elCount = getTriageCountElement();
    if (elCount) elCount.textContent = `${count} 条`;
  }

  function filterByLevel(level) {
    _activeLevel = level;
    // Normalize all entries to canonical A/B/C then filter
    const filtered = level === "ALL"
      ? _allTriageEntries
      : _allTriageEntries.filter((e) => canonicalLevel(e.level) === level);
    renderTriageList(filtered);
    updateTriageCount(filtered.length);

    // Update tab styles
    getLevelTabs().forEach((tab) => {
      const tabLevel = tab.dataset.level;
      const isActive = tabLevel === level;
      if (isActive) {
        tab.style.background = "var(--bg-brand-surface-l1)";
        tab.style.color = "var(--bg-brand)";
        tab.style.fontWeight = "500";
      } else {
        tab.style.background = "";
        tab.style.color = "var(--text-secondary)";
        tab.style.fontWeight = "";
      }
    });
  }

  function wireLevelTabs() {
    getLevelTabs().forEach((tab) => {
      const level = tab.dataset.level || "ALL";
      tab.addEventListener("click", () => filterByLevel(level));
    });
  }

  async function loadTriage() {
    try {
      const resp = await Auth.fetch(`${API_BASE}/api/v1/knowledge/triage`);
      if (!resp.ok) throw new Error(`status ${resp.status}`);
      const data = await resp.json();
      _allTriageEntries = data.entries || [];
      filterByLevel("ALL");
    } catch (err) {
      console.warn("[knowledge.js] loadTriage failed:", err);
      const container = getTriageListContainer();
      if (container) {
        container.innerHTML = "";
        const errDiv = el("div");
        errDiv.style.padding = "var(--spacer-16)";
        errDiv.style.color = "var(--status-error-default)";
        errDiv.style.fontSize = "var(--body-sm-font-size)";
        errDiv.textContent = `分诊台账加载失败: ${err}`;
        container.appendChild(errDiv);
      }
    }
  }

  // ─── Article viewer (now merged into #kb-results) ──────────────

  function getArticleContainer() {
    // Articles now render in the same container as search results.
    // The breadcrumb bar above shows "← back to search" + article path.
    return document.getElementById("kb-results");
  }

  async function loadArticle(entry) {
    const container = getArticleContainer();
    if (!container || !entry.file_path) {
      // No local article archived — show the source URL as external link
      if (container && entry.source) {
        showExternalLinkPrompt(container, entry);
      }
      return;
    }

    // Mark clicked triage item active
    document.querySelectorAll(".triage-item").forEach((it) => it.classList.remove("active"));
    const clicked = document.querySelector(`.triage-item[data-file-path="${entry.file_path}"]`);
    if (clicked) clicked.classList.add("active");

    // Show breadcrumb bar with back-to-search
    const bcBar = document.getElementById("kb-breadcrumb-bar");
    const bcText = document.getElementById("kb-breadcrumb");
    if (bcBar) bcBar.style.display = "flex";
    if (bcText) bcText.textContent = `知识库 / ${entry.file_path}`;

    container.innerHTML = '<div style="padding: var(--spacer-24); color: var(--text-tertiary);"><em>加载中…</em></div>';

    try {
      const resp = await Auth.fetch(`${API_BASE}/api/v1/knowledge/articles/${entry.file_path}`);
      if (!resp.ok) {
        const text = await resp.text();
        container.innerHTML = `<div style="padding: var(--spacer-24); color: var(--status-error-default);">
          文章加载失败: ${resp.status} ${text.slice(0, 200)}</div>`;
        return;
      }
      const data = await resp.json();
      renderArticle(container, entry, data.content);
    } catch (err) {
      container.innerHTML = `<div style="padding: var(--spacer-24); color: var(--status-error-default);">
        加载错误: ${escapeHtml(String(err))}</div>`;
    }
  }

  function showExternalLinkPrompt(container, entry) {
    document.querySelectorAll(".triage-item").forEach((it) => it.classList.remove("active"));
    const clicked = document.querySelector(`.triage-item[data-file-path="${entry.file_path || ""}"]`);
    if (clicked) clicked.classList.add("active");

    const bcBar = document.getElementById("kb-breadcrumb-bar");
    const bcText = document.getElementById("kb-breadcrumb");
    if (bcBar) bcBar.style.display = "flex";
    if (bcText) bcText.textContent = entry.title;

    container.innerHTML = "";
    const card = el("div", "ds-card");
    card.style.padding = "var(--spacer-32)";
    card.style.textAlign = "center";

    const title = el("div");
    title.style.fontFamily = "var(--font-family-heading)";
    title.style.fontSize = "var(--heading-sm-font-size)";
    title.style.fontWeight = "600";
    title.style.color = "var(--text-default)";
    title.style.marginBottom = "var(--spacer-12)";
    title.textContent = entry.title;
    card.appendChild(title);

    const note = el("div");
    note.style.color = "var(--text-tertiary)";
    note.style.fontSize = "var(--body-sm-font-size)";
    note.style.marginBottom = "var(--spacer-16)";
    note.textContent = "此条台账没有对应的本地归档文章。可访问原文链接:";
    card.appendChild(note);

    if (entry.source) {
      const link = el("a");
      link.href = entry.source;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.style.color = "var(--bg-brand)";
      link.style.textDecoration = "none";
      link.style.fontSize = "var(--body-sm-font-size)";
      link.style.wordBreak = "break-all";
      link.textContent = entry.source;
      card.appendChild(link);
    } else {
      const na = el("div");
      na.style.color = "var(--text-tertiary)";
      na.style.fontSize = "var(--body-sm-font-size)";
      na.textContent = "(无原文链接)";
      card.appendChild(na);
    }

    container.appendChild(card);
  }

  function showSearchResultsView() {
    // Hide breadcrumb bar, show empty search state in #kb-results
    const bcBar = document.getElementById("kb-breadcrumb-bar");
    if (bcBar) bcBar.style.display = "none";

    document.querySelectorAll(".triage-item").forEach((it) => it.classList.remove("active"));

    const container = getArticleContainer();
    if (container) renderEmpty(container);
  }

  function wireBackToSearch() {
    const link = document.getElementById("kb-back-to-search");
    if (link) {
      link.addEventListener("click", (e) => {
        e.preventDefault();
        showSearchResultsView();
      });
    }
  }

  function renderArticle(container, entry, markdown, mode = "L2") {
    container.innerHTML = "";

    // ── Article header (always visible) ──
    const header = el("div");
    header.style.padding = "var(--spacer-16) var(--spacer-24)";
    header.style.borderBottom = "1px solid var(--border-neutral-l1)";

    const title = el("div");
    title.style.fontFamily = "var(--font-family-heading)";
    title.style.fontSize = "var(--heading-sm-font-size)";
    title.style.fontWeight = "600";
    title.style.color = "var(--text-default)";
    title.style.marginBottom = "var(--spacer-8)";
    title.textContent = entry.title;
    header.appendChild(title);

    const meta = el("div");
    meta.style.fontFamily = "var(--font-family-mono)";
    meta.style.fontSize = "var(--body-sm-font-size)";
    meta.style.color = "var(--text-tertiary)";
    const metaItems = [
      entry.date,
      entry.author && `作者: ${entry.author}`,
      canonicalLevel(entry.level) && `等级: ${canonicalLevel(entry.level)}`,
      entry.score && `评分: ${entry.score}`,
      entry.topic && `主题: ${entry.topic.slice(0, 40)}`,
    ].filter(Boolean);
    meta.textContent = metaItems.join(" · ");
    header.appendChild(meta);
    container.appendChild(header);

    // ── L1: TLDR card (always visible) ──
    if (entry.reason) {
      const l1 = el("div");
      l1.style.margin = "var(--spacer-16) var(--spacer-24)";
      l1.style.padding = "var(--spacer-12) var(--spacer-16)";
      l1.style.background = "var(--bg-brand-surface-l1)";
      l1.style.borderLeft = "3px solid var(--bg-brand)";
      l1.style.borderRadius = "var(--radius-4)";

      const l1Label = el("div");
      l1Label.style.fontSize = "var(--body-sm-font-size)";
      l1Label.style.fontWeight = "600";
      l1Label.style.color = "var(--bg-brand)";
      l1Label.style.marginBottom = "var(--spacer-4)";
      l1Label.textContent = "💡 L1 · 一句话摘要";
      l1.appendChild(l1Label);

      const l1Body = el("div");
      l1Body.style.fontSize = "var(--body-base-font-size)";
      l1Body.style.color = "var(--text-default)";
      l1Body.style.lineHeight = "1.6";
      l1Body.textContent = entry.reason;
      l1.appendChild(l1Body);
      container.appendChild(l1);
    }

    // ── L2: Summary card (expandable) ──
    const l2Card = el("div");
    l2Card.style.margin = "0 var(--spacer-24) var(--spacer-16)";
    l2Card.style.border = "1px solid var(--border-neutral-l1)";
    l2Card.style.borderRadius = "var(--radius-4)";
    l2Card.style.overflow = "hidden";

    const l2Header = el("div");
    l2Header.style.padding = "var(--spacer-12) var(--spacer-16)";
    l2Header.style.background = "var(--bg-overlay-l1)";
    l2Header.style.display = "flex";
    l2Header.style.justifyContent = "space-between";
    l2Header.style.alignItems = "center";
    l2Header.style.cursor = "pointer";

    const l2Label = el("span");
    l2Label.style.fontSize = "var(--body-sm-font-size)";
    l2Label.style.fontWeight = "600";
    l2Label.style.color = "var(--text-default)";
    l2Label.textContent = "📌 L2 · 摘要(开头 + 目录 + 关键数据)";
    l2Header.appendChild(l2Label);

    const l2Toggle = el("span");
    l2Toggle.style.color = "var(--text-secondary)";
    l2Toggle.style.fontSize = "var(--body-sm-font-size)";
    l2Toggle.textContent = "▼";
    l2Header.appendChild(l2Toggle);

    const l2Body = el("div");
    l2Body.style.padding = "var(--spacer-16)";
    l2Body.style.fontSize = "var(--body-base-font-size)";
    l2Body.style.color = "var(--text-default)";
    l2Body.style.lineHeight = "1.8";
    l2Body.style.display = "block";  // expanded by default
    l2Body.innerHTML = renderL2Summary(markdown, entry.file_path);

    l2Header.onclick = () => {
      const isHidden = l2Body.style.display === "none";
      l2Body.style.display = isHidden ? "block" : "none";
      l2Toggle.textContent = isHidden ? "▼" : "▶";
    };
    l2Card.appendChild(l2Header);
    l2Card.appendChild(l2Body);
    container.appendChild(l2Card);

    // ── L3: Full article (collapsed by default) ──
    const l3Card = el("div");
    l3Card.style.margin = "0 var(--spacer-24) var(--spacer-24)";
    l3Card.style.border = "1px solid var(--border-neutral-l1)";
    l3Card.style.borderRadius = "var(--radius-4)";
    l3Card.style.overflow = "hidden";

    const l3Header = el("div");
    l3Header.style.padding = "var(--spacer-12) var(--spacer-16)";
    l3Header.style.background = "var(--bg-overlay-l1)";
    l3Header.style.display = "flex";
    l3Header.style.justifyContent = "space-between";
    l3Header.style.alignItems = "center";
    l3Header.style.cursor = "pointer";

    const l3Label = el("span");
    l3Label.style.fontSize = "var(--body-sm-font-size)";
    l3Label.style.fontWeight = "600";
    l3Label.style.color = "var(--text-default)";
    l3Label.textContent = "📖 L3 · 完整全文";
    l3Header.appendChild(l3Label);

    const l3Toggle = el("span");
    l3Toggle.style.color = "var(--text-secondary)";
    l3Toggle.style.fontSize = "var(--body-sm-font-size)";
    l3Toggle.textContent = "▶";  // collapsed by default
    l3Header.appendChild(l3Toggle);

    const l3Body = el("div");
    l3Body.style.padding = "var(--spacer-16)";
    l3Body.style.fontSize = "var(--body-base-font-size)";
    l3Body.style.color = "var(--text-default)";
    l3Body.style.lineHeight = "1.8";
    l3Body.style.display = "none";  // collapsed by default
    l3Body.innerHTML = renderMarkdownLite(markdown, entry.file_path);

    l3Header.onclick = () => {
      const isHidden = l3Body.style.display === "none";
      l3Body.style.display = isHidden ? "block" : "none";
      l3Toggle.textContent = isHidden ? "▼" : "▶";
      // Collapse L2 when expanding L3 (optional UX)
      if (isHidden) {
        l2Body.style.display = "none";
        l2Toggle.textContent = "▶";
      }
    };
    l3Card.appendChild(l3Header);
    l3Card.appendChild(l3Body);
    container.appendChild(l3Card);
  }

  /**
   * L2 summary: extract opening paragraphs + section headings + first table.
   * Skips frontmatter (---) and image-only lines.
   */
  function renderL2Summary(md, articlePath = "") {
    if (!md) return "<em>(无内容)</em>";

    // Strip frontmatter
    let content = md.replace(/^---[\s\S]*?---\s*/, "");

    const lines = content.split("\n");
    const parts = [];

    // Phase 1: extract first 2-3 meaningful paragraphs (skip headings/images)
    let paraCount = 0;
    let currentPara = [];
    let inFrontmatter = false;

    for (let i = 0; i < lines.length && paraCount < 2; i++) {
      const line = lines[i].trim();
      if (!line) {
        if (currentPara.length > 0) {
          parts.push({ type: "p", text: currentPara.join(" ") });
          currentPara = [];
          paraCount++;
        }
        continue;
      }
      if (line.startsWith("#")) continue;        // skip headings in summary paras
      if (line.startsWith("![")) continue;        // skip images
      if (line.startsWith("|")) continue;         // skip tables in opening
      if (line.startsWith("```")) continue;       // skip code blocks
      currentPara.push(line);
    }
    if (currentPara.length > 0 && paraCount < 2) {
      parts.push({ type: "p", text: currentPara.join(" ") });
    }

    // Phase 2: collect all section headings (## and ###)
    const headings = [];
    for (const line of lines) {
      const m = line.match(/^(#{2,3})\s+(.+)$/);
      if (m) {
        headings.push({ level: m[1].length, text: m[2].trim() });
      }
    }
    if (headings.length > 0) {
      parts.push({ type: "headings", items: headings });
    }

    // Phase 3: extract first table (if any)
    let tableStarted = false;
    let tableLines = [];
    let tableDone = false;
    for (const line of lines) {
      if (line.trim().startsWith("|") && !tableDone) {
        tableStarted = true;
        tableLines.push(line);
      } else if (tableStarted && !line.trim().startsWith("|")) {
        if (tableLines.length > 0) {
          parts.push({ type: "table", lines: tableLines });
          tableDone = true;
        }
        tableStarted = false;
      }
    }

    // Phase 4: word count stats
    const wordCount = content.replace(/[#*|`!\[\]()\-]/g, "").length;
    parts.push({ type: "stats", words: wordCount });

    // Render parts
    let html = "";
    for (const p of parts) {
      if (p.type === "p") {
        html += `<p style="margin-bottom: var(--spacer-12); color: var(--text-secondary);">${escapeHtml(p.text)}</p>`;
      } else if (p.type === "headings") {
        html += '<div style="margin: var(--spacer-16) 0; padding: var(--spacer-12); background: var(--bg-overlay-l1); border-radius: var(--radius-4);">';
        html += '<div style="font-size: var(--body-sm-font-size); color: var(--text-tertiary); margin-bottom: var(--spacer-8);">📋 目录</div>';
        html += '<ul style="margin: 0; padding-left: var(--spacer-20); color: var(--text-secondary); font-size: var(--body-sm-font-size); line-height: 1.8;">';
        for (const h of p.items) {
          const indent = h.level === 3 ? "padding-left: var(--spacer-16);" : "";
          html += `<li style="${indent}">${escapeHtml(h.text)}</li>`;
        }
        html += '</ul></div>';
      } else if (p.type === "table") {
        // Render as-is (markdown table)
        html += '<div style="margin: var(--spacer-16) 0;">';
        html += '<div style="font-size: var(--body-sm-font-size); color: var(--text-tertiary); margin-bottom: var(--spacer-8);">📊 关键数据</div>';
        html += `<div style="overflow-x: auto;">${renderMarkdownLite(p.lines.join("\n"), articlePath)}</div>`;
        html += '</div>';
      } else if (p.type === "stats") {
        html += `<div style="margin-top: var(--spacer-16); padding-top: var(--spacer-12); border-top: 1px solid var(--border-neutral-l1); font-size: var(--body-sm-font-size); color: var(--text-tertiary);">`;
        html += `全文约 ${p.words} 字符 · 点击「📖 展开全文 (L3)」查看完整内容`;
        html += '</div>';
      }
    }

    return html;
  }

  function renderMarkdownLite(md, articlePath = "") {
    if (!md) return "";
    let html = escapeHtml(md);

    // Convert relative image paths to absolute /static/knowledge/... URLs.
    // Article markdown uses paths like ![](./images/img_0.png) or ![](images/img_0.png).
    // articlePath is like "00_Inbox/2026-06-16-xxx/article.md" — we extract the
    // directory and prefix it with /static/knowledge/.
    if (articlePath) {
      // Extract article directory (strip trailing /article.md)
      let articleDir = articlePath;
      const lastSlash = articleDir.lastIndexOf("/");
      if (lastSlash > 0) {
        articleDir = articleDir.substring(0, lastSlash);
      } else {
        articleDir = "";
      }
      if (articleDir) {
        const prefix = `/knowledge-static/${articleDir}/`;
        // Convert ![alt](./images/x.png) and ![alt](images/x.png)
        html = html.replace(
          /!\[([^\]]*)\]\((\.?\/?)(images\/[^)]+)\)/g,
          (match, alt, dotSlash, imgPath) => `![${alt}](${prefix}${imgPath})`
        );
      }
    }

    // Code blocks
    html = html.replace(/```([\s\S]*?)```/g, (_, code) =>
      `<pre style="background: var(--bg-overlay-l2); padding: var(--spacer-12); border-radius: var(--radius-4); overflow-x: auto;"><code>${code}</code></pre>`);
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code style="background: var(--bg-overlay-l2); padding: 2px 4px; border-radius: 3px;">$1</code>');
    // Images — render as <img> tags (max-width to fit container)
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g,
      '<img alt="$1" src="$2" style="max-width: 100%; height: auto; border-radius: var(--radius-4); margin: var(--spacer-8) 0;" />');
    // Headings
    html = html.replace(/^###### (.+)$/gm, '<h6>$1</h6>');
    html = html.replace(/^##### (.+)$/gm, '<h5>$1</h5>');
    html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^### (.+)$/gm, '<h3 style="margin-top: 16px;">$1</h3>');
    html = html.replace(/^## (.+)$/gm, '<h2 style="margin-top: 20px;">$1</h2>');
    html = html.replace(/^# (.+)$/gm, '<h1 style="margin-top: 24px;">$1</h1>');
    // Bold + italic
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    // Lists
    html = html.replace(/^- (.+)$/gm, "<li>$1</li>");
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
    // Paragraphs (double newline)
    html = html.replace(/\n\n/g, "</p><p>");
    html = `<p>${html}</p>`;
    return html;
  }

  // ─── Search ──────────────────────────────────────────────────
  function getSearchInput() {
    return document.querySelector('.kb-center input.ds-input[type="text"]');
  }

  function getSearchButton() {
    return document.querySelector(
      '.kb-center button.ds-btn-primary, .kb-center button.ds-btn'
    );
  }

  /**
   * Get the scrollable content area where search results render.
   * This is the #kb-results div under .kb-center.
   */
  function getResultContainer() {
    return document.getElementById("kb-results");
  }

  function clearMockArticle() {
    // Clear the search-results container (#kb-results)
    const container = getResultContainer();
    if (container) container.innerHTML = "";

    // Clear the breadcrumb
    const breadcrumb = document.getElementById("kb-breadcrumb");
    if (breadcrumb) breadcrumb.textContent = "";

    // Clear any leftover mock .triage-item elements (defensive — HTML should
    // already have them removed, but this protects against stale markup)
    document.querySelectorAll(".kb-left .triage-item").forEach((el) => el.remove());
  }

  function renderEmpty(container) {
    container.innerHTML = "";
    const card = el("div", "ds-card");
    card.style.padding = "var(--spacer-32)";
    card.style.textAlign = "center";
    card.style.color = "var(--text-tertiary)";
    card.textContent = "输入关键词搜索知识库";
    container.appendChild(card);
  }

  function renderLoading(container) {
    container.innerHTML = "";
    const card = el("div", "ds-card");
    card.style.padding = "var(--spacer-24)";
    card.style.color = "var(--text-tertiary)";
    card.innerHTML = '<em>检索中…(向量召回 + 重排序约 1-3 秒)</em>';
    container.appendChild(card);
  }

  function renderError(container, message) {
    container.innerHTML = "";
    const card = el("div", "ds-card");
    card.style.padding = "var(--spacer-16)";
    card.style.color = "var(--status-error-default)";
    card.textContent = `搜索失败: ${message}`;
    container.appendChild(card);
  }

  function renderResults(container, data) {
    container.innerHTML = "";

    // Summary header
    const summary = el("div", "ds-card");
    summary.style.padding = "var(--spacer-12) var(--spacer-16)";
    summary.style.display = "flex";
    summary.style.justifyContent = "space-between";
    summary.style.alignItems = "center";
    summary.innerHTML = `
      <span style="font-family: var(--font-family-heading); font-size: var(--body-lg-font-size); font-weight: 600; color: var(--text-default);">
        搜索结果
      </span>
      <span style="font-family: var(--font-family-mono); font-size: var(--body-sm-font-size); color: var(--text-tertiary);">
        ${data.total} 条 · ${data.elapsed_ms}ms · 查询: ${escapeHtml(data.query)}
      </span>
    `;
    container.appendChild(summary);

    if (!data.results || data.results.length === 0) {
      const empty = el("div", "ds-card");
      empty.style.padding = "var(--spacer-24)";
      empty.style.textAlign = "center";
      empty.style.color = "var(--text-tertiary)";
      empty.textContent = "未找到相关内容,试试其他关键词?";
      container.appendChild(empty);
      return;
    }

    // Result cards
    data.results.forEach((r, idx) => {
      const card = el("div", "ds-card");
      card.style.marginBottom = "var(--spacer-12)";

      // Title row
      const titleRow = el("div");
      titleRow.style.display = "flex";
      titleRow.style.justifyContent = "space-between";
      titleRow.style.alignItems = "center";
      titleRow.style.marginBottom = "var(--spacer-8)";

      const title = el("span");
      title.style.fontFamily = "var(--font-family-heading)";
      title.style.fontSize = "var(--body-base-font-size)";
      title.style.fontWeight = "600";
      title.style.color = "var(--text-default)";
      title.textContent = `#${idx + 1} · ${r.title || r.source || r.id || "未知来源"}`;
      titleRow.appendChild(title);

      // Score badge
      const score = r.rerank_score != null ? r.rerank_score : r.similarity;
      const scoreLabel = r.rerank_score != null
        ? `rerank ${score.toFixed(3)}`
        : `sim ${score.toFixed(3)}`;
      const badge = el("span", "ds-tag ds-tag-primary", scoreLabel);
      titleRow.appendChild(badge);
      card.appendChild(titleRow);

      // Source + stage
      const meta = el("div");
      meta.style.fontFamily = "var(--font-family-mono)";
      meta.style.fontSize = "var(--body-sm-font-size)";
      meta.style.color = "var(--text-tertiary)";
      meta.style.marginBottom = "var(--spacer-8)";
      const stageLabel = r.search_stage === "reranked" ? "重排序" : "向量";
      meta.textContent = `${r.source || "unknown"} · ${stageLabel} · similarity ${r.similarity.toFixed(3)}`;
      card.appendChild(meta);

      // Preview text
      const preview = el("div");
      preview.style.fontSize = "var(--body-base-font-size)";
      preview.style.color = "var(--text-secondary)";
      preview.style.lineHeight = "1.6";
      preview.style.whiteSpace = "pre-wrap";
      preview.style.wordBreak = "break-word";
      preview.textContent = r.preview || r.text || "";
      card.appendChild(preview);

      // Metadata chips (if any)
      if (r.metadata && Object.keys(r.metadata).length > 0) {
        const chips = el("div");
        chips.style.display = "flex";
        chips.style.flexWrap = "wrap";
        chips.style.gap = "var(--spacer-4)";
        chips.style.marginTop = "var(--spacer-8)";
        for (const [k, v] of Object.entries(r.metadata).slice(0, 5)) {
          if (v == null || v === "") continue;
          const chip = el("span", "ds-tag", `${k}: ${String(v).slice(0, 30)}`);
          chips.appendChild(chip);
        }
        if (chips.children.length > 0) card.appendChild(chips);
      }

      container.appendChild(card);
    });
  }

  async function doSearch(query) {
    const container = getResultContainer();
    if (!container) {
      console.warn("knowledge.js: result container not found");
      return;
    }
    renderLoading(container);
    try {
      const url = `${API_BASE}/api/v1/rag/search?q=${encodeURIComponent(query)}&top_k=10&rerank=true`;
      const resp = await Auth.fetch(url);
      if (!resp.ok) {
        const errText = await resp.text();
        renderError(container, `HTTP ${resp.status}: ${errText.slice(0, 200)}`);
        return;
      }
      const data = await resp.json();
      renderResults(container, data);
    } catch (err) {
      renderError(container, String(err));
    }
  }

  // ─── Wire up ─────────────────────────────────────────────────
  async function wire() {
    // Require authentication
    const user = await Auth.requireUser();
    if (!user) return;
    Auth.renderUserBadge(user);

    const input = getSearchInput();
    const btn = getSearchButton();
    if (!input || !btn) {
      console.warn("knowledge.js: search input or button not found", { input, btn });
      return;
    }

    // Enter to search
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const q = input.value.trim();
        if (q) doSearch(q);
      }
    });

    // Button click
    btn.addEventListener("click", () => {
      const q = input.value.trim();
      if (q) doSearch(q);
    });

    // Initial empty state for search results (center panel #kb-results)
    clearMockArticle();
    const container = getResultContainer();
    if (container) renderEmpty(container);

    // Load status + triage ledger (left panel real data + wire A/B/C tabs)
    loadStatus();
    wireLevelTabs();
    wireBackToSearch();
    loadTriage();

    console.info("[knowledge.js] wired up");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
