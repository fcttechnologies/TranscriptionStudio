let jobId = null;

const formBox = document.getElementById("formBox");
const urlEl = document.getElementById("url");
const fileInput = document.getElementById("fileInput");
const tabUrl = document.getElementById("tabUrl");
const tabPdf = document.getElementById("tabPdf");
const urlInputBox = document.getElementById("urlInputBox");
const fileInputBox = document.getElementById("fileInputBox");

const titleGroup = document.getElementById("titleGroup");
const titleEl = document.getElementById("customTitle");
const goEl = document.getElementById("go");
const transcriptOnlyEl = document.getElementById("transcriptOnly");
const saveMarkdownEl = document.getElementById("saveMarkdown");

let mode = "video"; // "video" or "pdf"

const progressBox = document.getElementById("progressBox");
const statusText = document.getElementById("statusText");
const statusIcon = document.getElementById("statusIcon");
const barFill = document.getElementById("barFill");
const stepsEl = document.getElementById("steps");

const resultBox = document.getElementById("resultBox");
const resultHeadline = document.getElementById("resultHeadline");
const filePath = document.getElementById("filePath");
const pastePack = document.getElementById("pastePack");
const copyBtn = document.getElementById("copy");
const againBtn = document.getElementById("again");

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function renderSteps(steps, activeIndex) {
  stepsEl.innerHTML = "";
  steps.forEach((s, idx) => {
    const li = document.createElement("li");
    li.textContent = s;
    if (idx < activeIndex) li.classList.add("done");
    if (idx === activeIndex) li.classList.add("active");
    stepsEl.appendChild(li);
  });
}

async function pollJob(id) {
  while (true) {
    const res = await fetch(`/api/jobs/${id}`);
    const data = await res.json();

    statusText.textContent = data.stage_text || "Working…";
    barFill.style.width = `${data.progress || 0}%`;

    const isTranscriptOnly = Boolean(data.transcript_only);
    const saveMarkdown = Boolean(data.save_markdown);

    const steps = data.steps || [];
    const active = data.active_step_index ?? 0;

    if (data.state === "done") {
      renderSteps(steps, steps.length);
    } else if (data.state === "error") {
      renderSteps(steps, active);
    } else {
      renderSteps(steps, active);
    }

    if (data.state === "done") {
      statusIcon.textContent = "";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = isTranscriptOnly ? "Transcript ready." : "Video summarized.";
      if (saveMarkdown && data.file_path) {
        filePath.classList.remove("hidden");
        const fileName = data.file_path.split(/[\\/]/).pop() || data.file_path;
        filePath.innerHTML = `Saved: <code>${fileName}</code>`;
      } else {
        filePath.classList.add("hidden");
        filePath.textContent = "";
      }
      pastePack.classList.remove("hidden");
      copyBtn.classList.remove("hidden");
      againBtn.textContent = "Summarize another";
      pastePack.value = data.clipboard_payload || "";
      return;
    }

    if (data.state === "error") {
      statusIcon.textContent = "";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = "Video failed to summarize.";
      filePath.textContent = data.error || "Unknown error";
      pastePack.value = "";
      pastePack.classList.add("hidden");
      copyBtn.classList.add("hidden");
      againBtn.textContent = "Try again";
      return;
    }

    await sleep(800);
  }
}

function resetUI() {
  jobId = null;
  formBox.classList.remove("hidden");
  progressBox.classList.add("hidden");
  resultBox.classList.add("hidden");
  statusIcon.textContent = "";
  statusText.textContent = "";
  barFill.style.width = "0%";
  stepsEl.innerHTML = "";
  pastePack.value = "";
  filePath.innerHTML = "";
  filePath.classList.add("hidden");
  resultHeadline.textContent = "";
  pastePack.classList.remove("hidden");
  copyBtn.classList.remove("hidden");
  copyBtn.textContent = "Copy";
  againBtn.textContent = "Summarize another";
  updateTitleVisibility();
  updateGoButtonLabel();
}

function updateTitleVisibility() {
  const show = saveMarkdownEl.checked;
  titleGroup.classList.toggle("hidden", !show);
  if (!show) {
    titleEl.value = "";
  }
}

function updateGoButtonLabel() {
  goEl.textContent = transcriptOnlyEl.checked ? "Transcribe / Extract" : "Summarize";
}

function setMode(m) {
  mode = m;
  if (mode === "video") {
    tabUrl.classList.add("active");
    tabPdf.classList.remove("active");
    urlInputBox.classList.remove("hidden");
    fileInputBox.classList.add("hidden");
    titleEl.placeholder = "Leave blank to auto-title";
  } else {
    tabUrl.classList.remove("active");
    tabPdf.classList.add("active");
    urlInputBox.classList.add("hidden");
    fileInputBox.classList.remove("hidden");
    titleEl.placeholder = "Optional title override";
  }
}

tabUrl.addEventListener("click", () => setMode("video"));
tabPdf.addEventListener("click", () => setMode("pdf"));

goEl.addEventListener("click", async () => {
  const custom_title = titleEl.value.trim();
  const transcript_only = transcriptOnlyEl.checked;
  const save_markdown = saveMarkdownEl.checked;

  let endpoint = "/api/start/url";
  let body = null;
  let headers = {};

  if (mode === "video") {
    const url = urlEl.value.trim();
    if (!url) return;
    endpoint = "/api/start/url";
    headers = { "Content-Type": "application/json" };
    body = JSON.stringify({ url, custom_title, transcript_only, save_markdown });
  } else {
    if (!fileInput.files.length) return;
    const file = fileInput.files[0];
    endpoint = "/api/start/file";
    // No Content-Type header for FormData, browser sets it with boundary
    const fd = new FormData();
    fd.append("file", file);
    fd.append("transcript_only", transcript_only);
    fd.append("save_markdown", save_markdown);
    if (custom_title) fd.append("custom_title", custom_title);
    body = fd;
  }

  formBox.classList.add("hidden");
  progressBox.classList.remove("hidden");
  resultBox.classList.add("hidden");

  statusIcon.textContent = "";
  statusText.textContent = "Queued…";
  barFill.style.width = "2%";
  renderSteps(["Queued…"], 0);

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: headers, // Empty for file
      body: body
    });

    if (!res.ok) {
      throw new Error(await res.text() || "Request failed");
    }

    const data = await res.json();
    jobId = data.job_id;
    await pollJob(jobId);
  } catch (err) {
    statusText.textContent = "Error";
    renderSteps([`Error: ${err.message}`], 0);
    goEl.textContent = "Try Again";
  }
});

saveMarkdownEl.addEventListener("change", updateTitleVisibility);
transcriptOnlyEl.addEventListener("change", updateGoButtonLabel);

updateTitleVisibility();
updateGoButtonLabel();

copyBtn.addEventListener("click", async () => {
  const text = pastePack.value || "";
  if (!text) return;

  try {
    await navigator.clipboard.writeText(text);
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = "Copy"), 900);
    return;
  } catch (_) {
  }

  try {
    pastePack.removeAttribute("readonly");
    pastePack.setAttribute("contenteditable", "true");
    pastePack.focus();
    pastePack.value = text;
    pastePack.setSelectionRange(0, text.length);

    const ok = document.execCommand("copy");
    copyBtn.textContent = ok ? "Copied!" : "Tap & Hold to Copy";

    if (!ok) {
    }
  } catch (e) {
    copyBtn.textContent = "Tap & Hold to Copy";
  } finally {
    setTimeout(() => {
      pastePack.setAttribute("readonly", "readonly");
      pastePack.removeAttribute("contenteditable");
      copyBtn.textContent = "Copy";
    }, 1200);
  }
});

againBtn.addEventListener("click", () => {
  urlEl.value = "";
  fileInput.value = ""; // Reset file
  titleEl.value = "";
  transcriptOnlyEl.checked = false;
  saveMarkdownEl.checked = false;
  resetUI();
});
