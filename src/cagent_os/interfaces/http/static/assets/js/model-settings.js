/**
 * model-settings.js — BYOK (bring your own key) model settings modal.
 *
 * Loaded by chat.html. Wires the sidebar "模型设置" button to a modal
 * that manages per-user LLM provider + API key + default model.
 *
 * API endpoints (see routes_llm_keys.py):
 *   GET    /api/v1/llm/settings
 *   PUT    /api/v1/llm/settings
 *   DELETE /api/v1/llm/settings
 *   POST   /api/v1/llm/test
 *   GET    /api/v1/llm/models
 */
(function () {
  "use strict";

  var backdrop = document.getElementById("modelModalBackdrop");
  if (!backdrop) return; // modal not on this page

  var openBtn = document.getElementById("openModelSettings");
  var closeBtn = document.getElementById("closeModelSettings");
  var providerSel = document.getElementById("llmProvider");
  var keyInput = document.getElementById("llmApiKey");
  var keyHint = document.getElementById("keyHint");
  var modelInput = document.getElementById("llmModel");
  var suggestions = document.getElementById("modelSuggestions");
  var testBtn = document.getElementById("testKeyBtn");
  var clearBtn = document.getElementById("clearKeyBtn");
  var saveBtn = document.getElementById("saveKeyBtn");
  var resultEl = document.getElementById("testResult");
  var btnLabel = document.getElementById("modelBtnLabel");

  // Auth-aware fetch (adds Bearer token, handles 401 redirect)
  var api = function (url, options) {
    if (window.Auth && window.Auth.fetch) return window.Auth.fetch(url, options);
    return fetch(url, options);
  };

  // ── helpers ──
  function setResult(text, ok) {
    resultEl.textContent = text || "";
    resultEl.className = "model-modal__result" + (ok ? " is-ok" : " is-err");
  }

  function open() {
    backdrop.hidden = false;
    setResult("");
    loadSettings();
    loadModels();
  }

  function close() {
    backdrop.hidden = true;
  }

  // ── data loading ──
  function loadSettings() {
    api("/api/v1/llm/settings")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.configured) {
          providerSel.value = data.provider;
          modelInput.value = data.default_model || "";
          keyHint.textContent = "已保存 Key：" + data.api_key_masked + "（留空保持不变）";
          keyInput.value = "";
          btnLabel.textContent = "自定义模型";
          openBtn.classList.add("is-custom");
        } else {
          keyHint.textContent = "";
          btnLabel.textContent = "模型设置";
          openBtn.classList.remove("is-custom");
        }
      })
      .catch(function () {
        setResult("加载设置失败", false);
      });
  }

  function refreshModelSuggestions() {
    api("/api/v1/llm/models")
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var models = (data.models_by_provider || {})[providerSel.value] || [];
        suggestions.innerHTML = models
          .map(function (m) { return '<option value="' + m + '">'; })
          .join("");
      })
      .catch(function () { /* non-fatal */ });
  }

  function loadModels() {
    refreshModelSuggestions();
    providerSel.addEventListener("change", refreshModelSuggestions);
  }

  // ── actions ──
  function save() {
    var key = keyInput.value.trim();
    var provider = providerSel.value;
    var model = modelInput.value.trim() || null;

    if (!key && !keyHint.textContent) {
      setResult("请输入 API Key", false);
      return;
    }

    saveBtn.disabled = true;
    saveBtn.textContent = "保存中…";

    api("/api/v1/llm/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: provider, api_key: key, default_model: model }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
      .then(function (res) {
        if (res.ok) {
          setResult("已保存 ✓", true);
          loadSettings(); // refresh masked hint + sidebar label
          setTimeout(close, 800);
        } else {
          setResult(res.data.detail || "保存失败", false);
        }
      })
      .catch(function () { setResult("网络错误", false); })
      .finally(function () {
        saveBtn.disabled = false;
        saveBtn.textContent = "保存";
      });
  }

  function testKey() {
    testBtn.disabled = true;
    testBtn.textContent = "测试中…";
    setResult("");

    var runTest = function () {
      api("/api/v1/llm/test", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.ok) setResult("连接成功 ✓ " + (d.model || ""), true);
          else setResult("失败：" + (d.detail || "未知错误"), false);
        })
        .catch(function () { setResult("网络错误", false); })
        .finally(function () {
          testBtn.disabled = false;
          testBtn.textContent = "测试连接";
        });
    };

    // If user typed a new key, save it first so the test uses it
    var key = keyInput.value.trim();
    if (key) {
      api("/api/v1/llm/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: providerSel.value,
          api_key: key,
          default_model: modelInput.value.trim() || null,
        }),
      })
        .then(function () { keyInput.value = ""; runTest(); })
        .catch(runTest);
    } else {
      runTest();
    }
  }

  function clearKey() {
    if (!confirm("确定清除已保存的 API Key？之后将使用平台默认模型。")) return;
    api("/api/v1/llm/settings", { method: "DELETE" })
      .then(function () {
        setResult("已清除，回落平台模型", true);
        keyInput.value = "";
        keyHint.textContent = "";
        modelInput.value = "";
        btnLabel.textContent = "模型设置";
        openBtn.classList.remove("is-custom");
      })
      .catch(function () { setResult("网络错误", false); });
  }

  // ── wire events ──
  openBtn.addEventListener("click", open);
  closeBtn.addEventListener("click", close);
  backdrop.addEventListener("click", function (e) {
    if (e.target === backdrop) close();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !backdrop.hidden) close();
  });
  saveBtn.addEventListener("click", save);
  testBtn.addEventListener("click", testKey);
  clearBtn.addEventListener("click", clearKey);

  // ============================================================
  // Quick model switcher (badge next to chat input)
  // ============================================================
  var badge = document.getElementById("quickModelBadge");
  var popover = document.getElementById("quickModelPopover");
  var customList = document.getElementById("quickModelCustomList");
  var customEmpty = document.getElementById("quickModelCustomEmpty");
  var cfgBtn = document.getElementById("quickModelOpenSettings");

  if (badge && popover) {
    var currentModel = localStorage.getItem("cos_active_model") || "";

    function badgeText() {
      return currentModel ? currentModel.split("/").pop() + " ▾" : "DeepSeek V4 Pro ▾";
    }

    function refreshBadge() {
      badge.textContent = badgeText();
      badge.classList.toggle("is-custom", !!currentModel);
    }

    function closePopover() { popover.hidden = true; }

    function loadQuickModels() {
      Promise.all([
        api("/api/v1/llm/settings").then(function (r) { return r.json(); }),
        api("/api/v1/llm/models").then(function (r) { return r.json(); }),
      ]).then(function (res) {
        var settings = res[0], models = res[1];
        var items = "";
        if (settings.configured) {
          var models2 = (models.models_by_provider || {})[settings.provider] || [];
          models2.forEach(function (m) {
            var active = m === currentModel ? " is-active" : "";
            items += '<button class="model-popover__item' + active + '" data-model="' + m + '">' + m + '</button>';
          });
        }
        if (items) {
          customList.innerHTML = items;
          customEmpty.hidden = true;
          // wire clicks
          customList.querySelectorAll(".model-popover__item").forEach(function (b) {
            b.addEventListener("click", function () {
              currentModel = b.getAttribute("data-model");
              localStorage.setItem("cos_active_model", currentModel);
              refreshBadge();
              closePopover();
            });
          });
        } else {
          customList.innerHTML = "";
          customEmpty.hidden = false;
        }
        // mark platform default active state
        var defBtn = popover.querySelector('[data-model=""]');
        if (defBtn) defBtn.classList.toggle("is-active", !currentModel);
      }).catch(function () { /* non-fatal */ });
    }

    badge.addEventListener("click", function (e) {
      e.stopPropagation();
      popover.hidden = !popover.hidden;
      if (!popover.hidden) loadQuickModels();
    });
    badge.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        badge.click();
      }
    });
    document.addEventListener("click", function (e) {
      if (!popover.hidden && !popover.contains(e.target) && e.target !== badge) closePopover();
    });

    // platform default
    var defBtn = popover.querySelector('[data-model=""]');
    if (defBtn) {
      defBtn.addEventListener("click", function () {
        currentModel = "";
        localStorage.removeItem("cos_active_model");
        refreshBadge();
        closePopover();
      });
    }
    if (cfgBtn) {
      cfgBtn.addEventListener("click", function () {
        closePopover();
        open();
      });
    }

    refreshBadge();
  }
})();
