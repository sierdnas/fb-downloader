const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const TYPE_ICONS = { video: "icon-video", photo: "icon-photo", reel: "icon-reel" };
const TYPE_KEYS = { video: "type_video", photo: "type_photo", reel: "type_reel" };
const STATUS_ICONS = {
  done: "icon-check",
  error: "icon-error",
  downloading: "icon-history",
  queued: "icon-history",
  pending: "icon-history",
  skipped_duplicate: "icon-info",
};
const STATUS_KEYS = {
  done: "status_done",
  error: "status_error",
  downloading: "status_downloading",
  queued: "status_queued",
  pending: "status_pending",
  skipped_duplicate: "status_skipped_duplicate",
};

function typeBadge(mediaType) {
  const icon = TYPE_ICONS[mediaType] || "icon-video";
  const label = t(TYPE_KEYS[mediaType] || "type_video");
  return `<span class="badge ${mediaType}"><svg class="icon"><use href="#${icon}"/></svg>${label}</span>`;
}

function statusLabel(status) {
  const icon = STATUS_ICONS[status] || "icon-info";
  const label = t(STATUS_KEYS[status] || status);
  return `<span class="status ${status}"><svg class="icon"><use href="#${icon}"/></svg>${label}</span>`;
}

// ---------- Tabs ----------
function switchTab(tabName) {
  $$("nav button").forEach((b) => b.classList.remove("active"));
  $$(".tab-content").forEach((t) => t.classList.remove("active"));
  const navBtn = $(`nav button[data-tab="${tabName}"]`);
  if (navBtn) navBtn.classList.add("active");
  const panel = $(`#tab-${tabName}`);
  if (panel) panel.classList.add("active");

  if (tabName === "history") { loadHistory(); loadSources(); }
  if (tabName === "settings") loadSettings();
  if (tabName === "login") loadLoginStatus();
  if (tabName === "logs") { loadLogs(); startLogsPolling(); } else { stopLogsPolling(); }

  closeMobileMenu();
}

$$("nav button").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

// ---------- Logo: click returns to the Download tab ----------
$("#brand-logo").addEventListener("click", () => switchTab("download"));

// ---------- Mobile menu (hamburger) ----------
function closeMobileMenu() {
  $("#main-nav").classList.remove("open");
}

$("#btn-mobile-menu").addEventListener("click", (e) => {
  e.stopPropagation();
  $("#main-nav").classList.toggle("open");
});

// closes the mobile menu when clicking outside of it
document.addEventListener("click", (e) => {
  const nav = $("#main-nav");
  const menuBtn = $("#btn-mobile-menu");
  if (nav.classList.contains("open") && !nav.contains(e.target) && e.target !== menuBtn && !menuBtn.contains(e.target)) {
    closeMobileMenu();
  }
});

// ---------- Type filter chips ----------
let selectedTypes = new Set(["video", "photo", "reel"]);
$$("#type-filter .chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    chip.classList.toggle("selected");
    const ty = chip.dataset.type;
    chip.classList.contains("selected") ? selectedTypes.add(ty) : selectedTypes.delete(ty);
  });
});

// ---------- Analyze ----------
let lastResults = [];
let analyzeStartTime = null;
let analyzeTimerHandle = null;
let currentProgressLabel = "";

function renderAnalyzeStatus() {
  const elapsedSec = analyzeStartTime ? Math.floor((Date.now() - analyzeStartTime) / 1000) : 0;
  $("#analyze-status").innerHTML = `<svg class="icon"><use href="#icon-history"/></svg>${t("msg_analyzing")}${currentProgressLabel} — ${t("hint_elapsed_time", { seconds: elapsedSec })}`;
}

function startAnalyzeTimer() {
  analyzeStartTime = Date.now();
  renderAnalyzeStatus();
  analyzeTimerHandle = setInterval(renderAnalyzeStatus, 1000);
}

function stopAnalyzeTimer() {
  if (analyzeTimerHandle) {
    clearInterval(analyzeTimerHandle);
    analyzeTimerHandle = null;
  }
}

function updateResultsTitle(profiles) {
  const title = $("#results-title");
  const visibleCount = $$(".row-select").length; // rows still present, not the total ever analyzed
  if (profiles && profiles.size > 0) {
    const profileLabel = profiles.size === 1 ? [...profiles][0] : `${profiles.size} profiles/pages`;
    title.textContent = `${visibleCount} — ${profileLabel}`;
  } else {
    title.textContent = `${visibleCount}`;
  }
}

$("#select-all-results").addEventListener("change", (e) => {
  $$(".row-select").forEach((cb) => {
    cb.checked = e.target.checked;
  });
});

function appendResultRows(items, profiles) {
  if (!items || items.length === 0) return;
  $("#results-panel").style.display = "block";
  const body = $("#results-body");

  items.forEach((item) => {
    const idx = lastResults.length;
    lastResults.push(item);
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td><input type="checkbox" class="row-select" data-idx="${idx}" ${item.already_downloaded ? "" : "checked"} /></td>
      <td>${item.thumbnail_url ? `<img class="thumb" src="${item.thumbnail_url}" />` : ""}</td>
      <td>${escapeHtml(item.display_title)}${item.already_downloaded ? ` <span class="hint">${t("msg_already_downloaded")}</span>` : ""}</td>
      <td>${typeBadge(item.media_type)}</td>
      <td>${item.publish_date ? item.publish_date.substring(0, 10) : "—"}</td>
      <td class="path-preview">${item.predicted_path}</td>
    `;
    body.appendChild(tr);
    body.insertAdjacentHTML("beforeend", renderDetailRow(6, item.description, item.tags));
  });

  updateResultsTitle(profiles);
}

$("#btn-analyze").addEventListener("click", async () => {
  const raw = $("#fb-url").value.trim();
  if (!raw) return;
  const urls = raw.split("\n").map((u) => u.trim()).filter(Boolean);
  if (urls.length === 0) return;

  $("#btn-analyze").disabled = true;
  $("#results-panel").style.display = "none";
  $("#results-body").innerHTML = "";
  $("#select-all-results").checked = false;
  lastResults = [];

  const errors = [];
  const profiles = new Set();

  startAnalyzeTimer();

  for (let i = 0; i < urls.length; i++) {
    currentProgressLabel = urls.length > 1 ? ` (${i + 1}/${urls.length})` : "";
    renderAnalyzeStatus();

    try {
      const res = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: urls[i] }),
      });
      if (!res.ok) {
        let detail = "Analysis error";
        try {
          const err = await res.json();
          if (err && err.detail) detail = err.detail;
        } catch (e) {
          // non-JSON body: keep the generic message
        }
        throw new Error(detail);
      }
      const job = await res.json();
      const result = await waitForAnalyzeJob(job.job_id);
      if (result.status === "error") {
        errors.push(`${urls[i]} — ${result.error}`);
      } else {
        if (result.profile) profiles.add(result.profile);
        // each analyzed link appears IMMEDIATELY in the table, instead
        // of waiting for every link in the list to finish
        appendResultRows(result.items || [], profiles);
      }
    } catch (e) {
      errors.push(`${urls[i]} — ${e.message}`);
    }
  }

  stopAnalyzeTimer();
  $("#btn-analyze").disabled = false;
  lastProfilesSet = profiles;
  updateResultsTitle(profiles);

  let statusMsg = lastResults.length > 0 ? t("msg_items_found", { count: lastResults.length, profile: [...profiles].join(", ") }) : "";
  if (errors.length > 0) {
    statusMsg += (statusMsg ? " — " : "") + errors.join(" | ");
  }
  $("#analyze-status").textContent = statusMsg;
});

function waitForAnalyzeJob(jobId) {
  return new Promise((resolve) => {
    const check = async () => {
      let res;
      try {
        res = await fetch(`/api/analyze/${jobId}`);
      } catch (e) {
        resolve({ status: "error", error: "Network error during analysis." });
        return;
      }

      if (!res.ok) {
        // expired/not found job (e.g. after a container restart: analysis
        // jobs live in memory only) or another server error — previously
        // this wasn't checked, causing a JS crash instead of a readable
        // error message
        let detail = `Error ${res.status} during analysis.`;
        try {
          const err = await res.json();
          if (err && err.detail) detail = err.detail;
        } catch (e) {
          // non-JSON body: keep the generic message above
        }
        resolve({ status: "error", error: detail });
        return;
      }

      let job;
      try {
        job = await res.json();
      } catch (e) {
        resolve({ status: "error", error: "Invalid server response during analysis." });
        return;
      }

      if (job && job.status === "running") {
        setTimeout(check, 2000);
      } else {
        resolve(job || { status: "error", error: "Empty response from server." });
      }
    };
    check();
  });
}

function renderDetailRow(colspan, description, tags) {
  const hasDescription = description && description.trim().length > 0;
  const hasTags = tags && tags.length > 0;
  const descriptionHtml = hasDescription
    ? `<span class="detail-text">${escapeHtml(description)}</span>`
    : `<span class="detail-text detail-empty">${t("detail_no_description")}</span>`;
  const tagsHtml = hasTags
    ? `<div class="tag-chips">${tags.map((tg) => `<span class="tag-chip">${escapeHtml(tg)}</span>`).join("")}</div>`
    : `<span class="detail-text detail-empty">${t("detail_no_tags")}</span>`;

  return `
    <tr class="detail-row">
      <td colspan="${colspan}">
        <div class="detail-block">
          <div class="detail-line"><span class="detail-label">${t("th_description")}</span>${descriptionHtml}</div>
          <div class="detail-line"><span class="detail-label">${t("th_tags")}</span>${tagsHtml}</div>
        </div>
      </td>
    </tr>
  `;
}

$("#btn-download-selected").addEventListener("click", async () => {
  const checked = $$(".row-select:checked").map((cb) => lastResults[parseInt(cb.dataset.idx)]);
  const toSend = checked.filter((i) => selectedTypes.has(i.media_type));
  if (toSend.length === 0) return;

  let res;
  try {
    res = await fetch("/api/download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: toSend, media_types: Array.from(selectedTypes) }),
    });
  } catch (e) {
    $("#analyze-status").textContent = t("msg_error_prefix") + "network error.";
    return;
  }

  if (!res.ok) {
    let detail = `Error ${res.status}.`;
    try {
      const err = await res.json();
      if (err && err.detail) detail = err.detail;
    } catch (e) {
      // non-JSON body: keep the generic message
    }
    $("#analyze-status").textContent = t("msg_error_prefix") + detail;
    return;
  }

  const data = await res.json();
  $("#analyze-status").textContent = t("msg_queued", { count: (data.queued || []).length });

  toSend.forEach((item) => pendingDownloadIds.add(item.fb_id));
  startQueuePolling();
});

// ---------- Download queue (polling) ----------
let queuePollTimer = null;
let pendingDownloadIds = new Set();
let lastProfilesSet = new Set();

function startQueuePolling() {
  if (queuePollTimer) return;
  pollQueue();
  queuePollTimer = setInterval(pollQueue, 2000);
}

async function pollQueue() {
  let items = [];
  try {
    const res = await fetch("/api/queue");
    if (res.ok) items = (await res.json()) || [];
  } catch (e) {
    // skip this polling round, retry on the next interval
    return;
  }
  renderQueue(items);

  if (pendingDownloadIds.size > 0) {
    const stillQueuedIds = new Set(items.map((i) => i.fb_id));
    const justFinishedIds = [...pendingDownloadIds].filter((id) => !stillQueuedIds.has(id));
    if (justFinishedIds.length > 0) {
      justFinishedIds.forEach((id) => pendingDownloadIds.delete(id));
      await removeCompletedResultRows(justFinishedIds);
    }
  }

  if (items.length === 0) {
    clearInterval(queuePollTimer);
    queuePollTimer = null;
    if ($("#tab-history").classList.contains("active")) {
      loadHistory();
    }
  }
}

async function removeCompletedResultRows(fbIds) {
  // an item that left the queue may have finished successfully OR with
  // an error: we remove from the results table ONLY the ones completed
  // successfully, keeping the ones with errors visible (so the user can
  // reselect and retry them without having to find them again)
  let historyItems = [];
  try {
    const res = await fetch("/api/history");
    if (res.ok) historyItems = (await res.json()) || [];
  } catch (e) {
    return;
  }

  const statusById = {};
  historyItems.forEach((h) => {
    statusById[h.fb_id] = h.status;
  });

  fbIds.forEach((fbId) => {
    if (statusById[fbId] === "done") {
      removeResultRowByFbId(fbId);
    }
  });
}

function removeResultRowByFbId(fbId) {
  const idx = lastResults.findIndex((item) => item && item.fb_id === fbId);
  if (idx === -1) return;

  const checkbox = $(`.row-select[data-idx="${idx}"]`);
  if (checkbox) {
    const tr = checkbox.closest("tr");
    if (tr) {
      const detailRow = tr.nextElementSibling;
      if (detailRow && detailRow.classList.contains("detail-row")) detailRow.remove();
      tr.remove();
    }
  }

  updateResultsTitle(lastProfilesSet);

  if ($$(".row-select").length === 0) {
    $("#results-panel").style.display = "none";
  }
}

function renderQueue(items) {
  items = items || [];
  const panel = $("#queue-panel");
  if (items.length === 0) {
    panel.style.display = "none";
    return;
  }
  panel.style.display = "block";
  const body = $("#queue-body");
  body.innerHTML = "";
  items.forEach((item) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.profile)}</td>
      <td>${typeBadge(item.media_type)}</td>
      <td>${escapeHtml(item.title)}</td>
      <td>${statusLabel(item.status)}</td>
    `;
    body.appendChild(tr);
  });
}

// ---------- Analyzed sources (link history + reload) ----------
async function loadSources() {
  let sources = [];
  try {
    const res = await fetch("/api/history/sources");
    if (res.ok) sources = (await res.json()) || [];
  } catch (e) {
    return;
  }
  const body = $("#sources-body");
  body.innerHTML = "";
  sources.forEach((s) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(s.profile || "—")}</td>
      <td class="path-preview">${escapeHtml(s.url)}</td>
      <td>${s.last_item_count}</td>
      <td>${s.last_analyzed_at ? s.last_analyzed_at.substring(0, 10) : "—"}</td>
      <td><button class="btn secondary btn-reload" data-url="${escapeHtml(s.url)}"><svg class="icon"><use href="#icon-refresh"/></svg>${t("btn_reload")}</button></td>
    `;
    body.appendChild(tr);
  });

  $$(".btn-reload").forEach((btn) => {
    btn.addEventListener("click", () => {
      $("#fb-url").value = btn.dataset.url;
      switchTab("download");
      $("#btn-analyze").click();
    });
  });
}

// ---------- History ----------
async function loadHistory() {
  let items = [];
  try {
    const res = await fetch("/api/history");
    if (res.ok) items = (await res.json()) || [];
  } catch (e) {
    return;
  }
  const body = $("#history-body");
  body.innerHTML = "";
  items.forEach((item) => {
    const seasonEp = item.season != null && item.episode != null ? `S${item.season} E${item.episode}` : "—";
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${escapeHtml(item.profile)}</td>
      <td>${typeBadge(item.media_type)}</td>
      <td>${escapeHtml(item.title)}</td>
      <td>${seasonEp}</td>
      <td>${item.publish_date ? item.publish_date.substring(0, 10) : "—"}</td>
      <td class="path-preview">${escapeHtml(item.relative_path)}</td>
      <td>${statusLabel(item.status)}</td>
    `;
    body.appendChild(tr);
    body.insertAdjacentHTML("beforeend", renderDetailRow(7, item.description, item.tags));
  });
}

// ---------- Settings ----------
async function loadSettings() {
  const res = await fetch("/api/settings");
  const s = await res.json();
  $("#setting-folder-video").value = s.folder_template_video;
  $("#setting-folder-photo").value = s.folder_template_photo;
  $("#setting-filename").value = s.filename_template;
  $("#setting-filename-photo").value = s.filename_template_photo;
  $("#setting-dateformat").value = s.date_format;
  $("#setting-nfo").checked = s.generate_nfo;
  $("#setting-translate").checked = s.translate_description;
  $("#setting-language").value = languageLabel(s.ui_language || "en");
  applyTranslations(s.ui_language || "en");
  applyTheme(s.theme || "dark");
}

// ---------- Theme ----------
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem("theme", theme);
  } catch (e) {
    // localStorage unavailable (e.g. private browsing) — theme just won't persist across reloads
  }
  $$(".theme-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === theme);
  });
}

$$(".theme-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    const theme = btn.dataset.theme;
    applyTheme(theme);
    await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
    });
  });
});

$("#btn-save-settings").addEventListener("click", async () => {
  const langCode = resolveLanguageCode($("#setting-language").value);
  const body = {
    folder_template_video: $("#setting-folder-video").value,
    folder_template_photo: $("#setting-folder-photo").value,
    filename_template: $("#setting-filename").value,
    filename_template_photo: $("#setting-filename-photo").value,
    date_format: $("#setting-dateformat").value,
    generate_nfo: $("#setting-nfo").checked,
    translate_description: $("#setting-translate").checked,
    ui_language: langCode,
  };
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (res.ok) {
    applyTranslations(langCode);
    $("#setting-language").value = languageLabel(langCode);
  }
  $("#settings-status").innerHTML = res.ok
    ? `<svg class="icon"><use href="#icon-check"/></svg>${t("msg_settings_saved")}`
    : `<svg class="icon"><use href="#icon-error"/></svg>${t("msg_settings_error")}`;
});

// ---------- Login (cookie) ----------
async function loadLoginStatus() {
  const res = await fetch("/api/auth/status");
  const s = await res.json();
  if (!s.cookies_present) {
    $("#login-status").innerHTML = `<svg class="icon"><use href="#icon-info"/></svg>${t("msg_no_session")}`;
    return;
  }
  let extra = "";
  if (s.expired === true) {
    extra = t("msg_session_expired");
  } else if (s.days_remaining !== null && s.days_remaining !== undefined) {
    extra = t("msg_session_expires", { days: s.days_remaining, date: s.expires_at ? s.expires_at.substring(0, 10) : "?" });
  }
  $("#login-status").innerHTML = `<svg class="icon"><use href="#${s.expired ? "icon-error" : "icon-check"}"/></svg>${t("msg_session_active")}${extra}`;
}

async function checkCookieBanner() {
  try {
    const res = await fetch("/api/auth/status");
    const s = await res.json();
    const banner = $("#cookie-banner");
    banner.classList.remove("show", "expired", "warning");

    if (!s.cookies_present) return;

    if (s.expired === true) {
      banner.classList.add("show", "expired");
      $("#cookie-banner-text").textContent = t("banner_expired");
    } else if (s.days_remaining !== null && s.days_remaining !== undefined && s.days_remaining <= 3) {
      banner.classList.add("show", "warning");
      $("#cookie-banner-text").textContent = t("banner_warning", { days: s.days_remaining });
    }
  } catch (e) {
    // silent: don't block the app if the check fails
  }
}

async function uploadCookieFile(file) {
  if (!file) return;
  $("#login-status").innerHTML = `<svg class="icon"><use href="#icon-history"/></svg>${t("msg_analyzing")}`;
  const form = new FormData();
  form.append("file", file);
  let res;
  try {
    res = await fetch("/api/auth/cookies", { method: "POST", body: form });
  } catch (e) {
    $("#login-status").innerHTML = `<svg class="icon"><use href="#icon-error"/></svg>${t("msg_cookies_upload_error")}`;
    return;
  }
  $("#login-status").innerHTML = res.ok
    ? `<svg class="icon"><use href="#icon-check"/></svg>${t("msg_cookies_uploaded")}`
    : `<svg class="icon"><use href="#icon-error"/></svg>${t("msg_cookies_upload_error")}`;
  loadLoginStatus();
  checkCookieBanner();
}

// uploads automatically as soon as the user chooses the file, no need
// to press a separate "Upload" button
$("#cookie-file").addEventListener("change", () => {
  uploadCookieFile($("#cookie-file").files[0]);
});

$("#btn-clear-cookies").addEventListener("click", async () => {
  await fetch("/api/auth/cookies", { method: "DELETE" });
  $("#cookie-file").value = "";
  loadLoginStatus();
  checkCookieBanner();
});

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

// ---------- Log ----------
let logsPollTimer = null;
let currentLogLevel = 1;

function selectLogLevelChip(level) {
  $$("#log-level-filter .chip").forEach((chip) => {
    chip.classList.toggle("selected", parseInt(chip.dataset.level) === level);
  });
  $("#log-level-description").textContent = t(`log_level_desc_${level}`);
}

async function loadLogs() {
  // the current level lives in the shared (persisted) settings, so the
  // choice stays the same even when switching tabs or restarting the app
  try {
    const res = await fetch("/api/settings");
    if (res.ok) {
      const s = await res.json();
      currentLogLevel = s.log_level != null ? s.log_level : 1;
      selectLogLevelChip(currentLogLevel);
    }
  } catch (e) {
    // ignore: the level selection stays whatever is currently shown in the UI
  }

  try {
    const res = await fetch("/api/logs");
    if (res.ok) {
      const data = await res.json();
      const textarea = $("#log-output");
      const wasScrolledToBottom = textarea.scrollTop + textarea.clientHeight >= textarea.scrollHeight - 10;
      textarea.value = (data.lines || []).join("\n");
      if (wasScrolledToBottom) {
        textarea.scrollTop = textarea.scrollHeight;
      }
    }
  } catch (e) {
    // skip this polling round, retry on the next interval
  }
}

function startLogsPolling() {
  if (logsPollTimer) return;
  logsPollTimer = setInterval(loadLogs, 2000);
}

function stopLogsPolling() {
  if (logsPollTimer) {
    clearInterval(logsPollTimer);
    logsPollTimer = null;
  }
}

$$("#log-level-filter .chip").forEach((chip) => {
  chip.addEventListener("click", async () => {
    const level = parseInt(chip.dataset.level);
    selectLogLevelChip(level);
    currentLogLevel = level;
    await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ log_level: level }),
    });
  });
});

$("#btn-copy-logs").addEventListener("click", async () => {
  const text = $("#log-output").value;
  try {
    await navigator.clipboard.writeText(text);
    $("#logs-status").innerHTML = `<svg class="icon"><use href="#icon-check"/></svg>${t("msg_logs_copied")}`;
  } catch (e) {
    // fallback for contexts without the Clipboard API (e.g. non-HTTPS):
    // selects the text so the user can copy it manually with Ctrl/Cmd+C
    const textarea = $("#log-output");
    textarea.focus();
    textarea.select();
    $("#logs-status").innerHTML = `<svg class="icon"><use href="#icon-info"/></svg>${t("msg_logs_copy_manual")}`;
  }
});

$("#btn-clear-logs").addEventListener("click", async () => {
  await fetch("/api/logs", { method: "DELETE" });
  loadLogs();
});

// The URL box's content is persisted to localStorage: each share reopens
// the PWA as a fresh page load (a new browser navigation, not a
// continuation of the same in-memory session), so the textarea always
// starts empty in the DOM — without this, "appending" a newly shared
// link would append to nothing and silently lose whatever was shared
// before it.
const URL_DRAFT_KEY = "fbUrlDraft";

function saveUrlDraft() {
  try {
    localStorage.setItem(URL_DRAFT_KEY, $("#fb-url").value);
  } catch (e) {
    // localStorage unavailable (e.g. private browsing) — the draft just won't persist
  }
}

function loadUrlDraft() {
  try {
    return localStorage.getItem(URL_DRAFT_KEY) || "";
  } catch (e) {
    return "";
  }
}

$("#fb-url").addEventListener("input", saveUrlDraft);

$("#btn-clear-url").addEventListener("click", () => {
  $("#fb-url").value = "";
  saveUrlDraft(); // persists the now-empty value too, otherwise the
                   // cleared links would reappear on the next page load
});

// handles a link shared from another Android app (e.g. Facebook's
// "Share" button) via the PWA share target: main.py's /share-target
// redirects here with ?shared_url=...
function handleSharedUrl() {
  const textarea = $("#fb-url");

  // restores whatever was in the box before this page load (previous
  // shares, or links typed in and not yet analyzed)
  const draft = loadUrlDraft();
  if (draft && !textarea.value.trim()) {
    textarea.value = draft;
  }

  const params = new URLSearchParams(window.location.search);
  const sharedUrl = params.get("shared_url");
  if (sharedUrl) {
    const existing = textarea.value.trim();
    textarea.value = existing ? `${existing}\n${sharedUrl}` : sharedUrl;
    switchTab("download");

    // removes the query parameter from the address bar so refreshing the
    // page doesn't re-append the same link again
    const cleanUrl = window.location.pathname;
    window.history.replaceState({}, "", cleanUrl);
  }

  saveUrlDraft();
}

// init
populateLanguageOptions();
loadSettings();
checkCookieBanner();
handleSharedUrl();
