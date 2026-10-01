"use strict";

const DRIVER = { driver_id: "driver-demo-001", truck_id: "truck-8821" };
const POLL_MS = 5000;

const $ = (id) => document.getElementById(id);

const ui = {
  orb: $("recordButton"),
  orbLabel: $("orbLabel"),
  orbIcon: $("orbIcon"),
  actionsBlock: $("actionsBlock"),
  traceBlock: $("traceBlock"),
  ring: $("levelRing"),
  status: $("status"),
  thread: $("thread"),
  newReport: $("newReport"),
  typeForm: $("typeForm"),
  typeInput: $("typeInput"),
  guidance: $("guidance"),
  badge: $("severityBadge"),
  decision: $("decision"),
  response: $("responseText"),
  replay: $("replayButton"),
  issueRef: $("issueRef"),
  actions: $("actionsList"),
  pipeline: $("pipeline"),
  audio: $("audioPlayer"),
  reasoningPill: $("reasoningPill"),
  voicePill: $("voicePill"),
  incidentList: $("incidentList"),
  categoryChart: $("categoryChart"),
  chartTip: $("chartTip"),
  severityFilter: $("severityFilter"),
  statusFilter: $("statusFilter"),
  lastUpdated: $("lastUpdated"),
};

const DECISION_LABELS = {
  STOP_SAFELY: "Pull over safely",
  CONTINUE_WITH_CAUTION: "Continue carefully",
  SEND_MESSAGE: "Dispatch notified",
  LOG_ONLY: "Logged for review",
};

const SEVERITY_LABELS = { critical: "Critical", warning: "Warning", low: "Low risk", idle: "Waiting for a report" };
const SEVERITY_ICONS = { critical: "i-critical", warning: "i-warning", low: "i-low", idle: "i-low" };

const state = {
  busy: false,
  listening: false,
  lastSpoken: null,
  conversationId: null,
  awaitingAnswer: false,
  events: [],
  openConversations: new Set(),
  view: "driver",
  severity: "",
  status: "",
  seenIds: null,
  pollTimer: null,
};

/* ---------- Small DOM helpers ---------- */

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else if (key.includes("-") || key === "role") node.setAttribute(key, value);
    else node[key] = value;
  }
  for (const child of [].concat(children)) {
    if (child != null) node.append(child);
  }
  return node;
}

function icon(id) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `#${id}`);
  svg.append(use);
  svg.setAttribute("aria-hidden", "true");
  return svg;
}

function severityBadge(severity) {
  return el("span", { class: "badge", "data-severity": severity }, [
    icon(SEVERITY_ICONS[severity] || "i-low"),
    el("span", { text: SEVERITY_LABELS[severity] || severity }),
  ]);
}

function timeAgo(iso) {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function setStatus(html) {
  ui.status.innerHTML = html;
}

/* ---------- System status ---------- */

async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    const health = await res.json();
    const llm = health.reasoning.provider === "groq";
    setPill(ui.reasoningPill, llm ? "on" : "fallback", llm ? `Groq · ${shortModel(health.reasoning.model)}` : "Rules engine");
    const eleven = health.voice === "elevenlabs";
    setPill(ui.voicePill, eleven ? "on" : "fallback", eleven ? "ElevenLabs voice" : "Browser voice");
    setVoiceEngine(health.speech_to_text === "groq-whisper");
    $("storageNote").hidden = health.storage !== "ephemeral";
  } catch {
    setPill(ui.reasoningPill, "down", "Backend offline");
    setPill(ui.voicePill, "down", "Voice offline");
    setVoiceEngine(false);
  }
}

function setPill(pill, pillState, text) {
  pill.dataset.state = pillState;
  pill.querySelector(".pill-text").textContent = text;
}

function shortModel(model) {
  return (model || "").split("/").pop();
}

/* ---------- Voice input ---------- */
// Two engines. "server": record audio and transcribe it with Groq Whisper, which
// behaves the same in every browser. "browser": the Web Speech API, used when the
// server has no speech-to-text configured.

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
const canRecord = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
const MAX_RECORD_MS = 30000;

state.sttEngine = SpeechRecognition ? "browser" : null;

function setVoiceEngine(serverAvailable) {
  if (serverAvailable && canRecord) state.sttEngine = "server";
  else if (SpeechRecognition) state.sttEngine = "browser";
  else state.sttEngine = null;

  ui.orb.disabled = !state.sttEngine;
  if (!state.sttEngine) {
    ui.orbLabel.textContent = "Voice isn't supported here";
    setStatus("Type your report below instead");
  }
}

function setListeningUI(on) {
  ui.orb.classList.toggle("is-listening", on);
  ui.orb.setAttribute("aria-pressed", String(on));
  ui.orb.setAttribute("aria-label", on ? "Stop speaking" : "Start speaking");
  ui.orbIcon.firstElementChild.setAttribute("href", on ? "#i-stop" : "#i-mic");
  if (on) ui.orbLabel.textContent = "Listening…";
  else updateOrbLabel();
  if (on) {
    setStatus(spaceHeld ? "Release <kbd>Space</kbd> when you're done" : "Tap again when you're done");
    showTranscript("", true);
  }
}

function micErrorMessage(error) {
  if (error?.name === "NotAllowedError" || error?.name === "SecurityError") {
    return "Microphone is blocked. Allow it in your browser's settings for this site, or type below.";
  }
  if (error?.name === "NotFoundError") return "No microphone found. Type below instead.";
  return "Couldn't start the microphone. Type below instead.";
}

/* Engine 1: record + server transcription */
const recorder = {
  media: null,
  stream: null,
  chunks: [],
  timer: null,
  startedAt: 0,
  stopRequested: false,

  async start() {
    this.stopRequested = false;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
    } catch (error) {
      state.listening = false;
      setStatus(micErrorMessage(error));
      return;
    }

    const mimeType = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find(
      (type) => MediaRecorder.isTypeSupported?.(type)
    );
    this.chunks = [];
    this.media = new MediaRecorder(this.stream, mimeType ? { mimeType } : undefined);
    this.media.ondataavailable = (event) => event.data.size && this.chunks.push(event.data);
    this.media.onstop = () => this.finish();
    this.media.start(250);
    this.startedAt = Date.now();
    this.timer = setTimeout(() => this.stop(), MAX_RECORD_MS);

    setListeningUI(true);
    levelMeter.start(this.stream);
    if (this.stopRequested) this.stop(); // released Space before the mic was ready
  },

  stop() {
    this.stopRequested = true;
    if (this.media?.state === "recording") this.media.stop();
  },

  async finish() {
    clearTimeout(this.timer);
    this.stream?.getTracks().forEach((track) => track.stop());
    levelMeter.stop();
    state.listening = false;
    setListeningUI(false);

    const type = this.media.mimeType || this.chunks[0]?.type || "audio/webm";
    const blob = new Blob(this.chunks, { type });
    if (Date.now() - this.startedAt < 600 || blob.size < 1500) {
      showTranscript("");
      setStatus("That was too short. Tap, speak, then tap again.");
      return;
    }
    await transcribeAndSend(blob);
  },
};

function audioFilename(type) {
  if (type.includes("mp4") || type.includes("aac")) return "clip.mp4";
  if (type.includes("ogg")) return "clip.ogg";
  if (type.includes("wav")) return "clip.wav";
  return "clip.webm";
}

async function transcribeAndSend(blob) {
  state.busy = true;
  ui.orb.classList.add("is-thinking");
  ui.orbLabel.textContent = "Transcribing…";
  showTranscript("Transcribing…");
  setStatus("One moment");

  let text = "";
  try {
    const form = new FormData();
    form.append("audio", blob, audioFilename(blob.type));
    const res = await fetch("/api/transcribe", { method: "POST", body: form });
    if (!res.ok) throw new Error(`Transcription failed with status ${res.status}`);
    text = (await res.json()).transcript;
  } catch (error) {
    console.error(error);
    setStatus("Couldn't transcribe that. Try again, or type below.");
  } finally {
    state.busy = false;
    ui.orb.classList.remove("is-thinking");
    updateOrbLabel();
  }

  if (!text) {
    showTranscript("");
    if (ui.status.textContent === "One moment") setStatus("Didn't catch that. Try again.");
    return;
  }
  sendReport(text, "Whisper");
}

/* Engine 2: browser Web Speech API */
let recognition = null;
let finalTranscript = "";
let interimTranscript = "";

if (SpeechRecognition) {
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.interimResults = true;
  recognition.continuous = false;

  recognition.onstart = () => {
    finalTranscript = "";
    interimTranscript = "";
    setListeningUI(true);
    levelMeter.start(null); // a second mic capture can cancel recognition in Safari
  };

  recognition.onresult = (event) => {
    let interim = "";
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const result = event.results[i];
      if (result.isFinal) finalTranscript += result[0].transcript;
      else interim += result[0].transcript;
    }
    interimTranscript = interim;
    showTranscript((finalTranscript + interim).trim(), !finalTranscript);
  };

  recognition.onerror = (event) => {
    const messages = {
      "not-allowed": "Microphone is blocked. Allow it in your browser's settings for this site, or type below.",
      "service-not-allowed": "Speech recognition is off. On a Mac, turn on Dictation in System Settings → Keyboard, or type below.",
      "no-speech": "Didn't catch that. Try again.",
      "audio-capture": "No microphone found. Type below instead.",
      network: "Speech service unreachable. Type below instead.",
      aborted: "",
    };
    state.voiceError = messages[event.error] ?? "Voice input stopped. Try again.";
  };

  recognition.onend = () => {
    state.listening = false;
    setListeningUI(false);
    levelMeter.stop();

    // Safari often ends without marking the last result final, so fall back to the interim text.
    const text = (finalTranscript || interimTranscript).trim();
    if (text) {
      sendReport(text, "browser");
    } else {
      setStatus(state.voiceError || "Didn't catch that. Try again.");
      showTranscript("");
    }
    state.voiceError = null;
  };
}

/* Controls */
function startListening() {
  if (state.listening || state.busy || !state.sttEngine) return;
  stopSpeaking();
  state.listening = true;

  if (state.sttEngine === "server") {
    recorder.start();
    return;
  }
  try {
    recognition.start();
  } catch (error) {
    state.listening = false;
    console.error(error);
    setStatus("Voice input couldn't start. Try again.");
  }
}

function stopListening() {
  if (!state.listening) return;
  if (state.sttEngine === "server") recorder.stop();
  else recognition.stop();
}

ui.orb.addEventListener("click", () => (state.listening ? stopListening() : startListening()));

let spaceHeld = false;
document.addEventListener("keydown", (event) => {
  if (event.code !== "Space" || event.repeat || state.view !== "driver") return;
  if (event.target.closest("input, textarea, select, button, summary")) return;
  event.preventDefault();
  spaceHeld = true;
  startListening();
});
document.addEventListener("keyup", (event) => {
  if (event.code !== "Space" || !spaceHeld) return;
  event.preventDefault();
  spaceHeld = false;
  stopListening();
});

function showTranscript(text, interim = false) {
  // Shows what is being heard as a provisional line at the end of the thread.
  let live = ui.thread.querySelector(".thread-live");
  if (!text && !interim) {
    live?.remove();
    if (!ui.thread.children.length) ui.thread.append(el("li", { class: "thread-empty", text: "Nothing yet." }));
    return;
  }
  ui.thread.querySelector(".thread-empty")?.remove();
  if (!live) {
    live = el("li", { class: "turn turn-driver thread-live" }, [
      el("span", { class: "turn-who", text: "You" }),
      el("p", { class: "turn-text" }),
    ]);
    ui.thread.append(live);
  }
  live.querySelector(".turn-text").textContent = text || "Listening…";
}

/* ---------- Live mic level ring ---------- */

const levelMeter = (() => {
  const ctx2d = ui.ring.getContext("2d");
  let audioCtx, analyser, data, frame;
  let level = 0;
  let active = false;

  function start(stream) {
    active = true;
    if (stream) {
      try {
        audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        audioCtx.resume?.();
        analyser = audioCtx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        audioCtx.createMediaStreamSource(stream).connect(analyser);
        data = new Uint8Array(analyser.frequencyBinCount);
      } catch {
        analyser = null; // no meter; the halo falls back to a gentle pulse
      }
    }
    if (!frame) draw();
  }

  function stop() {
    active = false;
    audioCtx?.close().catch(() => {});
    audioCtx = analyser = null;
  }

  function draw() {
    const { width, height } = ui.ring;
    const scale = width / ui.ring.clientWidth || 2;
    const orbRadius = 48 * scale;
    ctx2d.clearRect(0, 0, width, height);

    let target = 0;
    if (active && analyser) {
      analyser.getByteFrequencyData(data);
      target = Math.min(1, data.reduce((sum, v) => sum + v, 0) / data.length / 90);
    } else if (active) {
      target = 0.25 + 0.15 * Math.sin(performance.now() / 300); // no mic meter: gentle pulse
    }
    level += (target - level) * 0.25;

    const color = getComputedStyle(ui.orb).backgroundColor;
    ctx2d.fillStyle = color;
    ctx2d.globalAlpha = 0.14;
    ctx2d.beginPath();
    ctx2d.arc(width / 2, height / 2, orbRadius + (4 + level * 20) * scale, 0, Math.PI * 2);
    ctx2d.fill();
    ctx2d.globalAlpha = 1;

    if (active || level > 0.01) {
      frame = requestAnimationFrame(draw);
    } else {
      ctx2d.clearRect(0, 0, width, height);
      frame = null;
    }
  }

  return { start, stop };
})();

/* ---------- Conversation ---------- */

ui.typeForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = ui.typeInput.value.trim();
  if (!text) return;
  ui.typeInput.value = "";
  sendReport(text);
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    if (state.conversationId) resetConversation();
    sendReport(chip.textContent.trim());
  });
});

ui.newReport.addEventListener("click", () => {
  stopSpeaking();
  resetConversation();
  setStatus("or hold <kbd>Space</kbd>");
});

function resetConversation() {
  state.conversationId = null;
  state.events = [];
  ui.thread.replaceChildren(el("li", { class: "thread-empty", text: "Nothing yet." }));
  ui.newReport.hidden = true;
  ui.guidance.dataset.severity = "idle";
  setBadge("idle");
  ui.decision.textContent = "Standing by";
  ui.response.textContent = "When you report something, the recommended next step will appear here and be read aloud.";
  ui.issueRef.textContent = "";
  ui.actionsBlock.hidden = true;
  ui.traceBlock.hidden = true;
  ui.replay.hidden = true;
}

function addTurn(role, text) {
  ui.thread.querySelector(".thread-empty")?.remove();
  ui.thread.querySelector(".thread-live")?.remove();
  ui.thread.append(
    el("li", { class: `turn turn-${role}` }, [
      el("span", { class: "turn-who", text: role === "driver" ? "You" : "Fleet Voice" }),
      el("p", { class: "turn-text", text }),
    ])
  );
  ui.thread.lastElementChild.scrollIntoView({ block: "nearest" });
}

async function sendReport(text, heardBy = "typed") {
  if (state.busy) return;
  state.busy = true;
  stopSpeaking();
  addTurn("driver", text);
  ui.newReport.hidden = false;
  ui.orb.classList.add("is-thinking");
  ui.orbLabel.textContent = "Thinking…";
  setStatus("One moment");
  resetPipeline();
  setStep("heard", "done", `${heardBy} · ${text.split(/\s+/).length} words`);
  setStep("reason", "active", "thinking…");

  try {
    let res = await postTurn(text);
    if (res.status === 404 && state.conversationId) {
      state.conversationId = null; // conversation expired: start a fresh one
      res = await postTurn(text);
    }
    if (!res.ok) throw new Error(`Request failed with status ${res.status}`);
    renderTurn(await res.json());
  } catch (error) {
    console.error(error);
    renderError();
  } finally {
    state.busy = false;
    ui.orb.classList.remove("is-thinking");
    updateOrbLabel();
  }
}

function postTurn(text) {
  return fetch("/api/agent/turn", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, conversation_id: state.conversationId, ...DRIVER }),
  });
}

function updateOrbLabel() {
  if (!state.sttEngine) ui.orbLabel.textContent = "Voice isn't supported here";
  else ui.orbLabel.textContent = state.awaitingAnswer ? "Tap to answer" : "Tap to speak";
}

function setBadge(kind, label) {
  const badge =
    kind === "question"
      ? el("span", { class: "badge", "data-severity": "question" }, [icon("i-question"), el("span", { text: label })])
      : severityBadge(kind);
  badge.id = "severityBadge";
  ui.badge.replaceWith(badge);
  ui.badge = badge;
}

function renderTurn(data) {
  state.conversationId = data.conversation_id;
  state.awaitingAnswer = data.awaiting_answer;
  const seen = new Set(state.events.map((event) => event.summary));
  data.events = data.events.filter((event) => !seen.has(event.summary) && seen.add(event.summary));
  state.events.push(...data.events);
  addTurn("agent", data.reply);

  if (data.awaiting_answer) {
    ui.guidance.dataset.severity = "question";
    setBadge("question", "Needs one more detail");
    ui.decision.textContent = "Quick question";
    ui.issueRef.textContent = "";
    setStatus("Answer by tapping the mic, or type below");
  } else {
    const incident = data.incident;
    ui.guidance.dataset.severity = incident.severity;
    setBadge(incident.severity);
    ui.decision.textContent = DECISION_LABELS[incident.decision] || incident.decision;
    ui.issueRef.textContent = `#${incident.issue_id}`;
    setStatus(incident.escalated ? "Dispatch has been alerted" : "Logged for the fleet");
  }
  ui.response.textContent = data.reply;
  ui.replay.hidden = false;
  ui.traceBlock.hidden = false;

  ui.actionsBlock.hidden = !state.events.length;
  ui.actions.replaceChildren(
    ...state.events.map((event, i) => {
      const fresh = i >= state.events.length - data.events.length;
      const li = el("li", { class: `${fresh ? "enter" : ""}${event.ok ? "" : " is-failed"}${event.by === "safety_floor" ? " by-floor" : ""}` }, [
        icon(event.by === "safety_floor" ? "i-shield" : "i-check"),
        el("span", { text: event.summary }),
        event.by === "safety_floor" ? el("span", { class: "action-tag", text: "safety rule" }) : null,
      ]);
      if (fresh) li.style.animationDelay = `${120 + (i - (state.events.length - data.events.length)) * 90}ms`;
      return li;
    })
  );

  setStep("reason", "done", data.source === "llm" ? `${shortModel(data.model)} · ${data.turn_ms} ms` : `keyword rules · ${data.turn_ms} ms`);
  if (data.guardrail) setStep("floor", "escalated", data.guardrail.detail);
  else setStep("floor", "done", data.source === "llm" ? "passed" : "rules only");
  const toolNames = data.events.filter((event) => event.by === "agent").map((event) => event.tool.replace(/_/g, " "));
  setStep("tools", toolNames.length ? "done" : "", toolNames.length ? toolNames.join(", ") : "none this turn");

  setStep("log", data.incident ? "done" : "", data.incident ? `#${data.incident.issue_id}` : "not yet");

  if (window.matchMedia("(max-width: 960px)").matches) {
    ui.guidance.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  state.lastSpoken = { text: data.reply, audio: data.audio_url };
  speak(state.lastSpoken);
}

function renderError() {
  ui.guidance.dataset.severity = "warning";
  setBadge("warning");
  ui.decision.textContent = "Unavailable";
  ui.response.textContent = "The service didn't respond. If this is urgent, pull over safely and call dispatch directly.";
  ui.replay.hidden = true;
  ui.issueRef.textContent = "";
  setStep("reason", "", "failed");
  setStatus("Couldn't reach the server");
}

/* ---------- Pipeline trace ---------- */

function resetPipeline() {
  ui.pipeline.querySelectorAll("li").forEach((li) => {
    li.className = "";
    li.querySelector(".step-meta").textContent = "—";
  });
}

function setStep(step, stepState, meta) {
  const li = ui.pipeline.querySelector(`[data-step="${step}"]`);
  li.className = stepState ? `is-${stepState}` : "";
  if (meta != null) li.querySelector(".step-meta").textContent = meta;
}

/* ---------- Speech output ---------- */

function speak({ text, audio }) {
  setStep("voice", "active", "speaking…");
  if (audio) {
    ui.audio.src = audio;
    ui.audio
      .play()
      .then(() => setStep("voice", "done", "ElevenLabs voice"))
      .catch(() => speakWithBrowser(text));
  } else {
    speakWithBrowser(text);
  }
}

function speakWithBrowser(text) {
  if (!("speechSynthesis" in window)) {
    setStep("voice", "", "unavailable");
    return;
  }
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = 1.02;
  window.speechSynthesis.speak(utterance);
  setStep("voice", "done", "browser voice");
}

function stopSpeaking() {
  ui.audio.pause();
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
}

ui.replay.addEventListener("click", () => {
  if (!state.lastSpoken) return;
  stopSpeaking();
  speak(state.lastSpoken);
});

/* ---------- Roles & routing ---------- */
// "/" asks who is using the app; "/driver" and "/dispatch" are the two roles.
// The choice is remembered so returning users land straight in their view.

const ROLE_KEY = "fleetvoice.role";
const ROLE_NAMES = { driver: "Driver", dispatch: "Dispatch" };

function rememberRole(role) {
  try {
    if (role) localStorage.setItem(ROLE_KEY, role);
    else localStorage.removeItem(ROLE_KEY);
  } catch {
    /* storage unavailable: just don't remember */
  }
}

function rememberedRole() {
  try {
    return localStorage.getItem(ROLE_KEY);
  } catch {
    return null;
  }
}

function viewForPath(path) {
  if (path.startsWith("/driver")) return "driver";
  if (path.startsWith("/dispatch")) return "dispatch";
  return "picker";
}

function navigate(path, { replace = false } = {}) {
  if (path === "/") rememberRole(null); // "Switch role" forgets the saved choice
  history[replace ? "replaceState" : "pushState"](null, "", path);
  showView(viewForPath(path));
}

document.addEventListener("click", (event) => {
  const link = event.target.closest("[data-nav]");
  if (!link || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  navigate(link.dataset.nav);
});

window.addEventListener("popstate", () => showView(viewForPath(location.pathname)));

function showView(view) {
  if (state.listening) stopListening();
  stopSpeaking();
  state.view = view;

  $("view-picker").hidden = view !== "picker";
  $("view-driver").hidden = view !== "driver";
  $("view-dispatch").hidden = view !== "dispatch";

  const roleLabel = $("roleLabel");
  roleLabel.hidden = view === "picker";
  roleLabel.textContent = ROLE_NAMES[view] || "";
  $("switchRole").hidden = view === "picker";
  $("systemStatus").hidden = view !== "driver";
  document.title = view === "picker" ? "Fleet Voice" : `${ROLE_NAMES[view]} · Fleet Voice`;
  if (view !== "picker") rememberRole(view);

  clearInterval(state.pollTimer);
  if (view === "dispatch") {
    state.seenIds = null;
    refreshDispatch();
    state.pollTimer = setInterval(refreshDispatch, POLL_MS);
  }
  window.scrollTo(0, 0);
}

/* ---------- Dispatch console ---------- */

ui.severityFilter.addEventListener("click", (event) => {
  const button = event.target.closest(".seg-btn");
  if (!button) return;
  ui.severityFilter.querySelectorAll(".seg-btn").forEach((b) => b.classList.toggle("is-active", b === button));
  state.severity = button.dataset.value;
  loadIncidents();
});

ui.statusFilter.addEventListener("change", () => {
  state.status = ui.statusFilter.value;
  loadIncidents();
});

async function refreshDispatch() {
  if (state.view !== "dispatch") return;
  await Promise.all([loadStats(), loadIncidents()]);
}

async function loadStats() {
  try {
    const stats = await (await fetch("/api/stats")).json();
    $("kpiCritical").textContent = stats.open_critical;
    $("kpiWarning").textContent = stats.open_warning;
    $("kpiTrucks").textContent = stats.trucks_affected;
    $("kpiResolved").firstChild.textContent = stats.resolved;
    $("kpiTotal").textContent = `/ ${stats.total}`;
    renderCategoryChart(stats.by_category, stats.total);
  } catch (error) {
    console.error(error);
  }
}

async function loadIncidents() {
  const params = new URLSearchParams({ limit: "100" });
  if (state.severity) params.set("severity", state.severity);
  if (state.status) params.set("status", state.status);

  try {
    const { issues } = await (await fetch(`/api/issues?${params}`)).json();
    renderIncidents(issues);
    ui.lastUpdated.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch (error) {
    console.error(error);
    ui.incidentList.replaceChildren(el("li", { class: "empty" }, el("p", { text: "Couldn't load incidents. Is the backend running?" })));
  }
}

function renderIncidents(issues) {
  const firstLoad = state.seenIds === null;
  const seen = state.seenIds || new Set();

  if (!issues.length) {
    const filtered = state.severity || state.status;
    const empty = el("li", { class: "empty" }, [
      el("p", { text: filtered ? "No incidents match these filters." : "No incidents logged yet." }),
    ]);
    if (!filtered) {
      const button = el("button", { class: "primary-btn", text: "Load sample fleet data" });
      button.addEventListener("click", async () => {
        button.disabled = true;
        await fetch("/api/demo/seed", { method: "POST" });
        refreshDispatch();
      });
      empty.append(button);
    }
    ui.incidentList.replaceChildren(empty);
    return;
  }

  ui.incidentList.replaceChildren(
    ...issues.map((issue) => {
      const isNew = !firstLoad && !seen.has(issue.issue_id);
      seen.add(issue.issue_id);
      return incidentRow(issue, isNew);
    })
  );
  state.seenIds = seen;
}

function incidentRow(issue, isNew) {
  const select = el("select", { class: "status-select", "aria-label": "Incident status" });
  for (const value of ["open", "acknowledged", "resolved"]) {
    select.append(el("option", { value, text: value[0].toUpperCase() + value.slice(1), selected: issue.status === value }));
  }
  select.setAttribute("aria-label", `Status for incident ${issue.issue_id}`);
  select.addEventListener("change", async () => {
    select.disabled = true;
    await fetch(`/api/issues/${issue.issue_id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: select.value }),
    });
    refreshDispatch();
  });

  return el(
    "li",
    { class: `incident${isNew ? " is-new" : ""}`, "data-severity": issue.severity, "data-status": issue.status },
    [
      el("span", { class: "incident-stripe" }),
      el("div", {}, [
        el("div", { class: "incident-top" }, [
          severityBadge(issue.severity),
          el("span", { class: "incident-decision", text: DECISION_LABELS[issue.decision] || issue.decision }),
        ]),
        el("p", { class: "incident-text", text: `“${issue.transcript}”` }),
        conversationDetails(issue),
        el("div", { class: "incident-meta" }, [
          el("span", { text: issue.truck_id }),
          el("span", { text: issue.driver_id }),
          el("span", { class: "tag", text: issue.category }),
          el("span", { text: issue.source === "llm" ? "Assessed by AI" : "Assessed by rules" }),
          issue.escalated ? el("span", { class: "escalated", text: issue.urgency === "routine" ? "Dispatch alerted" : "Urgent alert" }) : null,
          issue.guardrail_applied ? el("span", { text: "Safety rule applied" }) : null,
          el("span", { text: timeAgo(issue.timestamp), title: new Date(issue.timestamp).toLocaleString() }),
        ]),
      ]),
      el("div", { class: "incident-side" }, select),
    ]
  );
}

function conversationDetails(issue) {
  const turns = issue.conversation || [];
  if (!turns.length && !issue.summary) return null;
  const body = el("div", { class: "convo-body" }, [
    issue.summary ? el("p", {}, [el("span", { class: "convo-who", text: "Summary" }), issue.summary]) : null,
    ...turns.map((turn) =>
      el("p", {}, [el("span", { class: "convo-who", text: turn.role === "driver" ? "Driver" : "Fleet Voice" }), turn.text])
    ),
    issue.actions?.length ? el("ul", { class: "convo-actions" }, issue.actions.map((action) => el("li", { text: action }))) : null,
  ]);
  const label = turns.length ? `Conversation · ${turns.length} message${turns.length === 1 ? "" : "s"}` : "Details";
  const details = el("details", { class: "convo", open: state.openConversations.has(issue.issue_id) }, [el("summary", { text: label }), body]);
  details.addEventListener("toggle", () => {
    if (details.open) state.openConversations.add(issue.issue_id);
    else state.openConversations.delete(issue.issue_id);
  });
  return details;
}

function renderCategoryChart(byCategory, total) {
  const rows = Object.entries(byCategory).sort((a, b) => b[1] - a[1]);
  if (!rows.length) {
    ui.categoryChart.replaceChildren(el("p", { class: "muted", text: "No data yet." }));
    return;
  }
  const max = rows[0][1];

  ui.categoryChart.replaceChildren(
    ...rows.map(([category, count]) => {
      const fill = el("div", { class: "bar-fill" });
      fill.style.width = `${(count / max) * 100}%`;
      const row = el("div", { class: "bar-row", role: "row" }, [
        el("span", { class: "bar-label", role: "rowheader", text: category }),
        el("div", { class: "bar-track", "aria-hidden": "true" }, fill),
        el("span", { class: "bar-value", role: "cell", text: String(count) }),
      ]);
      const pct = Math.round((count / total) * 100);
      row.addEventListener("mousemove", (event) => showTip(event, `${capitalize(category)} · ${count} incident${count === 1 ? "" : "s"} · ${pct}%`));
      row.addEventListener("mouseleave", () => (ui.chartTip.hidden = true));
      return row;
    })
  );
}

function showTip(event, text) {
  ui.chartTip.textContent = text;
  ui.chartTip.hidden = false;
  ui.chartTip.style.left = `${event.clientX + 12}px`;
  ui.chartTip.style.top = `${event.clientY - 32}px`;
}

function capitalize(text) {
  return text[0].toUpperCase() + text.slice(1);
}

/* ---------- Boot ---------- */

loadHealth();
const initialView = viewForPath(location.pathname);
const savedRole = rememberedRole();
if (initialView === "picker" && ROLE_NAMES[savedRole]) navigate(`/${savedRole}`, { replace: true });
else showView(initialView);
