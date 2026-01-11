// Track the current job so the UI can poll for progress.
let jobId = null;

// Form elements for starting a transcription.
const formBox = document.getElementById("formBox");
const urlEl = document.getElementById("url");
const goEl = document.getElementById("go");

// Progress UI elements updated during polling.
const progressBox = document.getElementById("progressBox");
const statusText = document.getElementById("statusText");
const statusIcon = document.getElementById("statusIcon");
const barFill = document.getElementById("barFill");
const stepsEl = document.getElementById("steps");

// Result UI elements shown when the transcript is ready or failed.
const resultBox = document.getElementById("resultBox");
const resultHeadline = document.getElementById("resultHeadline");
const pastePack = document.getElementById("pastePack");
const copyBtn = document.getElementById("copy");
const againBtn = document.getElementById("again");

// Small helper to pause between polling loops.
function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// Render the list of steps with the current active index.
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

// Poll the server until the job is done or errored.
async function pollJob(id) {
  while (true) {
    const res = await fetch(`/api/jobs/${id}`);
    const data = await res.json();

    // Update headline status and progress bar.
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
      // Populate the transcript output area.
      statusIcon.textContent = "";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = "Transcript ready.";
      pastePack.classList.remove("hidden");

      const existingErr = resultBox.querySelector(".error-msg");
      if (existingErr) existingErr.remove();

      copyBtn.classList.remove("hidden");
      againBtn.textContent = "Transcribe another";
      pastePack.value = data.transcript || "";
      return;
    }

    if (data.state === "error") {
      // Surface backend errors to the user.
      statusIcon.textContent = "";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = "Video failed to transcribe.";

      if (data.error) {
        const errP = document.createElement("p");
        errP.textContent = data.error;
        errP.style.color = "red";
        errP.style.marginTop = "1rem";

        const existingErr = resultBox.querySelector(".error-msg");
        if (existingErr) existingErr.remove();

        errP.classList.add("error-msg");
        resultBox.appendChild(errP);
      }

      pastePack.value = "";
      pastePack.classList.add("hidden");
      copyBtn.classList.add("hidden");
      againBtn.textContent = "Try again";
      return;
    }

    await sleep(800);
  }
}

// Reset UI state when starting over.
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

  const existingErr = resultBox.querySelector(".error-msg");
  if (existingErr) existingErr.remove();
}

// Start a new job when the user clicks "Transcribe".
goEl.addEventListener("click", async () => {
  const url = urlEl.value.trim();
  if (!url) return;
  const endpoint = "/api/jobs/start";
  const headers = { "Content-Type": "application/json" };
  const body = JSON.stringify({ url });

  formBox.classList.add("hidden");
  progressBox.classList.remove("hidden");
  resultBox.classList.add("hidden");

  const existingErr = resultBox.querySelector(".error-msg");
  if (existingErr) existingErr.remove();

  statusIcon.textContent = "";
  statusText.textContent = "Queued…";
  barFill.style.width = "2%";
  renderSteps(["Queued…"], 0);

  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: headers,
      body: body,
    });

    if (!res.ok) {
      throw new Error((await res.text()) || "Request failed");
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

// Copy the transcript to the clipboard, with a fallback for older browsers.
copyBtn.addEventListener("click", async () => {
  const text = pastePack.value || "";
  if (!text) return;

  try {
    await navigator.clipboard.writeText(text);
    copyBtn.textContent = "Copied!";
    setTimeout(() => (copyBtn.textContent = "Copy"), 900);
    return;
  } catch (_) {
    // Fall through to the legacy copy path.
  }

  try {
    pastePack.removeAttribute("readonly");
    pastePack.setAttribute("contenteditable", "true");
    pastePack.focus();
    pastePack.value = text;
    pastePack.setSelectionRange(0, text.length);

    const ok = document.execCommand("copy");
    copyBtn.textContent = ok ? "Copied!" : "Tap & Hold to Copy";
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

// Reset and allow the user to start over.
againBtn.addEventListener("click", () => {
  urlEl.value = "";
  resetUI();
});
