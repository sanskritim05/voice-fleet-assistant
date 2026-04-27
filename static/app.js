const recordButton = document.getElementById("recordButton");
const transcriptBox = document.getElementById("transcript");
const responseText = document.getElementById("responseText");
const decisionText = document.getElementById("decision");
const actionsList = document.getElementById("actionsList");
const issuesContainer = document.getElementById("issues");
const audioPlayer = document.getElementById("audioPlayer");
const actionBox = document.getElementById("actionBox");
const statusText = document.getElementById("status");
const severityBadge = document.getElementById("severityBadge");

let recognition;
let isRecording = false;

function setupSpeechRecognition() {
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  if (!SpeechRecognition) {
    alert("Use Chrome for voice input.");
    return;
  }

  recognition = new SpeechRecognition();
  recognition.lang = "en-US";

  recognition.onstart = () => {
    isRecording = true;
    recordButton.classList.add("recording");
    recordButton.innerHTML = `<span class="mic">🎙</span><strong>Listening</strong>`;
    statusText.textContent = "Listening now...";
  };

  recognition.onresult = (event) => {
    const text = event.results[0][0].transcript;
    transcriptBox.value = text;
    sendMessage(text);
  };

  recognition.onend = () => {
    isRecording = false;
    recordButton.classList.remove("recording");
    recordButton.innerHTML = `<span class="mic">🎙</span><strong>Hold to Talk</strong>`;
    statusText.textContent = "Ready when you are.";
  };
}

recordButton.addEventListener("mousedown", () => {
  if (!recognition) setupSpeechRecognition();
  recognition.start();
});

recordButton.addEventListener("mouseup", () => {
  recognition.stop();
});

recordButton.addEventListener("touchstart", () => {
  if (!recognition) setupSpeechRecognition();
  recognition.start();
});

recordButton.addEventListener("touchend", () => {
  recognition.stop();
});

async function sendMessage(transcript) {
  statusText.textContent = "Reviewing your update...";

  try {
    const res = await fetch("/api/message", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        transcript,
        driver_id: "driver-demo-001",
        truck_id: "truck-demo-8821",
      }),
    });

    if (!res.ok) {
      throw new Error(`Request failed with status ${res.status}`);
    }

    const data = await res.json();

    responseText.textContent = data.response_text;
    decisionText.textContent = formatDecision(data.decision);

    updateActionColor(data.severity);

    actionsList.innerHTML = "";
    data.actions.forEach((action) => {
      const li = document.createElement("li");
      li.textContent = action;
      actionsList.appendChild(li);
    });

    if (data.audio_url) {
      audioPlayer.src = data.audio_url;
      audioPlayer.hidden = false;
      audioPlayer.play();
    } else {
      audioPlayer.hidden = true;
    }

    statusText.textContent = "Update processed.";
    loadIssues();
  } catch (error) {
    statusText.textContent = "Could not process update. Try again.";
    decisionText.textContent = "Unavailable";
    responseText.textContent =
      "The service did not return guidance. Confirm your API keys and backend server, then retry.";
    actionsList.innerHTML = "<li>No action logged</li>";
    audioPlayer.hidden = true;
    updateActionColor("warning");
    console.error(error);
  }
}

function formatDecision(decision) {
  if (decision === "STOP_SAFELY") return "Pull Over Safely";
  if (decision === "CONTINUE_WITH_CAUTION") return "Continue Carefully";
  if (decision === "SEND_MESSAGE") return "Dispatch Update Sent";
  return "Logged for Review";
}

function updateActionColor(severity) {
  actionBox.className = "right-panel";
  severityBadge.className = "severity-badge";

  if (severity === "critical") {
    actionBox.classList.add("critical");
    severityBadge.classList.add("critical");
    severityBadge.textContent = "Critical";
  } else if (severity === "warning") {
    actionBox.classList.add("warning");
    severityBadge.classList.add("warning");
    severityBadge.textContent = "Warning";
  } else {
    actionBox.classList.add("safe");
    severityBadge.classList.add("safe");
    severityBadge.textContent = "Low Risk";
  }
}

async function loadIssues() {
  try {
    const res = await fetch("/api/issues");
    if (!res.ok) {
      throw new Error(`Issue fetch failed with status ${res.status}`);
    }

    const data = await res.json();
    issuesContainer.innerHTML = "";

    if (!data.issues.length) {
      issuesContainer.innerHTML = `<div class="log-item">No trip reports yet.</div>`;
      return;
    }

    data.issues
      .slice()
      .reverse()
      .slice(0, 4)
      .forEach((issue) => {
        const div = document.createElement("div");
        div.className = "log-item";

        div.innerHTML = `
          <strong>${formatDecision(issue.decision)}</strong><br>
          ${issue.transcript}
        `;

        issuesContainer.appendChild(div);
      });
  } catch (error) {
    issuesContainer.innerHTML =
      '<div class="log-item">Could not load recent logs. Check if the backend is running.</div>';
    console.error(error);
  }
}

loadIssues();