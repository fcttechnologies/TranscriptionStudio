let jobId = null;

const formBox = document.getElementById("formBox");
const urlEl = document.getElementById("url");
const titleEl = document.getElementById("customTitle");
const goEl = document.getElementById("go");
const transcriptOnlyEl = document.getElementById("transcriptOnly");
const saveMarkdownEl = document.getElementById("saveMarkdown");
const titleGroup = document.getElementById("titleGroup");

const progressBox = document.getElementById("progressBox");
const statusText = document.getElementById("statusText");
const statusIcon = document.getElementById("statusIcon");
const barFill = document.getElementById("barFill");
const stepsEl = document.getElementById("steps");

const resultBox = document.getElementById("resultBox");
const resultHeadline = document.getElementById("resultHeadline");
const filePath = document.getElementById("filePath");
const optionMeta = document.getElementById("optionMeta");
const clipboardSection = document.getElementById("clipboardSection");
const pastePack = document.getElementById("pastePack");
const copyBtn = document.getElementById("copy");
const againBtn = document.getElementById("again");

function sleep(ms){ return new Promise(r=>setTimeout(r,ms)); }

function syncTitleVisibility(){
  if(!titleGroup) return;
  if(saveMarkdownEl.checked){
    titleGroup.classList.remove("hidden");
  } else {
    titleGroup.classList.add("hidden");
    titleEl.value = "";
  }
}

function renderSteps(steps, activeIndex){
  stepsEl.innerHTML = "";
  steps.forEach((s, idx) => {
    const li = document.createElement("li");
    li.textContent = s;
    if (idx < activeIndex) li.classList.add("done");
    if (idx === activeIndex) li.classList.add("active");
    stepsEl.appendChild(li);
  });
}

async function pollJob(id){
  while(true){
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

    if(data.state === "done"){
      statusIcon.textContent = "✅";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = isTranscriptOnly ? "Transcript ready." : "Video summarized.";

      if (saveMarkdown) {
        const displayName = data.file_name || data.custom_title || "Markdown saved.";
        filePath.textContent = `Saved: ${displayName}`;
        filePath.classList.remove("hidden");
      } else {
        filePath.textContent = "";
        filePath.classList.add("hidden");
      }

      optionMeta.textContent = "";
      optionMeta.classList.add("hidden");

      if (clipboardSection) {
        clipboardSection.classList.add("hidden");
      }

      pastePack.value = "";
      return;
    }

    if(data.state === "error"){
      statusIcon.textContent = "⚠️";
      resultBox.classList.remove("hidden");
      resultHeadline.textContent = "Video failed to summarize.";
      filePath.textContent = data.error || "Unknown error";
      filePath.classList.remove("hidden");
      optionMeta.textContent = "";
      optionMeta.classList.add("hidden");
      if (clipboardSection) {
        clipboardSection.classList.add("hidden");
      }
      pastePack.value = "";
      return;
    }

    await sleep(800);
  }
}

function resetUI(){
  jobId = null;
  formBox.classList.remove("hidden");
  progressBox.classList.add("hidden");
  resultBox.classList.add("hidden");
  statusIcon.textContent = "";
  statusText.textContent = "";
  barFill.style.width = "0%";
  stepsEl.innerHTML = "";
  filePath.classList.add("hidden");
  pastePack.value = "";
  filePath.textContent = "";
  optionMeta.textContent = "";
  optionMeta.classList.add("hidden");
  resultHeadline.textContent = "";
  if (clipboardSection) {
    clipboardSection.classList.add("hidden");
  }
  syncTitleVisibility();
}

goEl.addEventListener("click", async () => {
  const url = urlEl.value.trim();
  const custom_title = titleEl.value.trim();
  const transcript_only = transcriptOnlyEl.checked;
  const save_markdown = saveMarkdownEl.checked;
  if(!url) return;

  formBox.classList.add("hidden");
  progressBox.classList.remove("hidden");
  resultBox.classList.add("hidden");

  statusIcon.textContent = "";
  statusText.textContent = "Queued…";
  barFill.style.width = "2%";
  renderSteps(["Queued…"], 0);

  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: {"Content-Type":"application/json"},
    body: JSON.stringify({url, custom_title, transcript_only, save_markdown})
  });

  const data = await res.json();
  jobId = data.job_id;
  await pollJob(jobId);
});

saveMarkdownEl.addEventListener("change", syncTitleVisibility);
syncTitleVisibility();

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
  transcriptOnlyEl.checked = false;
  saveMarkdownEl.checked = false;
  resetUI();
});
