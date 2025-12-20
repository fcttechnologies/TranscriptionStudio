let jobId = null;

const formBox = document.getElementById("formBox");
const urlEl = document.getElementById("url");
const urlInputBox = document.getElementById("urlInputBox");

const titleGroup = document.getElementById("titleGroup");
const titleEl = document.getElementById("customTitle");
const goEl = document.getElementById("go");

const saveMarkdownEl = document.getElementById("saveMarkdown");

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
      resultHeadline.textContent = "Transcript ready.";
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
  goEl.textContent = "Transcribe";
}

goEl.addEventListener("click", async () => {
  const custom_title = titleEl.value.trim();

  const save_markdown = saveMarkdownEl.checked;

  const url = urlEl.value.trim();
  if (!url) return;
  const endpoint = "/api/jobs/start";
  const headers = { "Content-Type": "application/json" };
  const body = JSON.stringify({ url, custom_title, save_markdown });

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
      headers: headers,
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
  titleEl.value = "";

  saveMarkdownEl.checked = false;
  resetUI();
});
