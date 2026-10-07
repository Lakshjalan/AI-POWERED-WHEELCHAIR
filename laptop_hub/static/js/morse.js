/**
 * OcuSteer Morse Communicator — Page Logic
 * Handles keyboard/mouse blink simulation, telemetry polling,
 * real-time UI updates, and Web Speech API TTS.
 */

document.addEventListener("DOMContentLoaded", () => {
  // --- DOM References ---
  const navPill       = document.getElementById("nav-connection-pill");
  const navDot        = document.getElementById("nav-dot");
  const navStatusText = document.getElementById("nav-status-text");
  const morseClock    = document.getElementById("morse-clock");

  const eyeAnim       = document.getElementById("eye-anim");
  const eyeShape      = document.getElementById("eye-shape");
  const blinkStateVal  = document.getElementById("blink-state-val");
  const blinkDurVal    = document.getElementById("blink-dur-val");
  const blinkSignalBar = document.getElementById("blink-signal-bar");

  const symbolDots     = document.getElementById("symbol-dots");
  const messageOutput  = document.getElementById("message-output");
  const msgCursor      = document.getElementById("msg-cursor");
  const historyFlow    = document.getElementById("history-flow");

  const btnSpeak       = document.getElementById("btn-speak");
  const btnClear       = document.getElementById("btn-clear");
  const fabBlink       = document.getElementById("fab-blink");

  // --- State ---
  let morseEnabled = false;
  let isBlinkingLocal = false;
  let blinkStartTime = 0;
  let blinkDurationTimer = null;
  let lastMessage = "";

  // --- Clock ---
  setInterval(() => {
    morseClock.textContent = new Date().toTimeString().split(" ")[0];
  }, 1000);

  // --- Ensure Morse mode is ON when visiting this page ---
  async function ensureMorseEnabled() {
    try {
      const resp = await fetch("/api/telemetry");
      if (resp.ok) {
        const data = await resp.json();
        if (!data.morse_mode) {
          await fetch("/api/morse/toggle", { method: "POST" });
        }
        morseEnabled = true;
        updateNavStatus(true);
      }
    } catch (e) {
      console.error("Could not enable morse mode:", e);
    }
  }
  ensureMorseEnabled();

  function updateNavStatus(active) {
    if (active) {
      navPill.classList.add("active");
      navStatusText.textContent = "LIVE";
    } else {
      navPill.classList.remove("active");
      navStatusText.textContent = "STANDBY";
    }
  }

  // ==========================================================================
  // MANUAL BLINK via KEYBOARD (Spacebar) + FAB Button + Mouse
  // ==========================================================================

  async function startBlink() {
    if (isBlinkingLocal) return;
    isBlinkingLocal = true;
    blinkStartTime = performance.now();

    // Visual feedback
    eyeAnim.classList.add("blinking");
    eyeShape.classList.add("closed");
    blinkStateVal.textContent = "CLOSED";
    blinkStateVal.classList.add("blinking-val");
    fabBlink.classList.add("pressed");

    // Notify backend
    try {
      await fetch("/api/morse/blink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "start" })
      });
    } catch (e) { /* ok */ }

    // Live duration counter
    blinkDurationTimer = setInterval(() => {
      const dur = (performance.now() - blinkStartTime) / 1000;
      blinkDurVal.textContent = dur.toFixed(2) + "s";
      const pct = Math.min(100, (dur / 1.0) * 100);
      blinkSignalBar.style.width = pct + "%";
      blinkSignalBar.classList.toggle("long", dur >= 0.35);
    }, 30);
  }

  async function endBlink() {
    if (!isBlinkingLocal) return;
    isBlinkingLocal = false;

    // Visual feedback
    eyeAnim.classList.remove("blinking");
    eyeShape.classList.remove("closed");
    blinkStateVal.textContent = "OPEN";
    blinkStateVal.classList.remove("blinking-val");
    fabBlink.classList.remove("pressed");

    clearInterval(blinkDurationTimer);
    blinkDurVal.textContent = "0.00s";
    blinkSignalBar.style.width = "0%";
    blinkSignalBar.classList.remove("long");

    // Notify backend
    try {
      await fetch("/api/morse/blink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "end" })
      });
    } catch (e) { /* ok */ }
  }

  // Spacebar handler
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      startBlink();
    }
  });

  window.addEventListener("keyup", (e) => {
    if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      endBlink();
    }
  });

  // FAB button handler (mouse + touch)
  fabBlink.addEventListener("mousedown", (e) => { e.preventDefault(); startBlink(); });
  fabBlink.addEventListener("mouseup", (e) => { e.preventDefault(); endBlink(); });
  fabBlink.addEventListener("mouseleave", () => { if (isBlinkingLocal) endBlink(); });
  fabBlink.addEventListener("touchstart", (e) => { e.preventDefault(); startBlink(); }, { passive: false });
  fabBlink.addEventListener("touchend", (e) => { e.preventDefault(); endBlink(); });

  // ==========================================================================
  // TELEMETRY POLLING (100ms)
  // ==========================================================================
  async function pollTelemetry() {
    try {
      const resp = await fetch("/api/telemetry");
      if (resp.ok) {
        const data = await resp.json();
        updateMorseUI(data);
      }
    } catch (e) { /* pass */ }
    setTimeout(pollTelemetry, 100);
  }
  pollTelemetry();

  function updateMorseUI(data) {
    const morse = data.morse;
    if (!morse) return;

    morseEnabled = data.morse_mode;
    updateNavStatus(morseEnabled);

    // Eye state from backend (for real webcam blink detection)
    if (!isBlinkingLocal) {
      if (morse.is_blinking) {
        eyeAnim.classList.add("blinking");
        eyeShape.classList.add("closed");
        blinkStateVal.textContent = "CLOSED";
        blinkStateVal.classList.add("blinking-val");
        const dur = morse.blink_duration || 0;
        blinkDurVal.textContent = dur.toFixed(2) + "s";
        const pct = Math.min(100, (dur / 1.0) * 100);
        blinkSignalBar.style.width = pct + "%";
        blinkSignalBar.classList.toggle("long", dur >= 0.35);
      } else {
        eyeAnim.classList.remove("blinking");
        eyeShape.classList.remove("closed");
        blinkStateVal.textContent = "OPEN";
        blinkStateVal.classList.remove("blinking-val");
      }
    }

    // Current symbol buffer
    const display = morse.current_display || "";
    if (display) {
      symbolDots.textContent = display;
      symbolDots.classList.add("has-data");
    } else {
      symbolDots.textContent = "—";
      symbolDots.classList.remove("has-data");
    }

    // Decoded message
    const msg = morse.decoded_message || "";
    if (msg) {
      messageOutput.innerHTML = `<span>${escapeHTML(msg)}</span>`;
      msgCursor.style.display = "inline-block";

      // Auto-speak completed words via browser TTS
      if (msg !== lastMessage && msg.length > lastMessage.length) {
        const newChars = msg.substring(lastMessage.length);
        if (newChars.includes(" ") && window.speechSynthesis) {
          const words = msg.trim().split(" ");
          const lastWord = words[words.length - 2];
          if (lastWord) {
            const u = new SpeechSynthesisUtterance(lastWord);
            u.rate = 0.9;
            window.speechSynthesis.speak(u);
          }
        }
      }
      lastMessage = msg;
    } else {
      messageOutput.innerHTML = '<span class="msg-placeholder">Hold SPACEBAR or blink to compose...</span>';
      msgCursor.style.display = "none";
      lastMessage = "";
    }

    // Symbol history
    const history = morse.symbol_history || [];
    if (history.length > 0) {
      historyFlow.innerHTML = history.map(h => `
        <div class="hist-tag">
          <span class="hist-char">${escapeHTML(h.char)}</span>
          <span class="hist-morse">${escapeHTML(h.display)}</span>
        </div>
      `).join("");
    } else {
      historyFlow.innerHTML = '<span class="history-placeholder">Awaiting input...</span>';
    }
  }

  // ==========================================================================
  // ACTION BUTTONS
  // ==========================================================================
  btnSpeak.addEventListener("click", async () => {
    try {
      const resp = await fetch("/api/morse/speak", { method: "POST" });
      if (resp.ok) {
        const data = await resp.json();
        if (data.spoken && window.speechSynthesis) {
          const u = new SpeechSynthesisUtterance(data.spoken);
          u.rate = 0.9;
          u.pitch = 1.0;
          window.speechSynthesis.speak(u);
        }
      }
    } catch (e) {
      console.error("Speak error:", e);
    }
  });

  btnClear.addEventListener("click", async () => {
    try {
      await fetch("/api/morse/clear", { method: "POST" });
      lastMessage = "";
    } catch (e) {
      console.error("Clear error:", e);
    }
  });

  // ==========================================================================
  // HELPERS
  // ==========================================================================
  function escapeHTML(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }
});
