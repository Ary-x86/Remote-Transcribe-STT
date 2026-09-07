/* Remote Transcribe — client. No framework, no build step. */
(() => {
"use strict";

const $ = (id) => document.getElementById(id);
const PREFS_KEY = "remote-transcribe:prefs";
const POLL_MS = 1000;

const state = {
  file: null,          // File or Blob awaiting transcription
  fileName: "",
  objectUrl: null,
  record: null,        // active recording context
  settings: null,
  models: [],
  current: null,       // the transcript record on screen
  polling: null,
};

/* ---- helpers ----------------------------------------------------------- */

const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));

function clock(seconds) {
  seconds = Math.max(0, Math.round(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function humanSize(bytes) {
  if (!bytes) return "";
  const mb = bytes / 1e6;
  return mb < 1 ? `${Math.round(bytes / 1e3)} KB` : `${mb.toFixed(1)} MB`;
}

// A <select> that has not been populated yet reports selectedIndex -1.
function optionText(select) {
  const option = select.options[select.selectedIndex];
  return option ? option.text : "";
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text == null ? "" : String(text);
  return div.innerHTML;
}

let toastTimer = null;
function toast(message, isError = false) {
  const el = $("toast");
  el.textContent = message;
  el.classList.toggle("err", isError);
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, isError ? 6000 : 2600);
}

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (response.status === 401) {
    showLogin();
    throw new Error("Session expired. Sign in again.");
  }
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body && body.detail) detail = body.detail;
    } catch { /* non-JSON error body */ }
    throw new Error(detail);
  }
  return response.status === 204 ? null : response.json();
}

/* ---- preferences ------------------------------------------------------- */

function loadPrefs() {
  try { return JSON.parse(localStorage.getItem(PREFS_KEY)) || {}; }
  catch { return {}; }
}

function savePrefs() {
  const prefs = {
    model: $("opt-model").value,
    task: $("opt-task").value,
    language: $("opt-language").value,
    diarization: $("opt-diarization").value,
    numSpeakers: $("opt-num-speakers").value,
    cleanup: $("opt-cleanup").value,
    prompt: $("opt-prompt").value,
    temperature: $("opt-temperature").value,
    autocopy: $("opt-autocopy").checked,
    optionsOpen: $("options").open,
  };
  try { localStorage.setItem(PREFS_KEY, JSON.stringify(prefs)); } catch { /* private mode */ }
}

function applyPrefs() {
  const p = loadPrefs();
  const set = (id, value) => { if (value != null && value !== "") $(id).value = value; };
  set("opt-model", p.model);
  set("opt-task", p.task);
  set("opt-language", p.language);
  set("opt-diarization", p.diarization);
  set("opt-num-speakers", p.numSpeakers);
  set("opt-cleanup", p.cleanup);
  set("opt-prompt", p.prompt);
  set("opt-temperature", p.temperature);
  if (p.autocopy != null) $("opt-autocopy").checked = !!p.autocopy;
  if (p.optionsOpen) $("options").open = true;
}

/* ---- auth -------------------------------------------------------------- */

function showLogin() {
  $("login").hidden = false;
  $("app").hidden = true;
  setTimeout(() => $("login-password").focus(), 50);
}

async function boot() {
  let session;
  try {
    session = await api("/api/session");
  } catch {
    document.body.innerHTML =
      '<div class="overlay"><div class="login-card"><h1>Server unreachable</h1>' +
      '<p class="muted">Is the app still running?</p></div></div>';
    return;
  }

  if (session.auth_required && !session.authenticated) { showLogin(); return; }

  $("login").hidden = true;
  $("app").hidden = false;
  $("btn-logout").hidden = !session.auth_required;

  try {
    // Sequential on purpose: loadModels reads the default model from settings,
    // and it populates selects that syncOptionState reads back.
    await loadSettings();
    await loadModels();
  } catch (error) {
    toast(`Could not load settings: ${error.message}`, true);
  }
  applyPrefs();
  syncOptionState();
  refreshHistory();
}

$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = new FormData();
  body.append("password", $("login-password").value);
  try {
    await api("/api/login", { method: "POST", body });
    $("login-error").hidden = true;
    $("login-password").value = "";
    boot();
  } catch (error) {
    $("login-error").textContent = error.message;
    $("login-error").hidden = false;
  }
});

$("btn-logout").addEventListener("click", async () => {
  await fetch("/api/logout", { method: "POST", credentials: "same-origin" });
  location.reload();
});

/* ---- settings and models ----------------------------------------------- */

async function loadSettings() {
  state.settings = await api("/api/settings");

  const cleanupSelect = $("opt-cleanup");
  const resultSelect = $("result-cleanup");
  cleanupSelect.innerHTML = "";
  resultSelect.innerHTML = "";
  for (const preset of state.settings.cleanup_presets) {
    cleanupSelect.add(new Option(preset.label, preset.id));
    resultSelect.add(new Option(
      preset.id === "raw" ? "Cleanup…" : `Re-run: ${preset.label}`, preset.id));
  }
  updateCleanupHint();

  const banners = [];
  if (!state.settings.groq_configured) {
    banners.push({
      cls: "err",
      html: 'No Groq API key configured. Add <code>GROQ_API_KEY</code> to your <code>.env</code> ' +
            'file and restart — create one at ' +
            '<a href="https://console.groq.com/keys" target="_blank" rel="noopener">console.groq.com/keys</a>.',
    });
  }
  if (banners.length) {
    $("banner").className = `banner ${banners[0].cls}`;
    $("banner").innerHTML = banners[0].html;
    $("banner").hidden = false;
  }

  const acoustic = $("opt-diarization").querySelector('option[value="acoustic"]');
  acoustic.disabled = !state.settings.elevenlabs_configured;
  if (acoustic.disabled) acoustic.textContent = "Acoustic (needs an ElevenLabs key)";
}

async function loadModels() {
  const data = await api("/api/models");
  state.models = data.models;

  const select = $("opt-model");
  select.innerHTML = "";
  for (const model of data.models) {
    const price = model.price_per_hour != null ? ` — $${model.price_per_hour.toFixed(3)}/hr` : "";
    select.add(new Option(model.label + price, model.id));
  }
  if (state.settings && state.settings.default_model) {
    const match = [...select.options].find((o) => o.value === state.settings.default_model);
    if (match) select.value = state.settings.default_model;
  }
  if (data.warning) toast(data.warning, true);
  updateModelHint();
}

function selectedModel() {
  return state.models.find((m) => m.id === $("opt-model").value) || null;
}

function updateModelHint() {
  const model = selectedModel();
  $("model-hint").textContent = model && model.best_for ? model.best_for : "";

  // Selecting the ElevenLabs model implies its engine; keep the two in step.
  const diar = $("opt-diarization");
  const isElevenLabs = model && model.provider === "elevenlabs";
  const translate = $("opt-task").querySelector('option[value="translate"]');
  translate.disabled = isElevenLabs;
  if (isElevenLabs && $("opt-task").value === "translate") $("opt-task").value = "transcribe";
  if (!isElevenLabs && diar.value === "acoustic") diar.value = "llm";
  syncOptionState();
}

function updateCleanupHint() {
  const presets = (state.settings && state.settings.cleanup_presets) || [];
  const preset = presets.find((p) => p.id === $("opt-cleanup").value);
  $("cleanup-hint").textContent = preset ? preset.description : "";
}

function syncOptionState() {
  const mode = $("opt-diarization").value;
  $("field-speakers").hidden = mode === "off";

  const hints = {
    off: "No speaker labels.",
    llm: "Estimated from the transcript text, not the voices — good on clean " +
         "turn-taking, unreliable on crosstalk.",
    acoustic: "True voice-based separation via ElevenLabs. Costs about $0.22 per hour.",
  };
  $("diarization-hint").textContent = hints[mode] || "";

  // Acoustic diarization only exists on the ElevenLabs model.
  if (mode === "acoustic") {
    const eleven = state.models.find((m) => m.provider === "elevenlabs");
    if (eleven && $("opt-model").value !== eleven.id) {
      $("opt-model").value = eleven.id;
      $("model-hint").textContent = eleven.best_for || "";
    }
  }

  const bits = [];
  const model = selectedModel();
  if (model) bits.push(model.label);
  if ($("opt-task").value === "translate") bits.push("→ English");
  if ($("opt-language").value) bits.push(optionText($("opt-language")));
  if (mode !== "off") bits.push("speakers");
  const cleanup = $("opt-cleanup").value;
  if (cleanup && cleanup !== "raw") bits.push(optionText($("opt-cleanup")).toLowerCase());
  $("options-summary").textContent = bits.join(" · ");

  updateCostHint();
  savePrefs();
}

function updateCostHint() {
  const model = selectedModel();
  const seconds = state.durationGuess || 0;
  if (!model || !model.price_per_hour || !seconds) { $("cost-hint").textContent = ""; return; }
  // Groq bills a 10-second minimum per request.
  const billed = Math.max(10, seconds);
  const cost = (billed / 3600) * model.price_per_hour;
  $("cost-hint").textContent =
    `${clock(seconds)} of audio — about ${cost < 0.01 ? "<$0.01" : "$" + cost.toFixed(2)}`;
}

/* ---- language list ----------------------------------------------------- */

(function fillLanguages() {
  const select = $("opt-language");
  select.add(new Option("Auto-detect", ""));
  for (const [code, name] of window.WHISPER_LANGUAGES) {
    select.add(new Option(`${name} (${code})`, code));
  }
})();

/* ---- source tabs ------------------------------------------------------- */

document.querySelectorAll("[data-source]").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-source]").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    $("pane-record").hidden = tab.dataset.source !== "record";
    $("pane-upload").hidden = tab.dataset.source !== "upload";
  });
});

/* ---- file selection ---------------------------------------------------- */

function setFile(file, name) {
  clearFile(false);
  state.file = file;
  state.fileName = name || file.name || "recording.webm";
  state.objectUrl = URL.createObjectURL(file);

  $("selected-name").textContent = state.fileName;
  $("selected-meta").textContent = humanSize(file.size);
  $("selected-audio").src = state.objectUrl;
  $("selected").hidden = false;
  $("btn-submit").disabled = false;

  // Duration drives the cost estimate; the element reports it once loaded.
  $("selected-audio").onloadedmetadata = () => {
    const duration = $("selected-audio").duration;
    if (Number.isFinite(duration) && duration > 0) {
      state.durationGuess = duration;
      $("selected-meta").textContent = `${clock(duration)} · ${humanSize(file.size)}`;
      updateCostHint();
    }
  };
}

function clearFile(resetUi = true) {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = null;
  state.objectUrl = null;
  state.durationGuess = 0;
  if (resetUi) {
    $("selected").hidden = true;
    $("selected-audio").removeAttribute("src");
    $("btn-submit").disabled = true;
    $("cost-hint").textContent = "";
  }
}

$("btn-clear").addEventListener("click", () => clearFile());

const dropzone = $("dropzone");
dropzone.addEventListener("click", () => $("file-input").click());
dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") { event.preventDefault(); $("file-input").click(); }
});
$("file-input").addEventListener("change", (event) => {
  if (event.target.files[0]) setFile(event.target.files[0]);
});
["dragenter", "dragover"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault(); dropzone.classList.add("over");
  }));
["dragleave", "drop"].forEach((name) =>
  dropzone.addEventListener(name, (event) => {
    event.preventDefault(); dropzone.classList.remove("over");
  }));
dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files[0];
  if (file) setFile(file);
});

/* ---- recording --------------------------------------------------------- */

if (!window.isSecureContext || !navigator.mediaDevices) {
  $("mic-warning").hidden = false;
  $("btn-record").disabled = true;
  $("record-hint").textContent = "Microphone unavailable — upload a file instead";
}

function pickMimeType() {
  // Both are on Groq's accepted list; Safari only has the mp4 one.
  const candidates = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  return candidates.find((type) => MediaRecorder.isTypeSupported(type)) || "";
}

async function startRecording() {
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
  } catch (error) {
    const denied = error && (error.name === "NotAllowedError" || error.name === "SecurityError");
    toast(denied ? "Microphone permission denied. Allow it in your browser's site settings."
                 : `Could not open the microphone: ${error.message}`, true);
    return;
  }

  const mimeType = pickMimeType();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
  const chunks = [];
  recorder.ondataavailable = (event) => { if (event.data.size) chunks.push(event.data); };

  // Live input level, so it is obvious the mic is actually picking something up.
  const audioContext = new (window.AudioContext || window.webkitAudioContext)();
  const analyser = audioContext.createAnalyser();
  analyser.fftSize = 512;
  audioContext.createMediaStreamSource(stream).connect(analyser);
  const samples = new Uint8Array(analyser.frequencyBinCount);
  const meter = $("meter").firstElementChild;

  const started = Date.now();
  let raf = 0;
  const tick = () => {
    analyser.getByteTimeDomainData(samples);
    let peak = 0;
    for (const sample of samples) peak = Math.max(peak, Math.abs(sample - 128));
    meter.style.width = `${clamp((peak / 128) * 180, 2, 100)}%`;
    $("timer").textContent = clock((Date.now() - started) / 1000);
    raf = requestAnimationFrame(tick);
  };
  tick();

  recorder.onstop = () => {
    cancelAnimationFrame(raf);
    audioContext.close().catch(() => {});
    stream.getTracks().forEach((track) => track.stop());
    meter.style.width = "0%";

    $("btn-record").classList.remove("recording");
    $("btn-record").setAttribute("aria-label", "Start recording");
    $("btn-record-cancel").hidden = true;
    $("record-hint").textContent = "Click to start recording";

    const context = state.record;
    state.record = null;
    if (context && context.discarded) { $("timer").textContent = "00:00"; return; }

    const type = recorder.mimeType || mimeType || "audio/webm";
    const blob = new Blob(chunks, { type });
    if (!blob.size) { toast("That recording came out empty.", true); return; }

    const extension = type.includes("mp4") ? "m4a" : type.includes("ogg") ? "ogg" : "webm";
    const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
    setFile(blob, `recording-${stamp}.${extension}`);
    state.durationGuess = (Date.now() - started) / 1000;
    updateCostHint();
  };

  recorder.start();
  state.record = { recorder, discarded: false };
  $("btn-record").classList.add("recording");
  $("btn-record").setAttribute("aria-label", "Stop recording");
  $("btn-record-cancel").hidden = false;
  $("record-hint").textContent = "Recording — click again to stop";
}

$("btn-record").addEventListener("click", () => {
  if (state.record) state.record.recorder.stop();
  else startRecording();
});

$("btn-record-cancel").addEventListener("click", () => {
  if (!state.record) return;
  state.record.discarded = true;
  state.record.recorder.stop();
});

/* ---- submit and poll --------------------------------------------------- */

$("btn-submit").addEventListener("click", async () => {
  if (!state.file) return;

  const body = new FormData();
  body.append("file", state.file, state.fileName);
  body.append("model", $("opt-model").value);
  body.append("engine", (selectedModel() || {}).provider === "elevenlabs" ? "elevenlabs" : "groq");
  body.append("task", $("opt-task").value);
  body.append("language", $("opt-language").value);
  body.append("prompt", $("opt-prompt").value);
  body.append("temperature", $("opt-temperature").value);
  body.append("diarization", $("opt-diarization").value);
  body.append("num_speakers", $("opt-num-speakers").value);
  body.append("cleanup", $("opt-cleanup").value);

  $("btn-submit").disabled = true;
  $("result").hidden = true;
  showProgress("Uploading…", 0, 0);

  try {
    const { job_id } = await api("/api/transcribe", { method: "POST", body });
    pollJob(job_id);
  } catch (error) {
    hideProgress();
    $("btn-submit").disabled = false;
    toast(error.message, true);
  }
});

function showProgress(label, done, total) {
  $("progress").hidden = false;
  $("progress-label").textContent = label;
  const bar = $("progress-bar");
  if (total > 1) {
    bar.classList.remove("indeterminate");
    bar.style.width = `${Math.round((done / total) * 100)}%`;
    $("progress-detail").textContent = `chunk ${Math.min(done + 1, total)} of ${total}`;
  } else {
    bar.classList.add("indeterminate");
    $("progress-detail").textContent = "";
  }
}

function hideProgress() {
  $("progress").hidden = true;
  $("progress-bar").classList.remove("indeterminate");
  clearTimeout(state.polling);
}

function pollJob(jobId) {
  const step = async () => {
    let job;
    try {
      job = await api(`/api/jobs/${jobId}`);
    } catch (error) {
      hideProgress();
      $("btn-submit").disabled = false;
      toast(error.message, true);
      return;
    }

    showProgress(job.stage_label, job.chunks_done, job.chunks_total);

    if (!job.done) { state.polling = setTimeout(step, POLL_MS); return; }

    hideProgress();
    $("btn-submit").disabled = false;

    if (job.stage === "error") { toast(job.error || "Transcription failed.", true); return; }

    renderResult(job.result);
    refreshHistory();
    if ($("opt-autocopy").checked) copyResult(true);
  };
  step();
}

/* ---- rendering --------------------------------------------------------- */

function displayText(record) {
  return record.clean_text || record.raw_text || "";
}

function renderResult(record) {
  state.current = record;
  $("result").hidden = false;

  $("transcript").textContent = displayText(record);

  const segments = record.segments || [];
  const hasSpeakers = segments.some((s) => s.speaker);
  document.querySelector('[data-view="speakers"]').hidden = !hasSpeakers;

  const meta = [];
  if (record.duration) meta.push(clock(record.duration));
  if (record.model) meta.push(record.model);
  if (record.language) meta.push(`language: ${record.language}`);
  if (record.task === "translate") meta.push("translated to English");
  const words = displayText(record).trim().split(/\s+/).filter(Boolean).length;
  if (words) meta.push(`${words.toLocaleString()} words`);
  $("result-meta").textContent = meta.join(" · ");

  $("result-warnings").innerHTML = (record.warnings || [])
    .map((w) => `<div class="notice warn">${escapeHtml(w)}</div>`).join("");

  $("result-cleanup").value = record.cleanup_preset || "raw";

  renderTurns(segments, record.options || {});
  renderSegments(segments);
  showView("text");
}

function renderTurns(segments, options) {
  const notice = $("speaker-notice");
  if (options.diarization === "llm") {
    notice.className = "notice warn";
    notice.innerHTML = "<strong>Estimated.</strong> These labels were inferred from the " +
      "transcript text, not from the voices — Groq's Whisper API cannot tell speakers apart. " +
      "Reliable on clean turn-taking, less so when people overlap. Click a name to rename it.";
  } else {
    notice.className = "notice";
    notice.innerHTML = "Speakers separated acoustically by ElevenLabs. Click a name to rename it.";
  }

  // Collapse consecutive segments from one speaker into a single turn.
  const turns = [];
  for (const segment of segments) {
    const last = turns[turns.length - 1];
    if (last && last.speaker === segment.speaker) {
      last.text += ` ${segment.text}`;
      last.end = segment.end;
    } else {
      turns.push({ speaker: segment.speaker, text: segment.text, start: segment.start,
                   end: segment.end });
    }
  }

  $("turns").innerHTML = turns.map((turn) => `
    <div class="turn">
      <div class="turn-speaker" contenteditable="plaintext-only" spellcheck="false"
           data-original="${escapeHtml(turn.speaker || "")}"
           title="${clock(turn.start)}">${escapeHtml(turn.speaker || "Unknown")}</div>
      <div class="turn-text">${escapeHtml(turn.text.trim())}</div>
    </div>`).join("");

  $("turns").querySelectorAll(".turn-speaker").forEach((el) => {
    el.addEventListener("blur", () => commitRename(el));
    el.addEventListener("keydown", (event) => {
      if (event.key === "Enter") { event.preventDefault(); el.blur(); }
      if (event.key === "Escape") { el.textContent = el.dataset.original; el.blur(); }
    });
  });
}

async function commitRename(el) {
  const original = el.dataset.original;
  const next = el.textContent.trim();
  if (!next || next === original || !state.current) { el.textContent = original; return; }

  try {
    const updated = await api(`/api/history/${state.current.id}/speakers`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mapping: { [original]: next } }),
    });
    renderResult(updated);
    showView("speakers");
    toast(`Renamed to ${next}`);
  } catch (error) {
    el.textContent = original;
    toast(error.message, true);
  }
}

function renderSegments(segments) {
  if (!segments.length) {
    $("segments").innerHTML = '<div class="empty">No timestamps for this transcript.</div>';
    return;
  }
  $("segments").innerHTML = segments.map((segment) => `
    <div class="segment">
      <span class="segment-time">${clock(segment.start)}</span>
      <span>${segment.speaker ? `<strong>${escapeHtml(segment.speaker)}:</strong> ` : ""}${escapeHtml(segment.text)}</span>
    </div>`).join("");
}

function showView(name) {
  document.querySelectorAll("[data-view]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.view === name);
  });
  $("view-text").hidden = name !== "text";
  $("view-speakers").hidden = name !== "speakers";
  $("view-timestamps").hidden = name !== "timestamps";
}

document.querySelectorAll("[data-view]").forEach((tab) => {
  tab.addEventListener("click", () => showView(tab.dataset.view));
});

/* ---- copy and export --------------------------------------------------- */

async function copyResult(silentOnFail = false) {
  if (!state.current) return;
  const text = displayText(state.current);
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard");
  } catch {
    // Clipboard API needs a secure context; fall back to a hidden textarea.
    const area = document.createElement("textarea");
    area.value = text;
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand("copy");
    area.remove();
    if (ok) toast("Copied to clipboard");
    else if (!silentOnFail) toast("Could not copy — select the text and copy manually.", true);
  }
}

$("btn-copy").addEventListener("click", () => copyResult());

$("btn-export").addEventListener("click", (event) => {
  event.stopPropagation();
  $("export-menu").hidden = !$("export-menu").hidden;
});
document.addEventListener("click", () => { $("export-menu").hidden = true; });
$("export-menu").addEventListener("click", (event) => {
  const fmt = event.target.dataset.fmt;
  if (!fmt || !state.current) return;
  window.location.href = `/api/history/${state.current.id}/export?fmt=${fmt}`;
  $("export-menu").hidden = true;
});

$("result-cleanup").addEventListener("change", async (event) => {
  if (!state.current) return;
  const preset = event.target.value;
  const body = new FormData();
  body.append("preset", preset);

  $("result-cleanup").disabled = true;
  try {
    await api(`/api/history/${state.current.id}/cleanup`, { method: "POST", body });
    const updated = await api(`/api/history/${state.current.id}`);
    renderResult(updated);
    refreshHistory();
    toast(preset === "raw" ? "Showing the raw transcript" : "Cleanup applied");
  } catch (error) {
    toast(error.message, true);
  } finally {
    $("result-cleanup").disabled = false;
  }
});

/* ---- history ----------------------------------------------------------- */

async function refreshHistory() {
  let items;
  try { ({ items } = await api("/api/history")); }
  catch { return; }

  const list = $("history-list");
  if (!items.length) {
    list.innerHTML = '<div class="empty">Nothing here yet.<br>Transcripts you create are saved automatically.</div>';
    return;
  }

  list.innerHTML = items.map((item) => {
    const when = new Date(item.created_at).toLocaleString([], {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
    return `
      <div class="history-item" data-id="${item.id}">
        <div class="history-title">${escapeHtml(item.title)}</div>
        <div class="history-meta">
          <span>${when} · ${clock(item.duration)} · ${escapeHtml(item.model)}</span>
          <button class="history-del" data-del="${item.id}" title="Delete">✕</button>
        </div>
      </div>`;
  }).join("");

  list.querySelectorAll(".history-item").forEach((el) => {
    el.addEventListener("click", async (event) => {
      if (event.target.dataset.del) return;
      try {
        renderResult(await api(`/api/history/${el.dataset.id}`));
        closeDrawer();
        $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (error) { toast(error.message, true); }
    });
  });

  list.querySelectorAll("[data-del]").forEach((button) => {
    button.addEventListener("click", async (event) => {
      event.stopPropagation();
      const id = button.dataset.del;
      if (!confirm("Delete this transcript and its audio?")) return;
      try {
        await api(`/api/history/${id}`, { method: "DELETE" });
        if (state.current && state.current.id === id) {
          $("result").hidden = true;
          state.current = null;
        }
        refreshHistory();
        toast("Deleted");
      } catch (error) { toast(error.message, true); }
    });
  });
}

function openDrawer() { $("drawer").hidden = false; $("scrim").hidden = false; refreshHistory(); }
function closeDrawer() { $("drawer").hidden = true; $("scrim").hidden = true; }

$("btn-history").addEventListener("click", openDrawer);
$("btn-drawer-close").addEventListener("click", closeDrawer);
$("scrim").addEventListener("click", closeDrawer);

/* ---- help -------------------------------------------------------------- */

function showHelp(section) {
  document.querySelectorAll("[data-help]").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.help === section);
  });
  $("help-body").innerHTML = window.HELP[section] || "";
  $("help-body").scrollTop = 0;
}

$("btn-help").addEventListener("click", () => { $("help").hidden = false; showHelp("usage"); });
$("btn-help-close").addEventListener("click", () => { $("help").hidden = true; });
$("help").addEventListener("click", (event) => {
  if (event.target === $("help")) $("help").hidden = true;
});
document.querySelectorAll("[data-help]").forEach((tab) => {
  tab.addEventListener("click", () => showHelp(tab.dataset.help));
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("help").hidden) $("help").hidden = true;
  else if (!$("drawer").hidden) closeDrawer();
});

/* ---- option wiring ----------------------------------------------------- */

$("opt-model").addEventListener("change", updateModelHint);
$("opt-cleanup").addEventListener("change", () => { updateCleanupHint(); syncOptionState(); });
["opt-task", "opt-language", "opt-diarization", "opt-num-speakers", "opt-autocopy"]
  .forEach((id) => $(id).addEventListener("change", syncOptionState));
$("options").addEventListener("toggle", savePrefs);

$("opt-temperature").addEventListener("input", (event) => {
  $("temp-value").textContent = Number(event.target.value).toFixed(1);
});
$("opt-temperature").addEventListener("change", savePrefs);

$("opt-prompt").addEventListener("input", (event) => {
  // Groq truncates the prompt at 224 tokens; ~4 characters per token.
  const limit = 224 * 4;
  const used = event.target.value.length;
  $("prompt-count").textContent = used ? `${used}/${limit}` : "";
  $("prompt-count").style.color = used > limit ? "var(--warn)" : "";
});
$("opt-prompt").addEventListener("change", savePrefs);

boot();
})();
