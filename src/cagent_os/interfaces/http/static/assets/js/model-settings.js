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
        refreshModelSuggestions();
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

  providerSel.addEventListener("change", refreshModelSuggestions);

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
          refreshPicker(true);
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

  async function testKey() {
    testBtn.disabled = true;
    testBtn.textContent = "测试中…";
    setResult("");
    try {
      var response = await api("/api/v1/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: providerSel.value,
          api_key: keyInput.value.trim(),
          default_model: modelInput.value.trim() || null,
        }),
      });
      var data = await response.json();
      if (response.ok && data.ok) setResult("连接成功 ✓ " + data.model, true);
      else setResult("失败：" + (data.detail || "未知错误"), false);
    } catch {
      setResult("网络错误", false);
    } finally {
      testBtn.disabled = false;
      testBtn.textContent = "测试连接";
    }
  }

  function clearKey() {
    if (!confirm("确定清除已保存的 API Key？之后将使用平台默认模型。")) return;
    api("/api/v1/llm/settings", { method: "DELETE" })
      .then(function (response) {
        if (!response.ok) throw new Error();
        refreshPicker(false);
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
  var picker = document.getElementById("quickModelBadge");
  var preferenceKey;
  var tag = document.getElementById("activeModelTag");
  var names = {"deepseek-flash": "DeepSeek V4.1 Flash", "deepseek-v4-pro": "DeepSeek V4 Pro"};

  window.chatModelRequest = function () {
    var option = picker.selectedOptions[0];
    return {model_source: option.dataset.source || "platform", model: option.dataset.model || undefined};
  };

  function syncLabel() {
    tag.textContent = "Model: " + picker.selectedOptions[0].text;
  }

  function addGroup(title, source, models, provider) {
    var group = document.createElement("optgroup");
    group.label = title;
    models.forEach(function (model) {
      var option = new Option(names[model] || model, JSON.stringify([source, provider, model]));
      option.dataset.source = source;
      option.dataset.model = model;
      group.appendChild(option);
    });
    picker.appendChild(group);
  }

  var refreshVersion = 0;
  async function refreshPicker(usePersonal) {
    var version = ++refreshVersion;
    try {
      var response = await api("/api/v1/llm/models");
      if (!response.ok) throw new Error();
      var data = await response.json();
      if (version !== refreshVersion) return;
      preferenceKey = "cos_model_choice:" + data.user_id;
      var saved = localStorage.getItem(preferenceKey);
      picker.replaceChildren();
      addGroup("平台模型", "platform", data.platform_models, "");
      var provider = data.configured_provider;
      if (provider) {
        var models = new Set([data.user_default, ...(data.models_by_provider[provider] || [])]);
        addGroup("我的 Key · " + provider, "user", Array.from(models).filter(Boolean), provider);
      }
      // Migrate a saved personal model only if this account offers it.
      if (!saved && provider) {
        var legacy = localStorage.getItem("cos_active_model");
        var match = Array.from(picker.options).find(function (option) {
          return option.dataset.source === "user" && option.dataset.model === legacy;
        });
        if (match) saved = match.value;
      }
      var preferred = usePersonal && picker.querySelector('[data-source="user"]');
      picker.value = preferred ? preferred.value : saved || "";
      if (picker.selectedIndex < 0) picker.selectedIndex = 0;
      localStorage.setItem(preferenceKey, picker.value);
      syncLabel();
      picker.title = "选择对话模型";
    } catch {
      picker.title = "加载模型失败，点击重试";
      picker.onclick = function () { picker.onclick = null; refreshPicker(false); };
    }
  }

  picker.addEventListener("change", function () {
    if (preferenceKey) localStorage.setItem(preferenceKey, picker.value);
    syncLabel();
  });
  refreshPicker(false);
})();
