let jobId = null;

const formBox = document.getElementById("formBox");
const urlEl = document.getElementById("url");
const goEl = document.getElementById("go");

const progressBox = document.getElementById("progressBox");
const statusText = document.getElementById("statusText");
const statusIcon = document.getElementById("statusIcon");
const barFill = document.getElementById("barFill");
const stepsEl = document.getElementById("steps");

const resultBox = document.getElementById("resultBox");
const resultHeadline = document.getElementById("resultHeadline");
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
      pastePack.classList.remove("hidden");
      copyBtn.classList.remove("hidden");
      againBtn.textContent = "Transcribe another";
      pastePack.value = data.transcript || "";
      return;
    }

    if (data.state === "error") {
      statusIcon.textContent = "";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = "Video failed to transcribe.";
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
  resultHeadline.textContent = "";
  pastePack.classList.remove("hidden");
  copyBtn.classList.remove("hidden");
  copyBtn.textContent = "Copy";
  againBtn.textContent = "Transcribe another";
}

goEl.addEventListener("click", async () => {
  const url = urlEl.value.trim();
  if (!url) return;
  const endpoint = "/api/jobs/start";
  const headers = { "Content-Type": "application/json" };
  const body = JSON.stringify({ url });

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
    goEl.textContent = "Transcribe";
  }
});

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
  resetUI();
});
