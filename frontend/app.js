"use strict";

// Talks only to this server's own API (relative paths) - no processing logic here,
// this file just calls the backend and renders what it returns.
const POLL_INTERVAL_MS = 2000;
const YOUTUBE_URL_RE = /^(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|shorts\/|live\/)|youtu\.be\/)[\w-]{11}/i;

const els = {
  form: document.getElementById("job-form"),
  url: document.getElementById("url"),
  urlError: document.getElementById("url-error"),
  durationOptions: document.getElementById("duration-options"),
  customDuration: document.getElementById("custom-duration"),
  numClips: document.getElementById("num-clips"),
  generateBtn: document.getElementById("generate-btn"),

  formCard: document.getElementById("form-card"),
  statusCard: document.getElementById("status-card"),
  statusTitle: document.getElementById("status-title"),
  statusBadge: document.getElementById("status-badge"),
  progressFill: document.getElementById("progress-fill"),
  statusDetail: document.getElementById("status-detail"),
  cancelPollBtn: document.getElementById("cancel-poll-btn"),

  errorCard: document.getElementById("error-card"),
  errorDetail: document.getElementById("error-detail"),
  retryBtn: document.getElementById("retry-btn"),

  resultsCard: document.getElementById("results-card"),
  shortsGrid: document.getElementById("shorts-grid"),
  emptyNote: document.getElementById("empty-note"),
  downloadAllBtn: document.getElementById("download-all-btn"),
  newJobBtn: document.getElementById("new-job-btn"),
};

let selectedDuration = 60;
let pollTimer = null;
let currentJobId = null;

// ---- duration chips ----
els.durationOptions.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    els.durationOptions.querySelectorAll(".chip").forEach((c) => c.classList.remove("active"));
    chip.classList.add("active");
    if (chip.dataset.duration === "custom") {
      els.customDuration.classList.remove("hidden");
      els.customDuration.focus();
      selectedDuration = null; // resolved from the input at submit time
    } else {
      els.customDuration.classList.add("hidden");
      selectedDuration = parseInt(chip.dataset.duration, 10);
    }
  });
});

function resolveDuration() {
  const activeChip = els.durationOptions.querySelector(".chip.active");
  if (activeChip && activeChip.dataset.duration !== "custom") {
    return parseInt(activeChip.dataset.duration, 10);
  }
  const value = parseInt(els.customDuration.value, 10);
  return Number.isFinite(value) ? value : null;
}

// ---- view switching ----
function showOnly(card) {
  [els.formCard, els.statusCard, els.errorCard, els.resultsCard].forEach((c) => {
    c.classList.toggle("hidden", c !== card);
  });
}

function resetToForm() {
  stopPolling();
  currentJobId = null;
  showOnly(els.formCard);
  els.generateBtn.disabled = false;
  els.generateBtn.textContent = "Generate Shorts";
}

els.newJobBtn.addEventListener("click", resetToForm);
els.retryBtn.addEventListener("click", resetToForm);

// ---- submit ----
els.form.addEventListener("submit", async (event) => {
  event.preventDefault();
  els.urlError.textContent = "";

  const url = els.url.value.trim();
  if (!url) {
    els.urlError.textContent = "Paste a YouTube URL first.";
    return;
  }
  if (!YOUTUBE_URL_RE.test(url)) {
    els.urlError.textContent = "That doesn't look like a YouTube video URL.";
    return;
  }

  const duration = resolveDuration();
  if (duration !== null && (duration < 15 || duration > 180)) {
    els.urlError.textContent = "Custom duration must be between 15 and 180 seconds.";
    return;
  }

  const numClipsValue = els.numClips.value;
  const body = { url };
  if (duration !== null) body.clip_duration = duration;
  if (numClipsValue) body.num_clips = parseInt(numClipsValue, 10);

  els.generateBtn.disabled = true;
  els.generateBtn.textContent = "Starting…";

  try {
    const res = await fetch("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not start the job.");
    currentJobId = data.job_id;
    showOnly(els.statusCard);
    updateStatusView(data);
    startPolling();
  } catch (err) {
    showError(err.message || "Network error - is the server running?");
  } finally {
    els.generateBtn.disabled = false;
    els.generateBtn.textContent = "Generate Shorts";
  }
});

// ---- polling ----
function startPolling() {
  stopPolling();
  els.cancelPollBtn.classList.remove("hidden");
  pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS);
}

function stopPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  els.cancelPollBtn.classList.add("hidden");
}

els.cancelPollBtn.addEventListener("click", () => {
  stopPolling();
  els.statusDetail.textContent = "Stopped watching. The job keeps running on the server.";
});

async function pollOnce() {
  if (!currentJobId) return;
  try {
    const res = await fetch(`/jobs/${currentJobId}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Could not check job status.");
    updateStatusView(data);
    if (data.status === "completed") {
      stopPolling();
      await showResults(data);
    } else if (data.status === "failed") {
      stopPolling();
      showError(data.error || "Processing failed.");
    }
  } catch (err) {
    stopPolling();
    showError(err.message || "Lost connection to the server.");
  }
}

// stage -> (label, progress fraction floor)
const STAGE_INFO = {
  queued: ["Queued…", 0.02],
  starting: ["Starting…", 0.05],
  transcript: ["Reading the transcript…", 0.15],
  moments: ["Gemini is picking the best moments…", 0.25],
  clipping: ["Cutting clips…", 0.3],
  formatting: ["Formatting vertical Shorts + captions…", 0.6],
  done: ["Finishing up…", 0.98],
  failed: ["Failed", 0],
};

function updateStatusView(job) {
  els.statusBadge.textContent = job.status;
  els.statusBadge.className = "status-badge " + job.status;

  const [label, floor] = STAGE_INFO[job.stage] || ["Working…", 0.1];
  let fraction = floor;
  const p = job.progress || {};
  if (typeof p.done === "number" && typeof p.total === "number" && p.total > 0) {
    const within = p.done / p.total;
    // clipping spans 0.30-0.60, formatting spans 0.60-0.95 of the bar
    if (job.stage === "clipping") fraction = 0.3 + within * 0.3;
    if (job.stage === "formatting") fraction = 0.6 + within * 0.35;
  }
  els.progressFill.style.width = `${Math.round(fraction * 100)}%`;

  let detail = label;
  if (job.stage === "clipping" && p.total) detail = `Cutting clip ${p.done} of ${p.total}…`;
  if (job.stage === "formatting" && p.total) detail = `Formatting Short ${p.done} of ${p.total}…`;
  if (job.stage === "moments" && p.count) detail = `Found ${p.count} moment(s) to turn into Shorts…`;
  els.statusTitle.textContent = job.status === "running" ? "Processing…" : "Queued";
  els.statusDetail.textContent = detail;
}

function showError(message) {
  showOnly(els.errorCard);
  els.errorDetail.textContent = message;
}

// ---- results ----
async function showResults(job) {
  const result = job.result || {};
  const shorts = result.shorts || [];

  els.shortsGrid.innerHTML = "";
  if (shorts.length === 0) {
    els.emptyNote.classList.remove("hidden");
    els.downloadAllBtn.classList.add("hidden");
    showOnly(els.resultsCard);
    return;
  }
  els.emptyNote.classList.add("hidden");
  els.downloadAllBtn.classList.remove("hidden");
  els.downloadAllBtn.onclick = () => {
    window.location.href = `/jobs/${currentJobId}/download-all`;
  };

  try {
    const res = await fetch(`/jobs/${currentJobId}/shorts`);
    const data = await res.json();
    const entries = (data.shorts && data.shorts.length) ? data.shorts
      : shorts.map((path) => ({ filename: path.split("/").pop(), url: null, title: path }));

    for (const entry of entries) {
      const url = entry.url || `/files/shorts/${entry.filename}`;
      const card = document.createElement("div");
      card.className = "short-card";
      card.innerHTML = `
        <video src="${url}" controls preload="metadata" playsinline></video>
        <div class="short-meta">
          <span class="short-title" title="${escapeHtml(entry.title || entry.filename)}">
            ${escapeHtml(entry.title || entry.filename)}
          </span>
          <a class="download-link" href="${url}" download>Download</a>
        </div>`;
      els.shortsGrid.appendChild(card);
    }
  } catch (err) {
    showError("Shorts were generated, but the list could not be loaded: " + err.message);
    return;
  }
  showOnly(els.resultsCard);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}
