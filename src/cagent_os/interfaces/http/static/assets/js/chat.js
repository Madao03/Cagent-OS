/**
 * chat.js — Phase 4c wiring for the chat page.
 *
 * Responsibilities:
 *   1. Clear the mock conversation/thread content baked into chat.html
 *   2. Wire the textarea + send button to POST /api/v1/conversations/{id}/messages
 *   3. Parse the SSE stream (text/event-stream) chunk-by-chunk
 *   4. Render user bubbles, ReAct tool-call steps, and the assistant's
 *      streamed markdown answer in real time
 *
 * Design notes:
 *   - Uses fetch + ReadableStream (NOT EventSource) because the backend
 *     endpoint is POST, and EventSource only supports GET.
 *   - Conversation ID is generated client-side as a UUID per session and
 *     reused across messages (matches backend's auto-create-on-first-msg).
 *   - User identity is hardcoded "default" — Phase 4c single-user mode.
 *     Phase 4 multi-user will swap this for a JWT-derived principal.
 */

(function () {
  "use strict";

  // ───────────────────────────────────────────────────────────────
  // Config
  // ───────────────────────────────────────────────────────────────
  const API_BASE = "";  // same origin; static + API both served by FastAPI
  const USER_ID = "default";
  const PRINCIPAL_ID = "default";

  // Conversation ID — changes when user clicks "新建" to start a fresh thread.
  // Use `let` (not `const`) so newConversation() can reassign it.
  function generateConvId() {
    return "web-" +
      (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36));
  }
  let CONVERSATION_ID = generateConvId();
  /** The single "main" conversation — "新建" button navigates here, never creates duplicates. */
  let _mainConvId = CONVERSATION_ID;

  // ───────────────────────────────────────────────────────────────
  // DOM helpers
  // ───────────────────────────────────────────────────────────────

  function el(tag, className, text) {
    const n = document.createElement(tag);
    if (className) n.className = className;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function clearMockContent() {
    // Remove all existing children inside the chat-thread so the baked-in
    // NVDA example doesn't confuse the user. Keep the div itself.
    const thread = document.querySelector(".chat-thread");
    if (thread) thread.innerHTML = "";

    // Remove only baked-in mock items (no data-conv-id) from the sidebar.
    // Do NOT wipe the entire convList — loadConversationList() is the sole
    // owner of list content. Wiping it here causes a race where the real
    // conversations flash briefly then disappear.
    const convList = document.querySelector(".chat-conv-list");
    if (convList) {
      convList.querySelectorAll(".chat-conv-item:not([data-conv-id])").forEach(el => el.remove());
      // If list is now empty, add a placeholder while we wait for the API
      if (convList.children.length === 0) {
        _ensureCurrentConvInList(convList);
      }
    }

    // Update top-bar model selector text
    // (shell.js also normalizes the top-right "Model: ..." tag for all pages)
    const modelSel = document.querySelector(".chat-model-selector");
    if (modelSel) modelSel.textContent = "DeepSeek V4 Pro";
  }

  // ───────────────────────────────────────────────────────────────
  // Rendering
  // ───────────────────────────────────────────────────────────────

  function renderUserMessage(text) {
    const thread = document.querySelector(".chat-thread");
    if (!thread) return;

    const msg = el("div", "chat-msg-user");
    const bubble = el("div", "chat-user-bubble");
    bubble.textContent = text;
    msg.appendChild(bubble);
    thread.appendChild(msg);
    thread.scrollTop = thread.scrollHeight;
  }

  function renderAssistantShell() {
    /** Create an empty assistant message bubble and return {root, content, stepsEl}. */
    const thread = document.querySelector(".chat-thread");
    if (!thread) return null;

    const msg = el("div", "chat-msg-assistant");
    const head = el("div", "chat-assistant-head");
    const avatar = el("span", "ds-avatar chat-assistant-avatar", "AI");
    avatar.setAttribute("aria-label", "AI Agent");
    const name = el("span", "chat-assistant-name", "CagentOS");
    head.appendChild(avatar);
    head.appendChild(name);
    msg.appendChild(head);

    // Steps area (ReAct tool calls will render here)
    const stepsEl = el("div", "chat-react-steps");
    msg.appendChild(stepsEl);

    // Bubble for the streamed answer
    const bubble = el("div", "chat-assistant-bubble");
    const content = el("div", "chat-md-p");
    bubble.appendChild(content);
    msg.appendChild(bubble);

    thread.appendChild(msg);
    thread.scrollTop = thread.scrollHeight;
    return { root: msg, content, stepsEl };
  }

  function renderReactStep(stepsEl, payload) {
    /**
     * Render a single ReAct step (tool call/result).
     * Returns the step DOM node so caller can update it on later events.
     */
    const step = el("div", "react-step");
    const header = el("div", "react-step-header");

    const icon = el("span", "react-step-icon");
    icon.setAttribute("data-icon", "code");
    header.appendChild(icon);

    const toolName = el("span", "react-step-tool", payload.tool_name || "tool");
    header.appendChild(toolName);

    // ★ Determine status for visual styling
    const statusSpan = el("span", "react-step-status");
    const statusIcon = el("span", "react-step-status-icon");
    let statusText = payload.tool_status || "running";
    let iconName = "check-small"; // default: success
    let statusClass = "react-step-status-ok";
    let useSpinner = false;

    if (payload.phase === "tool_call") {
      statusText = "调用中";
      statusClass = "react-step-status-running";
      useSpinner = true;
    } else if (payload.phase === "tool_result") {
      if (payload.tool_status === "error" || payload.phase === "tool_result" && payload.tool_message) {
        statusText = "失败";
        iconName = "Close";
        statusClass = "react-step-status-error";
      } else {
        statusText = "成功";
        iconName = "check-small";
        statusClass = "react-step-status-ok";
      }
    } else if (payload.phase === "tool_plan") {
      statusText = "调用中";
      statusClass = "react-step-status-running";
      useSpinner = true;
    }

    statusSpan.classList.add(statusClass);
    if (useSpinner) {
      statusSpan.appendChild(el("span", "", "···"));
    } else {
      statusIcon.setAttribute("data-icon", iconName);
      statusSpan.appendChild(statusIcon);
    }
    statusSpan.appendChild(el("span", "", statusText));
    header.appendChild(statusSpan);
    step.appendChild(header);

    if (payload.tool_input_preview) {
      const args = el("div", "react-step-args", payload.tool_input_preview);
      step.appendChild(args);
    }
    if (payload.tool_output_preview) {
      const result = el("div", "react-step-result", payload.tool_output_preview);
      step.appendChild(result);
    } else if (payload.tool_message) {
      const result = el("div", "react-step-result", payload.tool_message);
      step.appendChild(result);
    }

    stepsEl.appendChild(step);
    const thread = document.querySelector(".chat-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
    return step;
  }

  // ───────────────────────────────────────────────────────────────
  // SSE parsing
  // ───────────────────────────────────────────────────────────────

  /**
   * Parse an SSE byte stream from a fetch Response.
   * Calls onData(jsonPayload) for each `data: {...}` line.
   *
   * SSE spec: messages separated by \n\n. Inside a message, each line
   * starts with `data: ` (could span multiple lines, but our backend
   * emits single-line JSON per event).
   */
  async function consumeSSE(response, onData, onDone) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      // Split on double-newline (event boundary)
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const rawEvent = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);

        // Each line of the event that starts with `data: `
        for (const line of rawEvent.split("\n")) {
          const trimmed = line.trim();
          if (!trimmed.startsWith("data:")) continue;
          const jsonStr = trimmed.slice(5).trim();
          if (!jsonStr) continue;
          try {
            const payload = JSON.parse(jsonStr);
            onData(payload);
          } catch (err) {
            console.warn("Failed to parse SSE data chunk:", jsonStr, err);
          }
        }
      }
    }
    // Flush any remaining buffer (some servers don't close with \n\n)
    if (buffer.trim()) {
      for (const line of buffer.split("\n")) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const jsonStr = trimmed.slice(5).trim();
        if (!jsonStr) continue;
        try {
          onData(JSON.parse(jsonStr));
        } catch (err) {
          console.warn("Failed to parse trailing SSE data:", jsonStr, err);
        }
      }
    }
    onDone();
  }

  // ───────────────────────────────────────────────────────────────
  // Markdown-lite (minimal — bold, headers, bullets, tables)
  // ───────────────────────────────────────────────────────────────

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function _processInline(line) {
    return line
      .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" class="chat-md-link">$1</a>')
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/\~\~(.+?)\~\~/g, "<del>$1</del>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }

  function _parseTableRow(row) {
    // "| a | b | c |" → ["a","b","c"]
    const trimmed = row.trim();
    if (!trimmed.startsWith("|") || !trimmed.endsWith("|")) return [];
    return trimmed.slice(1, -1).split("|");
  }

  function _parseTableAlign(sepRow) {
    const cells = _parseTableRow(sepRow);
    return cells.map(c => {
      const t = c.trim();
      if (t.startsWith(":") && t.endsWith(":")) return "center";
      if (t.endsWith(":")) return "right";
      return "left";
    });
  }

  function _isTableRow(line) {
    const t = line.trim();
    return t.startsWith("|") && t.endsWith("|");
  }

  function _isTableSep(line) {
    // separator row: | --- | :--- | ---: | :---: |
    const t = line.trim();
    if (!t.startsWith("|") || !t.endsWith("|")) return false;
    return /^\|[\s\-:]+\|/.test(t);
  }

  function _renderTable(lines, headerIdx, sepIdx, endIdx) {
    const headers = _parseTableRow(lines[headerIdx]);
    const aligns = _parseTableAlign(lines[sepIdx]);

    let html = '<div class="chat-md-table-card"><table class="chat-md-table"><thead><tr>';
    for (let i = 0; i < headers.length; i++) {
      const a = aligns[i] || "left";
      html += `<th class="chat-md-th-${a}">${_processInline(headers[i].trim())}</th>`;
    }
    html += '</tr></thead><tbody>';

    for (let r = sepIdx + 1; r <= endIdx; r++) {
      const t = lines[r].trim();
      if (!_isTableRow(t)) continue;
      const cells = _parseTableRow(t);
      html += '<tr>';
      for (let i = 0; i < Math.min(cells.length, headers.length); i++) {
        const a = aligns[i] || "left";
        const cls = a === "right" ? ' class="num"' : '';
        html += `<td${cls} class="chat-md-td-${a}">${_processInline(cells[i].trim())}</td>`;
      }
      html += '</tr>';
    }
    html += '</tbody></table></div>';
    return html;
  }

  function renderMarkdownLite(text) {
    /** Markdown renderer: bold, headers, code blocks, bullet lists, tables. */
    const lines = escapeHtml(text).split("\n");

    // ── Pre-scan: find markdown table blocks ──
    const tableRanges = [];  // { header, sep, end }
    const tableLineSet = new Set();
    let i = 0;
    while (i < lines.length) {
      if (lines[i].trim().startsWith("```")) {
        // skip code blocks
        i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) i++;
        i++;
        continue;
      }
      if (!_isTableRow(lines[i])) { i++; continue; }
      // potential header — look for separator on next non-empty line
      let sep = i + 1;
      while (sep < lines.length && lines[sep].trim() === "") sep++;
      if (sep >= lines.length || !_isTableSep(lines[sep])) { i++; continue; }
      // header + separator found — collect data rows
      let end = sep;
      for (let j = sep + 1; j < lines.length; j++) {
        if (_isTableRow(lines[j])) {
          end = j;
        } else if (lines[j].trim() === "") {
          // peek: is next non-empty a table row? then this blank is inside table
          let next = j + 1;
          while (next < lines.length && lines[next].trim() === "") next++;
          if (next < lines.length && _isTableRow(lines[next])) {
            continue; // blank line inside multi-section table
          }
          break;
        } else {
          break;
        }
      }
      for (let k = i; k <= end; k++) tableLineSet.add(k);
      tableRanges.push({ header: i, sep, end });
      i = end + 1;
    }

    // ── Render ──
    let html = "";
    let inCode = false;
    let inUl = false;
    let inOl = false;
    let inBq = false;
    let inDerivations = false;
    const closeUl = () => { if (inUl) { html += "</ul>"; inUl = false; } };
    const closeOl = () => { if (inOl) { html += "</ol>"; inOl = false; } };
    const closeBq = () => { if (inBq) { html += "</blockquote>"; inBq = false; } };
    const closeAllBlocks = () => { closeUl(); closeOl(); closeBq(); };

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // skip code-fenced block lines from pre-scan (they're not tables)
      if (tableLineSet.has(i) && !inCode && !inUl && !inOl && !inBq) {
        const range = tableRanges.find(r => i === r.header);
        if (range) { html += _renderTable(lines, range.header, range.sep, range.end); }
        continue;
      }

      if (line.trim().startsWith("```")) {
        if (inCode) { html += "</code></pre>"; inCode = false; }
        else { closeAllBlocks(); html += "<pre><code>"; inCode = true; }
        continue;
      }
      if (inCode) { html += line + "\n"; continue; }

      const coded = _processInline(line);
      const raw = line.trim();

      // ★ [derivations] block → collapsible details
      if (raw === "[derivations]" || raw.startsWith("[derivations]")) {
        closeAllBlocks();
        inDerivations = true;
        html += '<details class="chat-md-derivations"><summary>查看计算过程</summary>';
        continue;
      }
      if (raw === "[/derivations]" || raw.startsWith("[/derivations]")) {
        if (inDerivations) { html += '</details>'; inDerivations = false; }
        continue;
      }
      if (inDerivations) { html += `<p>${coded}</p>`; continue; }

      if (/^####\s+/.test(coded)) {
        closeAllBlocks();
        html += `<h4 class="chat-md-h4">${coded.replace(/^####\s+/, "")}</h4>`;
      } else if (/^###\s+/.test(coded)) {
        closeAllBlocks();
        html += `<h3 class="chat-md-h3">${coded.replace(/^###\s+/, "")}</h3>`;
      } else if (/^##\s+/.test(coded)) {
        closeAllBlocks();
        html += `<h2 class="chat-md-h2">${coded.replace(/^##\s+/, "")}</h2>`;
      } else if (/^#\s+/.test(coded)) {
        closeAllBlocks();
        html += `<h1 class="chat-md-h1">${coded.replace(/^#\s+/, "")}</h1>`;
      } else if (/^(-{3,}|\*{3,})\s*$/.test(raw)) {
        closeAllBlocks();
        html += '<hr class="chat-md-hr">';
      } else if (/^>\s?/.test(coded)) {
        closeUl(); closeOl();
        if (!inBq) { html += '<blockquote class="chat-md-blockquote">'; inBq = true; }
        html += `<p>${coded.replace(/^>\s?/, "")}</p>`;
      } else if (/^\d+\.\s+/.test(coded)) {
        closeUl(); closeBq();
        if (!inOl) { html += '<ol class="chat-md-ol">'; inOl = true; }
        html += `<li>${coded.replace(/^\d+\.\s+/, "")}</li>`;
      } else if (/^\s*[-*]\s+/.test(coded)) {
        closeOl(); closeBq();
        if (!inUl) { html += "<ul>"; inUl = true; }
        html += `<li>${coded.replace(/^\s*[-*]\s+/, "")}</li>`;
      } else if (coded.trim() === "") {
        closeAllBlocks();
      } else {
        closeAllBlocks();
        html += `<p>${coded}</p>`;
      }
    }
    closeAllBlocks();
    if (inCode) html += "</code></pre>";
    return html;
  }

  // ───────────────────────────────────────────────────────────────
  // Main send loop
  // ───────────────────────────────────────────────────────────────

  let isSending = false;
  let _firstAssistantDone = false;  // Track first answer for disclaimer injection

  async function sendMessage(text) {
    if (isSending || !text.trim()) return;
    isSending = true;
    setSendButtonState(true);

    renderUserMessage(text);

    // Update sidebar title immediately — first message becomes the conversation name
    _updateSidebarTitle(text);

    const shell = renderAssistantShell();
    if (!shell) {
      isSending = false;
      setSendButtonState(false);
      return;
    }

    // Show a "thinking" placeholder
    shell.content.innerHTML = '<em style="color: var(--text-tertiary);">思考中…</em>';

    let answerBuffer = "";
    let lastPhase = "";

    try {
      const resp = await Auth.fetch(
        `${API_BASE}/api/v1/conversations/${CONVERSATION_ID}/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
          },
          body: JSON.stringify({ content: text, user_id: USER_ID, stream: true }),
        }
      );

      if (!resp.ok) {
        const errText = await resp.text();
        shell.content.innerHTML = `<span style="color: var(--status-error-default);">请求失败 (${resp.status}): ${escapeHtml(errText.slice(0, 300))}</span>`;
        return;
      }

      // Refresh sidebar immediately — conversation is created server-side
      // the moment the POST lands, no need to wait for the full response.
      loadConversationList().catch(() => {});

      await consumeSSE(
        resp,
        (payload) => {
          // Route event by phase
          if (payload.phase === "tool_call" || payload.phase === "tool_plan") {
            renderReactStep(shell.stepsEl, payload);
            lastPhase = "tool";
          } else if (payload.phase === "tool_result") {
            // Could update existing step or append a new row showing result
            renderReactStep(shell.stepsEl, payload);
            lastPhase = "tool";
          } else if (payload.phase === "answer_delta") {
            // Incremental chunk — append to buffer
            if (lastPhase !== "answer") {
              shell.content.innerHTML = "";
              lastPhase = "answer";
            }
            const chunk = payload.answer_chunk || "";
            answerBuffer += chunk;
            shell.content.innerHTML = renderMarkdownLite(answerBuffer);
            const thread = document.querySelector(".chat-thread");
            if (thread) thread.scrollTop = thread.scrollHeight;
          } else if (payload.phase === "final_answer") {
            // Complete final answer — REPLACE buffer (authoritative version).
            // Without this, buffer would contain both incremental deltas AND
            // the full answer → user sees the response twice.
            if (lastPhase !== "answer") {
              shell.content.innerHTML = "";
              lastPhase = "answer";
            }
            answerBuffer = payload.answer_chunk || "";
            shell.content.innerHTML = renderMarkdownLite(answerBuffer);
            const thread = document.querySelector(".chat-thread");
            if (thread) thread.scrollTop = thread.scrollHeight;
          } else if (payload.phase === "error") {
            const msg = payload.summary || payload.tool_message || "Unknown error";
            shell.content.innerHTML = `<span style="color: var(--status-error-default);">错误: ${escapeHtml(msg)}</span>`;
          } else if (payload.phase === "provenance") {
            // ★ Provenance data available — post-process the message to add data cards
            lastPhase = "provenance";
            answerBuffer = payload.answer_chunk || answerBuffer;
            if (payload.provenance) {
              applyProvenanceToShell(shell, payload.provenance);
            }
          }
        },
        () => {
          // Stream complete
          if (!answerBuffer) {
            shell.content.innerHTML = '<em style="color: var(--text-tertiary);">(无返回内容)</em>';
          }
          // ★ First assistant message per session: inject disclaimer
          if (!_firstAssistantDone) {
            _firstAssistantDone = true;
            const disc = document.createElement("div");
            disc.className = "chat-disclaimer";
            disc.textContent = "内容由 AI 生成，不构成投资建议。数据请自行核实。";
            shell.root.appendChild(disc);
          }
        }
      );
    } catch (err) {
      console.error("sendMessage error:", err);
      shell.content.innerHTML = `<span style="color: var(--status-error-default);">连接错误: ${escapeHtml(String(err))}</span>`;
    } finally {
      isSending = false;
      setSendButtonState(false);
    }
  }

  // ───────────────────────────────────────────────────────────────
  // Provenance — data cards, untraced markers, unavailable state
  // ───────────────────────────────────────────────────────────────

  /** @type {Object.<string, Object>} fact_id → Fact fields */
  let _provFacts = {};
  /** @type {Array} traced numbers with fact_id links */
  let _provTraced = [];
  /** @type {Array} untraced numbers */
  let _provUntraced = [];
  /** @type {Object.<string, string>} ticker → reason */
  let _provOutOfCoverage = {};
  /** @type {Object.<string, Object>} fact_id → derivation info */
  let _provDerivations = {};

  // Source name → display label mapping
  const SOURCE_LABELS = {
    "EDGAR": "SEC EDGAR",
    "akshare": "akshare（新浪财经）",
    "FRED": "FRED（美联储）",
    "yfinance": "yfinance",
    "CoinMetrics": "Coin Metrics",
    "Binance": "Binance",
    "DeFiLlama": "DeFi Llama",
    "alternative.me": "alternative.me",
    "PANews": "PANews",
    "web": "网页",
    "unknown": "未知来源",
  };

  // Period type → Chinese label
  const PERIOD_LABELS = {
    "quarter": "单季",
    "fiscal_year": "全年",
    "cumulative": "累计",
  };

  // Audit context: supplemental info for the audit status line.
  // Only adds context when the reason differs from the label itself.
  function _auditContext(fact) {
    if (fact.audited === true) return "";  // "已审计" already in main label
    if (fact.audited === false) {
      // EDGAR LANE 2 (6-K/8-K): earnings press release, never audited
      const src = (fact.source || "").toLowerCase();
      if (src.includes("edgar")) return "（业绩新闻稿，未经审计）";
      // A-share interim reports
      if (fact.period_type === "quarter") return "（季报未经审计）";
      if (fact.period_type === "cumulative") return "（半年报/三季报未经审计）";
      return "";  // "未审计" already in main label — no duplicate
    }
    return "";
  }

  function _sourceTierLabel(tier) {
    if (tier === "primary" || tier === "0_primary") return "一级来源";
    if (tier === "secondary" || tier === "1_media_pro") return "⚠️ 二手聚合";
    if (tier === "curated") return "知识库精选";
    if (tier === "3_aggregator") return "社交媒体/博客";
    return tier || "未知";
  }

  function _buildProvCardHTML(fact) {
    /** Build the inner HTML for a provenance data card from a Fact object. */
    const sourceLabel = SOURCE_LABELS[fact.source] || fact.source || "未知";
    const tier = fact.source_tier || "";
    // ★ Infer tier from source if source_tier is empty
    const _PRIMARY_SOURCES = ["EDGAR", "FRED", "CoinMetrics", "Binance", "DeFiLlama", "alternative.me", "akshare"];
    let effectiveTier = tier;
    if (!effectiveTier && !isDerived) {
      if (_PRIMARY_SOURCES.some(s => fact.source && fact.source.includes(s))) effectiveTier = "primary";
      else if (fact.source === "knowledge_base") effectiveTier = "curated";
    }
    const tierClass = effectiveTier === "primary" ? "prov-card-row-ok" : (effectiveTier === "secondary" ? "prov-card-row-warn" : "");

    const isDerived = fact.kind === "derived";
    const derivInfo = isDerived ? _provDerivations[fact.id] || null : null;

    let periodStr = "";
    if (fact.period_start || fact.period_end) {
      const pt = PERIOD_LABELS[fact.period_type] || fact.period_type || "";
      periodStr = `${fact.period_start || "?"} ~ ${fact.period_end || "?"}` + (pt ? `（${pt}）` : "");
    }

    // ★ Caliber: hide technical values that have no user-facing meaning
    let caliber = fact.caliber || "";
    const _TECHNICAL_CALIBERS = ["value", "verified_citation", "data", ""];
    if (isDerived) {
      caliber = "派生计算值";
    } else if (_TECHNICAL_CALIBERS.includes(caliber)) {
      caliber = "";  // Hide meaningless technical caliber
    }
    const acctStd = fact.accounting_standard || "";

    const audited = fact.audited;
    let auditHTML = "";
    if (audited === true) {
      auditHTML = '<span class="prov-card-row-ok">✅ 已审计 ' + escapeHtml(_auditContext(fact)) + '</span>';
    } else if (audited === false) {
      auditHTML = '<span class="prov-card-row-warn">❌ 未审计 ' + escapeHtml(_auditContext(fact)) + '</span>';
    } else {
      // ★ null/undefined = 不适用 (FRED/行情/crypto 等非财报数据)
      // Show "不适用" instead of "未知" for cleaner semantics
      auditHTML = '<span class="prov-card-row-val" style="color:var(--text-tertiary);font-size:11px">不适用</span>';
    }

    const precision = fact.precision ? `（精度: ${escapeHtml(fact.precision)}）` : "";

    let html = '<div class="prov-card-header">';
    html += `<span class="prov-card-value">${escapeHtml(fact.display || fact.value || "")}${escapeHtml(precision)}</span>`;
    html += '</div>';
    html += '<div class="prov-card-rows">';

    // Source
    html += `<div class="prov-card-row"><span class="prov-card-label">来源</span><span class="prov-card-row-val">${escapeHtml(sourceLabel)}</span></div>`;

    // Tier
    if (effectiveTier) {
      html += `<div class="prov-card-row"><span class="prov-card-label">层级</span><span class="${tierClass}">${_sourceTierLabel(effectiveTier)}</span></div>`;
    }

    // Period
    if (periodStr) {
      html += `<div class="prov-card-row"><span class="prov-card-label">期间</span><span class="prov-card-row-val">${escapeHtml(periodStr)}</span></div>`;
    }

    // Caliber
    if (caliber) {
      html += `<div class="prov-card-row"><span class="prov-card-label">口径</span><span class="prov-card-row-val">${escapeHtml(caliber)}</span></div>`;
    }

    // Audit
    html += `<div class="prov-card-row"><span class="prov-card-label">审计</span>${auditHTML}</div>`;

    // Accounting standard
    if (acctStd) {
      html += `<div class="prov-card-row"><span class="prov-card-label">准则</span><span class="prov-card-row-val">${escapeHtml(acctStd)}</span></div>`;
    }

    // Currency
    if (fact.currency) {
      html += `<div class="prov-card-row"><span class="prov-card-label">货币</span><span class="prov-card-row-val">${escapeHtml(fact.currency)}</span></div>`;
    }

    // Capability
    if (fact.capability && !isDerived) {
      html += `<div class="prov-card-row"><span class="prov-card-label">工具</span><span class="prov-card-row-val" style="font-family:var(--font-family-mono);font-size:10px">${escapeHtml(fact.capability)}</span></div>`;
    }

    // ★ Media tier for verified_citation (social media vs pro media vs official)
    if (fact.kind === "verified_citation" || fact.media_tier) {
      const mt = fact.media_tier || "";
      let mtLabel = "";
      let mtColor = "var(--text-tertiary)";
      if (mt === "0_primary") { mtLabel = "🟢 一手来源"; mtColor = "var(--color-success)"; }
      else if (mt === "1_media_pro") { mtLabel = "🟡 专业媒体"; mtColor = "var(--color-warning)"; }
      else if (mt === "3_aggregator") { mtLabel = "🔴 社交媒体/博客"; mtColor = "var(--color-error)"; }
      if (mtLabel) {
        html += `<div class="prov-card-row"><span class="prov-card-label">信源</span><span class="prov-card-row-val" style="color:${mtColor};font-size:11px">${mtLabel}</span></div>`;
      }
    }

    // ★ Citation sentence (for verified_citation: show the matching original text)
    if (fact.kind === "verified_citation" && fact.citation_sentence) {
      html += `<div class="prov-card-row" style="flex-direction:column;align-items:flex-start"><span class="prov-card-label">原句</span><span class="prov-card-row-val" style="font-size:11px;color:var(--text-secondary);font-style:italic;margin-top:2px">"${escapeHtml(fact.citation_sentence)}"</span></div>`;
    }

    // ★ Clickable URL
    if (fact.url) {
      const shortUrl = fact.url.length > 50 ? fact.url.substring(0, 47) + "..." : fact.url;
      html += `<div class="prov-card-row"><span class="prov-card-label">链接</span><a href="${escapeHtml(fact.url)}" target="_blank" rel="noopener" style="font-size:11px;color:var(--color-primary);text-decoration:none">${escapeHtml(shortUrl)} →</a></div>`;
    }

    // ★ Derived expansion: show formula + parent fact references
    if (derivInfo) {
      html += '<div class="prov-card-section-title">派生计算</div>';
      html += `<div class="prov-card-row"><span class="prov-card-label">公式</span><span class="prov-card-row-val" style="font-family:var(--font-family-mono);font-size:11px">${escapeHtml(derivInfo.formula_display)}</span></div>`;
      html += `<div class="prov-card-row"><span class="prov-card-label">结果</span><span class="prov-card-row-val">${escapeHtml(derivInfo.result_display_hint || derivInfo.computed_value)}</span></div>`;
      if (derivInfo.parent_ids && derivInfo.parent_ids.length > 0) {
        let parentCells = "";
        for (const pid of derivInfo.parent_ids) {
          const pf = _provFacts[pid];
          const pcal = pf ? (pf.caliber || pid) : pid;
          parentCells += `<span class="prov-deriv-parent-chip" data-fact-id="${escapeHtml(pid)}" title="点击查看父数据">${escapeHtml(pcal)}</span>`;
        }
        html += `<div class="prov-card-row"><span class="prov-card-label">依赖</span><span class="prov-card-row-val">${parentCells}</span></div>`;
      }
      if (derivInfo.result_display_hint) {
        html += `<div class="prov-card-row"><span class="prov-card-label">提示</span><span class="prov-card-row-val" style="color:var(--brand-500);font-size:11px">${escapeHtml(derivInfo.result_display_hint)}</span></div>`;
      }
    }

    html += '</div>';
    return html;
  }

  /** The single shared popover element, lazily created. */
  let _provPopover = null;
  let _provPopoverTimer = null;

  function _getPopover() {
    if (!_provPopover) {
      _provPopover = document.createElement("div");
      _provPopover.className = "prov-card-popover";
      _provPopover.addEventListener("mouseenter", () => {
        clearTimeout(_provPopoverTimer);
      });
      _provPopover.addEventListener("mouseleave", () => {
        hideProvCard();
      });
      document.body.appendChild(_provPopover);

      // ★ Close a pinned popover when clicking anywhere outside of it
      document.addEventListener("click", (e) => {
        if (_provPopover && _provPopover.classList.contains("is-pinned") && !_provPopover.contains(e.target)) {
          _closePinnedPopover();
        }
      });
      // ★ Esc closes a pinned popover
      document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && _provPopover && _provPopover.classList.contains("is-pinned")) {
          _closePinnedPopover();
        }
      });
    }
    return _provPopover;
  }

  function showProvCard(factData, anchorEl, pinned) {
    clearTimeout(_provPopoverTimer);
    const popover = _getPopover();

    // ★ Hover preview is suppressed while any popover is pinned
    if (!pinned && popover.classList.contains("is-pinned")) {
      return;
    }
    // ★ Click pins: unpin a previously pinned popover first (only one at a time)
    if (pinned) {
      popover.classList.remove("is-pinned");
    }

    popover.innerHTML = _buildProvCardHTML(factData);

    if (pinned) {
      popover.classList.add("is-pinned");
      // ★ Add ✕ close button to the header (top-right)
      const header = popover.querySelector(".prov-card-header");
      if (header) {
        const closeBtn = document.createElement("button");
        closeBtn.type = "button";
        closeBtn.className = "prov-card-close";
        closeBtn.setAttribute("aria-label", "关闭");
        closeBtn.textContent = "✕";
        closeBtn.style.cssText = "margin-left:auto;background:transparent;border:none;color:var(--text-tertiary);font-size:13px;line-height:1;cursor:pointer;padding:0 2px;border-radius:4px";
        closeBtn.addEventListener("mouseenter", () => { closeBtn.style.color = "var(--text-default)"; });
        closeBtn.addEventListener("mouseleave", () => { closeBtn.style.color = "var(--text-tertiary)"; });
        closeBtn.addEventListener("click", (ev) => {
          ev.stopPropagation();
          _closePinnedPopover();
        });
        header.appendChild(closeBtn);
      }
    }

    const tier = factData.source_tier || "";
    const audited = factData.audited;
    // ★ Visual tier is driven by TRACE STATUS, not audit status:
    //   traced data → primary/secondary (green/yellow based on source quality)
    //   derived → derived (blue)
    //   verified_citation → citation (yellow)
    //   untraced → untraced (red) — only this one should be red
    if (factData.kind === "untraced") {
      popover.dataset.tier = "untraced";
    } else if (factData.kind === "derived") {
      popover.dataset.tier = "derived";
    } else if (factData.kind === "verified_citation") {
      popover.dataset.tier = "secondary";
    } else if (tier === "secondary") {
      popover.dataset.tier = "secondary";
    } else {
      // ★ Traced data gets primary (green) regardless of audit status
      // Audit status is shown as a row inside the card, not as the border color
      popover.dataset.tier = tier || "primary";
    }

    // Position the popover near the anchor
    const rect = anchorEl.getBoundingClientRect();
    const popW = 340;
    let left = rect.left + rect.width / 2 - popW / 2;
    let top = rect.bottom + 6;

    // Keep within viewport
    if (left < 12) left = 12;
    if (left + popW > window.innerWidth - 12) left = window.innerWidth - popW - 12;
    if (top + 300 > window.innerHeight) top = rect.top - 310; // flip above

    popover.style.left = left + "px";
    popover.style.top = top + "px";
    popover.classList.add("is-open");
  }

  function hideProvCard() {
    // ★ Pinned popovers stay open on mouseleave
    if (_provPopover && _provPopover.classList.contains("is-pinned")) {
      return;
    }
    _provPopoverTimer = setTimeout(() => {
      if (_provPopover) {
        _provPopover.classList.remove("is-open");
      }
    }, 150);
  }

  /** Force-close the currently pinned popover (✕ / outside click / Esc). */
  function _closePinnedPopover() {
    if (_provPopover) {
      _provPopover.classList.remove("is-pinned", "is-open");
    }
  }

  function applyProvenanceToShell(shell, provData) {
    /** Post-process the assistant message DOM with provenance annotations. */
    _provFacts = provData.facts || {};
    _provTraced = provData.traced_numbers || [];
    _provUntraced = provData.untraced_numbers || [];
    // Merge institutional out_of_coverage + all_tools_failed
    _provOutOfCoverage = Object.assign({}, provData.out_of_coverage || {}, provData.all_tools_failed || {});
    // Build derivation lookup map: fact_id → {formula_display, parent_ids, ...}
    _provDerivations = {};
    (provData.derivations || []).forEach(d => { _provDerivations[d.fact_id] = d; });

    // ★ Merge citation_sentence from traced_numbers into facts dict
    // so the provenance card can display the original matching sentence
    (_provTraced || []).forEach(tn => {
      if (tn.citation_sentence && tn.fact_id && _provFacts[tn.fact_id]) {
        _provFacts[tn.fact_id].citation_sentence = tn.citation_sentence;
      }
    });

    console.info("[prov]", "traced:", _provTraced.length, "untraced:", _provUntraced.length, "facts:", Object.keys(_provFacts).length);
    if (_provTraced.length === 0 && _provUntraced.length === 0) {
      console.warn("[prov] no numbers in provenance data — agent may have used text-only tools (RAG)");
    }

    const container = shell.content;
    if (!container) return;

    // ── Step 1: Inject ⓘ icons for traced numbers ──
    if (_provTraced.length > 0) {
      _injectTracedIcons(container);
    }

    // ── Step 2: Inject ⚠️ markers for untraced numbers ──
    if (_provUntraced.length > 0) {
      _injectUntracedMarkers(container);
    }

    // ── Step 3: Render unavailable data cards ──
    const oocTickers = Object.keys(_provOutOfCoverage);
    if (oocTickers.length > 0) {
      _renderUnavailableCard(shell);
    }

    // ── Step 4: Render provenance summary bar ──
    _renderSummaryBar(shell, provData);

    // Scroll to see the new annotations
    const thread = document.querySelector(".chat-thread");
    if (thread) thread.scrollTop = thread.scrollHeight;
  }

  function _injectTracedIcons(container) {
    /** Walk text nodes, find traced numbers by raw string, wrap with ⓘ icon. */
    const rawToFactIds = {};
    for (const tn of _provTraced) {
      if (!rawToFactIds[tn.raw]) rawToFactIds[tn.raw] = [];
      rawToFactIds[tn.raw].push(tn.fact_id);
    }

    const rawStrings = Object.keys(rawToFactIds).sort((a, b) => b.length - a.length);

    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    /** Generate search variants for a raw string to handle formatting differences.
     *  e.g. "547.03亿" → also try "547.03 亿", "547.03 亿 CNY"
     *       "$13.64B" → also try "13.64B"
     */
    function _variants(raw) {
      const v = [raw];
      // Currency prefixes
      const noCur = raw.replace(/^[¥￥$]/, "");
      if (noCur !== raw) v.push(noCur);
      // Space before Chinese unit (亿, 万, 元)
      const withSpace = raw.replace(/(\d)([亿万])/g, "$1 $2");
      if (withSpace !== raw) v.push(withSpace);
      // Space + CNY/USD suffix (common in tables)
      const noCurSpace = noCur.replace(/(\d)([亿万])/g, "$1 $2");
      for (const suffix of [" CNY", " USD", " RMB"]) {
        if (!raw.endsWith(suffix) && !noCurSpace.endsWith(suffix)) {
          v.push(noCurSpace + suffix);
        }
      }
      // Also try without trailing currency suffix
      for (const suffix of [" CNY", " USD", " RMB"]) {
        if (raw.endsWith(suffix)) v.push(raw.slice(0, -suffix.length));
      }
      // Deduplicate
      return [...new Set(v)];
    }

    let injected = 0;
    for (const raw of rawStrings) {
      const factIds = rawToFactIds[raw];
      if (!factIds.length) continue;
      const variants = _variants(raw);
      let found = false;

      for (let ni = 0; ni < textNodes.length; ni++) {
        const node = textNodes[ni];
        if (!node.parentNode) continue;

        const text = node.textContent;
        let idx = -1;
        let matchedVariant = raw;
        for (const variant of variants) {
          idx = text.indexOf(variant);
          if (idx !== -1) { matchedVariant = variant; break; }
        }
        if (idx === -1) continue;

        found = true;
        injected++;

        const parent = node.parentNode;
        const before = document.createTextNode(text.slice(0, idx));
        const after = document.createTextNode(text.slice(idx + matchedVariant.length));

        const span = document.createElement("span");
        span.className = "prov-traced";
        span.dataset.factIds = factIds.join(",");
        span.textContent = matchedVariant;

        const primaryFactId = factIds[0];
        const fact = _provFacts[primaryFactId];
        if (fact) {
          span.addEventListener("mouseenter", () => showProvCard(fact, span));
          span.addEventListener("mouseleave", () => hideProvCard());
          span.addEventListener("click", (e) => {
            e.stopPropagation();
            showProvCard(fact, span, true);
          });
        }

        parent.insertBefore(before, node);
        parent.insertBefore(span, node);
        parent.insertBefore(after, node);
        parent.removeChild(node);

        textNodes.splice(ni, 1, before, after);
        ni++;
        // Don't break — wrap ALL occurrences, not just the first
      }
      if (!found) {
        // silently skip — variant matching should catch most formatting differences
      }
    }
  }

  function _injectUntracedMarkers(container) {
    /** Walk text nodes, find untraced numbers by raw string, add ⚠️ marker. */
    const rawSet = new Set(_provUntraced.map(u => u.raw));
    const rawStrings = [...rawSet].sort((a, b) => b.length - a.length);

    const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
    const textNodes = [];
    while (walker.nextNode()) textNodes.push(walker.currentNode);

    for (const raw of rawStrings) {
      for (let ni = 0; ni < textNodes.length; ni++) {
        const node = textNodes[ni];
        if (!node.parentNode) continue;

        const text = node.textContent;
        const idx = text.indexOf(raw);
        if (idx === -1) continue;

        // Skip if already wrapped in a .prov-traced span
        if (node.parentNode && node.parentNode.classList && node.parentNode.classList.contains("prov-traced")) {
          continue;
        }

        const parent = node.parentNode;
        const before = document.createTextNode(text.slice(0, idx));
        const after = document.createTextNode(text.slice(idx + raw.length));

        const span = document.createElement("span");
        span.className = "prov-untraced";
        span.textContent = raw;
        span.title = "未溯源 — 该数字未在工具返回中找到可靠来源";

        // Hover to show a minimal popover
        const untracedInfo = {
          display: raw,
          source: "未溯源",
          source_tier: "",
          audited: null,
          caliber: "该数字未在工具返回中找到可靠来源",
          kind: "untraced",
        };
        span.addEventListener("mouseenter", () => showProvCard(untracedInfo, span));
        span.addEventListener("mouseleave", () => hideProvCard());

        parent.insertBefore(before, node);
        parent.insertBefore(span, node);
        parent.insertBefore(after, node);
        parent.removeChild(node);

        textNodes.splice(ni, 1, before, after);
        ni++;
        break;
      }
    }
  }

  function _renderUnavailableCard(shell) {
    /** Render "数据不可得" cards for out-of-coverage tickers. */
    const ooc = _provOutOfCoverage;
    if (!ooc || !Object.keys(ooc).length) return;

    // Remove any existing unavailable card
    const existing = shell.root.querySelector(".prov-unavailable-card");
    if (existing) existing.remove();

    const card = document.createElement("div");
    card.className = "prov-unavailable-card";

    let html = '<div class="prov-unavailable-header">📋 数据覆盖范围说明</div>';
    for (const [ticker, reason] of Object.entries(ooc)) {
      let reasonHTML;
      if (reason === "all_structured_tools_failed") {
        reasonHTML = "所有结构化数据源均失败 — 以下数字基于外网搜索，<strong>未经结构化验证</strong>";
      } else {
        reasonHTML = escapeHtml(reason);
      }
      html += `<div class="prov-unavailable-reason"><strong>${escapeHtml(ticker)}</strong>: ${reasonHTML}</div>`;
    }
    html += '<div class="prov-unavailable-hint">本系统不做推算、不编造数据。诚实标注数据边界比填补缺口更有价值。</div>';

    card.innerHTML = html;
    shell.root.appendChild(card);
  }

  function _renderSummaryBar(shell, provData) {
    /** Render a compact provenance coverage bar below the assistant message. */
    const container = shell.root;

    // Remove existing summary bar
    const existing = container.querySelector(".prov-summary-bar");
    if (existing) existing.remove();

    const traced = _provTraced.length;
    const untraced = _provUntraced.length;
    const derived = provData.derived_traced || 0;
    const totalTraced = traced + derived;
    const total = totalTraced + untraced;
    if (total === 0) return;

    const covPct = total > 0 ? Math.round((totalTraced / total) * 100) : 100;

    const bar = document.createElement("div");
    bar.className = "prov-summary-bar";

    let dots = "";
    if (traced > 0) dots += `<span class="prov-summary-dot prov-summary-dot-traced"></span> ${traced} 已溯源`;
    if (derived > 0) dots += `<span class="prov-summary-dot prov-summary-dot-derived"></span> ${derived} 派生`;
    if (untraced > 0) dots += `<span class="prov-summary-dot prov-summary-dot-untraced"></span> ${untraced} 未溯源`;
    dots += ` · 覆盖率 ${covPct}%`;

    bar.innerHTML = dots;
    container.appendChild(bar);
  }

  // ───────────────────────────────────────────────────────────────
  // Wire up the input bar
  // ───────────────────────────────────────────────────────────────

  function setSendButtonState(disabled) {
    const btn = document.querySelector(".chat-input-bar .ds-btn-primary");
    if (!btn) return;
    btn.disabled = disabled;
    btn.style.opacity = disabled ? "0.6" : "";
    btn.style.cursor = disabled ? "not-allowed" : "";
  }

  function wireInput() {
    const textarea = document.querySelector(".chat-input");
    const sendBtn = document.querySelector(".chat-input-bar .ds-btn-primary");
    if (!textarea || !sendBtn) {
      console.warn("chat.js: input or send button not found");
      return;
    }

    // Enter to send, Shift+Enter for newline
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const text = textarea.value;
        if (text.trim()) {
          textarea.value = "";
          sendMessage(text);
        }
      }
    });

    sendBtn.addEventListener("click", () => {
      const text = textarea.value;
      if (text.trim()) {
        textarea.value = "";
        sendMessage(text);
      }
    });
  }

  // ───────────────────────────────────────────────────────────────
  // "新建" button — start a fresh conversation thread
  // ───────────────────────────────────────────────────────────────

  function startNewConversation() {
    // Generate a fresh conversation ID every time "新建" is clicked.
    // This ensures the next message goes to a new thread, not appended
    // to the current conversation.
    CONVERSATION_ID = generateConvId();

    // Clear the chat thread
    const thread = document.querySelector(".chat-thread");
    if (thread) thread.innerHTML = "";

    // Clear the input
    const input = document.querySelector(".chat-input");
    if (input) input.value = "";

    // Reset active state — highlight nothing until user sends a message
    document.querySelectorAll(".chat-conv-item").forEach(item => {
      item.classList.toggle("is-active", false);
    });

    // Reload conversation list to include the new one after first message
    // (don't reload now — will happen naturally when user sends a message)
    console.info("[chat.js] New conversation started:", CONVERSATION_ID);
  }

  function wireNewConversation() {
    // Find the "新建" button inside the chat-left header
    const buttons = document.querySelectorAll(".chat-left-header button");
    buttons.forEach((btn) => {
      if (btn.textContent && btn.textContent.includes("新建")) {
        btn.addEventListener("click", startNewConversation);
      }
    });
  }

  // ───────────────────────────────────────────────────────────────
  // Sidebar navigation is handled by shell.js (shared across all pages).
  // ───────────────────────────────────────────────────────────────

  // ───────────────────────────────────────────────────────────────
  // Sidebar: load conversation list from backend + allow click-to-load
  // ───────────────────────────────────────────────────────────────

  let _loadingConversations = false;

  async function loadConversationList() {
    /** Fetch /api/v1/conversations and render into .chat-conv-list */
    const convList = document.querySelector(".chat-conv-list");
    if (!convList) return;

    // Prevent concurrent executions — if already loading, skip
    if (_loadingConversations) {
      console.debug("[chat.js] loadConversationList: already in progress, skipping");
      return;
    }
    _loadingConversations = true;

    try {
      const resp = await Auth.fetch(`${API_BASE}/api/v1/conversations?limit=30`, {});
      if (!resp.ok) {
        const errText = await resp.text().catch(() => "");
        console.warn("[chat.js] list conversations failed:", resp.status, errText.slice(0, 200));
        _ensureCurrentConvInList(convList);
        return;
      }
      const data = await resp.json();
      console.info("[chat.js] loaded", data.total, "conversations for principal", data.principal_id, "active:", CONVERSATION_ID);
      convList.innerHTML = "";

      // Diagnostic: if API returned 0 but we expected conversations (DB has data),
      // show a subtle indicator in the sidebar so users aren't confused
      if (data.total === 0) {
        console.warn("[chat.js] API returned 0 conversations — possible principal_id mismatch. Token principal:", data.principal_id);
        const hint = el("div", "chat-conv-item");
        hint.style.opacity = "0.5";
        hint.style.cursor = "default";
        hint.appendChild(el("span", "chat-conv-title", "暂无历史会话"));
        const meta = el("div", "chat-conv-meta");
        meta.appendChild(el("span", "chat-conv-date", "登录身份变更可能导致会话不可见"));
        hint.appendChild(meta);
        convList.appendChild(hint);
      }

      // Track if current conv is in the results
      let hasCurrentConv = false;

      data.conversations.forEach((c) => {
        const item = el("div", "chat-conv-item");
        item.setAttribute("data-conv-id", c.conversation_id);
        if (c.conversation_id === CONVERSATION_ID) {
          item.classList.add("is-active");
          hasCurrentConv = true;
        }
        const title = el("span", "chat-conv-title", c.first_user_message || c.last_user_message || "(空对话)");
        item.appendChild(title);
        const meta = el("div", "chat-conv-meta");
        // Format last_activity_at (ISO string → HH:MM or YYYY-MM-DD)
        let dateLabel = "";
        if (c.last_activity_at) {
          try {
            const d = new Date(c.last_activity_at);
            const today = new Date();
            if (d.toDateString() === today.toDateString()) {
              dateLabel = d.toLocaleTimeString().slice(0, 5);
            } else {
              dateLabel = d.toISOString().slice(0, 10);
            }
          } catch {
            dateLabel = c.last_activity_at.slice(0, 10);
          }
        }
        meta.appendChild(el("span", "chat-conv-date", dateLabel));
        if (c.event_count) {
          meta.appendChild(el("span", "ds-tag", `${c.event_count} evt`));
        }
        item.appendChild(meta);
        // Click → switch conversation (★ force re-render if thread is empty)
        item.addEventListener("click", () => {
          const thread = document.querySelector(".chat-thread");
          const isEmpty = !thread || !thread.children.length;
          switchConversation(c.conversation_id, isEmpty);
        });
        convList.appendChild(item);
      });

      // ★ Always show the current conversation, even if it's new (not yet in API)
      if (!hasCurrentConv) {
        _ensureCurrentConvInList(convList);
      }
    } catch (err) {
      console.warn("[chat.js] loadConversationList error:", err);
      _ensureCurrentConvInList(convList);
    } finally {
      _loadingConversations = false;
    }
  }

  function _ensureCurrentConvInList(convList) {
    /** Add the current conversation to the list if not already present. */
    const existing = convList.querySelector(`[data-conv-id="${CONVERSATION_ID}"]`);
    if (existing) return;

    const convId = CONVERSATION_ID;
    const item = el("div", "chat-conv-item is-active");
    item.setAttribute("data-conv-id", convId);
    item.appendChild(el("span", "chat-conv-title", "新对话"));
    const meta = el("div", "chat-conv-meta");
    meta.appendChild(el("span", "chat-conv-date", new Date().toLocaleTimeString().slice(0, 5)));
    item.appendChild(meta);
    item.addEventListener("click", () => switchConversation(convId));
    convList.insertBefore(item, convList.firstChild);
  }

  function _updateSidebarTitle(text) {
    /** Set sidebar title on first message only — never overwrite an existing title. */
    const convList = document.querySelector(".chat-conv-list");
    if (!convList) return;
    const item = convList.querySelector(`[data-conv-id="${CONVERSATION_ID}"]`);
    if (!item) return;
    const titleSpan = item.querySelector(".chat-conv-title");
    if (!titleSpan) return;
    // Only update if title is still the default placeholder
    if (titleSpan.textContent !== "新对话") return;
    const maxLen = 30;
    const trimmed = text.trim();
    titleSpan.textContent = trimmed.length > maxLen ? trimmed.slice(0, maxLen - 1) + "…" : trimmed;
  }

  async function switchConversation(convId, force) {
    /** Switch to an existing conversation: update state, load events, render */
    // ★ Allow re-rendering the same conversation (force=true) for when DOM
    // was cleared by another conversation's SSE stream disconnecting.
    if (convId === CONVERSATION_ID && !force) return;
    // ★ Stop polling the previous conversation
    _stopConvPolling();
    CONVERSATION_ID = convId;
    // Update sidebar active state
    document.querySelectorAll(".chat-conv-item").forEach((item) => {
      const id = item.getAttribute("data-conv-id");
      item.classList.toggle("is-active", id === convId);
    });
    // Clear chat thread
    const thread = document.querySelector(".chat-thread");
    if (thread) thread.innerHTML = "";
    // Load events
    try {
      const resp = await Auth.fetch(`${API_BASE}/api/v1/conversations/${convId}/events`, {});
      if (!resp.ok) {
        console.warn("load events failed:", resp.status);
        return;
      }
      const data = await resp.json();
      // Render each event by type — including tool calls for full traceability
      let lastAssistantShell = null;
      let partialAnswer = ""; // ★ Accumulate assistant_delta for in-progress streams
      const TOOL_TYPES = ["run.tool_requested", "run.tool_completed", "run.tool_failed", "message.assistant_tool_calls_added"];
      for (const evt of data.events) {
        if (evt.type === "message.user_added" && evt.content) {
          renderUserMessage(evt.content);
          partialAnswer = ""; // Reset for new turn
        } else if (evt.type === "message.assistant_delta" && evt.content) {
          // ★ Accumulate partial answer during streaming
          partialAnswer += evt.content;
          if (!lastAssistantShell) lastAssistantShell = renderAssistantShell();
          if (lastAssistantShell) lastAssistantShell.content.innerHTML = renderMarkdownLite(partialAnswer) + '<span class="cursor-blink">▎</span>';
        } else if (evt.type === "message.assistant_added" && evt.content) {
          // Reuse existing shell if created by tool events, otherwise create new
          if (!lastAssistantShell) lastAssistantShell = renderAssistantShell();
          if (lastAssistantShell) lastAssistantShell.content.innerHTML = renderMarkdownLite(evt.content);
          partialAnswer = evt.content; // Track in case more events follow
        } else if (TOOL_TYPES.includes(evt.type)) {
          // Create assistant shell lazily when first tool event appears
          // (tool events come BEFORE the final answer in the event stream)
          if (!lastAssistantShell) lastAssistantShell = renderAssistantShell();
          if (!lastAssistantShell) continue;
          // Reconstruct payload for renderReactStep from stored event data
          const ed = evt.data || {};
          let payload;
          if (evt.type === "message.assistant_tool_calls_added") {
            const tc = (ed.tool_calls || [])[0] || {};
            payload = { phase: "tool_plan", tool_name: tc.name || "", tool_input_preview: JSON.stringify(tc.arguments || {}).slice(0, 220), tool_status: "running" };
          } else if (evt.type === "run.tool_requested") {
            payload = { phase: "tool_call", tool_name: ed.name || "", tool_input_preview: JSON.stringify(ed.arguments || {}).slice(0, 220), tool_status: "running" };
          } else if (evt.type === "run.tool_completed") {
            payload = { phase: "tool_result", tool_name: ed.name || "", tool_output_preview: JSON.stringify(ed.result || "").slice(0, 220), tool_status: ed.status || "ok" };
          } else {
            payload = { phase: "tool_result", tool_name: ed.name || "", tool_message: ed.message || "failed", tool_status: "error" };
          }
          if (lastAssistantShell.stepsEl) renderReactStep(lastAssistantShell.stepsEl, payload);
        } else if (evt.type === "run.provenance" && evt.data && lastAssistantShell) {
          // Apply provenance to the most recent assistant message
          applyProvenanceToShell(lastAssistantShell, evt.data);
        }
      }
      console.info(`[chat.js] loaded ${data.total} events for conv ${convId}`);

      // ★ Check if run is still in progress — if so, poll for new events
      const lastEvt = data.events[data.events.length - 1];
      const isRunning = lastEvt && lastEvt.type !== "run.completed" && lastEvt.type !== "run.failed";
      if (isRunning) {
        _startConvPolling(convId, data.events.length);
      }
    } catch (err) {
      console.error("switchConversation error:", err);
    }
  }

  // ★ Conversation polling — re-fetch new events periodically until run completes
  let _convPollTimer = null;
  let _convPollConvId = null;

  function _stopConvPolling() {
    if (_convPollTimer) {
      clearTimeout(_convPollTimer);
      _convPollTimer = null;
    }
    _convPollConvId = null;
  }

  function _startConvPolling(convId, knownEventCount) {
    _stopConvPolling();
    _convPollConvId = convId;
    const poll = async () => {
      if (_convPollConvId !== convId || convId !== CONVERSATION_ID) {
        return; // User switched away
      }
      try {
        const resp = await Auth.fetch(`${API_BASE}/api/v1/conversations/${convId}/events`, {});
        if (!resp.ok) return;
        const data = await resp.json();
        // Only process new events
        const newEvents = data.events.slice(knownEventCount);
        if (newEvents.length > 0) {
          knownEventCount = data.events.length;
          // Render new events into the current thread
          const thread = document.querySelector(".chat-thread");
          if (thread) {
            // Find or create the last assistant shell
            let lastShell = _getLastAssistantShell();
            let pollPartial = "";
            const TOOL_TYPES = ["run.tool_requested", "run.tool_completed", "run.tool_failed", "message.assistant_tool_calls_added"];
            for (const evt of newEvents) {
              if (evt.type === "message.user_added" && evt.content) {
                renderUserMessage(evt.content);
                lastShell = null;
                pollPartial = "";
              } else if (evt.type === "message.assistant_delta" && evt.content) {
                pollPartial += evt.content;
                if (!lastShell) lastShell = renderAssistantShell();
                if (lastShell) lastShell.content.innerHTML = renderMarkdownLite(pollPartial) + '<span class="cursor-blink">▎</span>';
              } else if (evt.type === "message.assistant_added" && evt.content) {
                if (!lastShell) lastShell = renderAssistantShell();
                if (lastShell) lastShell.content.innerHTML = renderMarkdownLite(evt.content);
              } else if (TOOL_TYPES.includes(evt.type)) {
                if (!lastShell) lastShell = renderAssistantShell();
                if (!lastShell) continue;
                const ed = evt.data || {};
                let payload;
                if (evt.type === "message.assistant_tool_calls_added") {
                  const tc = (ed.tool_calls || [])[0] || {};
                  payload = { phase: "tool_plan", tool_name: tc.name || "", tool_input_preview: JSON.stringify(tc.arguments || {}).slice(0, 220), tool_status: "running" };
                } else if (evt.type === "run.tool_requested") {
                  payload = { phase: "tool_call", tool_name: ed.name || "", tool_input_preview: JSON.stringify(ed.arguments || {}).slice(0, 220), tool_status: "running" };
                } else if (evt.type === "run.tool_completed") {
                  payload = { phase: "tool_result", tool_name: ed.name || "", tool_output_preview: JSON.stringify(ed.result || "").slice(0, 220), tool_status: ed.status || "ok" };
                } else {
                  payload = { phase: "tool_result", tool_name: ed.name || "", tool_message: ed.message || "failed", tool_status: "error" };
                }
                if (lastShell.stepsEl) renderReactStep(lastShell.stepsEl, payload);
              } else if (evt.type === "run.provenance" && evt.data && lastShell) {
                applyProvenanceToShell(lastShell, evt.data);
              } else if (evt.type === "run.completed" || evt.type === "run.failed") {
                // Run finished — stop polling
                _stopConvPolling();
                return;
              }
            }
          }
          // Scroll to bottom
          const thread2 = document.querySelector(".chat-thread");
          if (thread2) thread2.scrollTop = thread2.scrollHeight;
        }
        // Check if run completed
        const lastEvt = data.events[data.events.length - 1];
        if (lastEvt && (lastEvt.type === "run.completed" || lastEvt.type === "run.failed")) {
          _stopConvPolling();
          return;
        }
      } catch (err) {
        console.warn("[chat.js] poll error:", err);
      }
      // Schedule next poll — ★ 800ms for near-native streaming feel
      _convPollTimer = setTimeout(poll, 800);
    };
    _convPollTimer = setTimeout(poll, 800);
  }

  function _getLastAssistantShell() {
    /** Find the last assistant message shell in the thread DOM. */
    const thread = document.querySelector(".chat-thread");
    if (!thread) return null;
    const msgs = thread.querySelectorAll(".chat-msg-ai");
    if (msgs.length === 0) return null;
    const last = msgs[msgs.length - 1];
    return {
      content: last.querySelector(".chat-msg-content"),
      stepsEl: last.querySelector(".react-steps"),
    };
  }

  // ───────────────────────────────────────────────────────────────
  // Data source status — refresh right panel from backend health checks
  // ───────────────────────────────────────────────────────────────

  async function refreshDataSources() {
    const card = document.getElementById("data-sources-card");
    if (!card) return;
    const body = card.querySelector(".data-sources-body");
    if (!body) return;

    try {
      const resp = await fetch(`${API_BASE}/api/v1/data-sources`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();

      // Clear old rows
      body.innerHTML = "";

      // Update timestamp
      const meta = card.querySelector(".ctx-card-meta");
      if (meta) {
        meta.textContent = new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      }

      // Display name mapping (adapter name → user-facing label)
      const DISPLAY_NAMES = {
        "edgar":                 "SEC EDGAR",
        "fin-skill":             "fin-skill MCP",
        "fred":                  "FRED",
        "yfinance":              "yfinance",
        "coinmetrics":           "Coin Metrics",
        "defillama":             "DeFi Llama",
        "binance_derivatives":   "Binance 衍生品",
        "fear_greed":            "恐贪指数",
        "akshare-stock":         "akshare (行情)",
        "akshare-futures":       "akshare (期货)",
        "akshare-financials":    "akshare (财报)",
      };

      for (const s of data.sources) {
        const row = el("div", "src-row");
        const name = el("span", "src-name");
        name.textContent = DISPLAY_NAMES[s.name] || s.name;
        row.appendChild(name);

        const state = el("span", "src-state");
        const dot = el("span", "src-dot");
        if (s.available) {
          dot.classList.add("is-ok");
          state.appendChild(dot);
          state.appendChild(document.createTextNode(" 在线"));
          if (s.latency_ms !== null) {
            const extra = el("span", "src-extra");
            extra.innerHTML = `<span class="t-metric">${s.latency_ms}</span>ms`;
            state.appendChild(extra);
          }
        } else {
          dot.classList.add("is-warn");
          state.classList.add("is-warn");
          state.appendChild(dot);
          state.appendChild(document.createTextNode(s.error ? ` ${s.error}` : " 离线"));
        }
        row.appendChild(state);
        body.appendChild(row);
      }
    } catch (err) {
      console.warn("refreshDataSources: API unavailable — keeping static content", err.message);
    }
  }

  // ───────────────────────────────────────────────────────────────
  // Boot
  // ───────────────────────────────────────────────────────────────

  async function boot() {
    // ★ Clear mock content IMMEDIATELY (sync, no await) so baked-in HTML
    // placeholder items don't flash during the async auth check below.
    clearMockContent();

    // Data source status — runs independently of auth (public endpoint)
    // ★ Must await before auth redirect, otherwise page navigation aborts fetch
    try { await refreshDataSources(); } catch(e) {}
    setInterval(refreshDataSources, 60000);

    // Require authentication — redirects to /login if no token
    const user = await Auth.requireUser();
    if (!user) return;  // redirecting, don't continue
    Auth.renderUserBadge(user);

    wireInput();
    wireNewConversation();
    // Load conversation history into the sidebar
    try {
      await loadConversationList();
    } catch (err) {
      console.warn("[chat.js] loadConversationList failed:", err);
    }

    // ★ Auto-submit pending query from welcome page
    const urlParams = new URLSearchParams(window.location.search);
    const pendingQ = urlParams.get("q") || sessionStorage.getItem("cagentos_pending_query");
    if (pendingQ) {
      sessionStorage.removeItem("cagentos_pending_query");
      // Clean URL
      if (window.history.replaceState) {
        window.history.replaceState({}, "", window.location.pathname);
      }
      const textarea = document.querySelector(".chat-input");
      if (textarea) {
        textarea.value = pendingQ;
        setTimeout(() => sendMessage(pendingQ), 500);
      }
    }

    console.info("[chat.js] wired up as user:", user.email, "conv:", CONVERSATION_ID);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
