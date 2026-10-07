/**
 * Obsidian Vanguard — Cockpit Dashboard Logic
 * Integrates WebRTC Browser Camera, Oscilloscope Canvas,
 * and Bi-directional Telemetry with the Fedora Hub.
 */

document.addEventListener("DOMContentLoaded", () => {
  // DOM References
  const hudClock = document.getElementById("hud-clock");
  const valCarStatus = document.getElementById("val-car-status");
  const dotCarStatus = document.getElementById("dot-car-status");
  
  // Gaze & Eye Telemetry
  const gazeBadge = document.getElementById("gaze-badge");
  const cardLeft = document.getElementById("card-left-glance");
  const cardRight = document.getElementById("card-right-glance");
  const cardClench = document.getElementById("card-clench-blink");
  const blinkFlash = document.getElementById("blink-flash");

  // PIP Overlay elements
  const pipGazeLabel = document.getElementById("pip-gaze-label");
  const pipGazeReadout = document.getElementById("pip-gaze-readout");
  const pipGazeConf = document.getElementById("pip-gaze-conf");

  // Quick gesture strip pills
  const gqLeft = document.getElementById("gq-left");
  const gqRight = document.getElementById("gq-right");
  const gqClench = document.getElementById("gq-clench");

  // State Banner
  const driveStateBanner = document.getElementById("drive-state-banner");
  const stateTitle = document.getElementById("state-title");
  const stateIcon = document.getElementById("state-icon");

  // Radar & Obstacle (kept as optional references)
  const obstacleBanner = document.getElementById("obstacle-banner");
  const hudDistPill = document.getElementById("hud-dist-pill");

  // Signal Value Readouts
  const txtEogVal = document.getElementById("txt-eog-val");
  const barEog = document.getElementById("bar-eog");
  const txtPiezoVal = document.getElementById("txt-piezo-val");
  const barPiezo = document.getElementById("bar-piezo");
  const commandLogList = document.getElementById("command-log-list");

  // Canvas Oscilloscope
  const canvas = document.getElementById("scopeCanvas");
  const ctx = canvas.getContext("2d");

  // Local Webcam Toggle
  const btnToggleCam = document.getElementById("btn-toggle-cam");
  const videoLocal = document.getElementById("webcam-local");
  const pipDriverStream = document.getElementById("pip-driver-stream");
  const faceOverlayCanvas = document.getElementById("faceOverlayCanvas");
  const faceOverlayCtx = faceOverlayCanvas.getContext("2d");

  // Config Modal
  const configModal = document.getElementById("config-modal");
  const btnOpenConfig = document.getElementById("btn-open-config");
  const btnCloseConfig = document.getElementById("btn-close-config");
  const btnSaveConfig = document.getElementById("btn-save-config");

  let eogHistory = new Array(80).fill(512);
  let piezoHistory = new Array(80).fill(40);
  let usingLocalWebcam = false;
  let localMediaStream = null;

  // 1. Clock
  setInterval(() => {
    const now = new Date();
    hudClock.textContent = now.toTimeString().split(" ")[0];
  }, 1000);

  // 2. High-Performance Canvas Oscilloscope Rendering (Obsidian Palette)
  function renderOscilloscope() {
    const w = canvas.width;
    const h = canvas.height;

    // Clear background
    ctx.fillStyle = "#0e0e0e";
    ctx.fillRect(0, 0, w, h);

    // Subtle Monochrome Grid
    ctx.strokeStyle = "rgba(68, 71, 72, 0.25)";
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 30) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    for (let y = 0; y < h; y += 30) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(w, y);
      ctx.stroke();
    }

    const baselineY = h * 0.5;
    const upperThreshY = baselineY - (120 / 1024) * h * 1.5;
    const lowerThreshY = baselineY + (120 / 1024) * h * 1.5;

    // Threshold Dashes
    ctx.setLineDash([4, 6]);
    ctx.strokeStyle = "rgba(142, 145, 146, 0.4)";
    ctx.beginPath();
    ctx.moveTo(0, upperThreshY);
    ctx.lineTo(w, upperThreshY);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(0, lowerThreshY);
    ctx.lineTo(w, lowerThreshY);
    ctx.stroke();

    // Baseline Solid
    ctx.strokeStyle = "rgba(196, 199, 200, 0.3)";
    ctx.beginPath();
    ctx.moveTo(0, baselineY);
    ctx.lineTo(w, baselineY);
    ctx.stroke();
    ctx.setLineDash([]);

    // Draw EOG Wave (Crisp White Glow)
    if (eogHistory.length > 1) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2.2;
      ctx.shadowColor = "rgba(255, 255, 255, 0.8)";
      ctx.shadowBlur = 10;
      ctx.beginPath();

      const step = w / (eogHistory.length - 1);
      for (let i = 0; i < eogHistory.length; i++) {
        const val = eogHistory[i];
        const norm = (val - 512) / 400;
        const y = baselineY - norm * (h * 0.45);
        const x = i * step;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    // Draw Piezo Wave (Silver Secondary Glow)
    if (piezoHistory.length > 1) {
      ctx.strokeStyle = "#c7c6c6";
      ctx.lineWidth = 1.8;
      ctx.shadowColor = "rgba(199, 198, 198, 0.5)";
      ctx.shadowBlur = 6;
      ctx.beginPath();

      const step = w / (piezoHistory.length - 1);
      for (let i = 0; i < piezoHistory.length; i++) {
        const val = piezoHistory[i];
        const y = h - (val / 800) * (h * 0.6) - 10;
        const x = i * step;
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    requestAnimationFrame(renderOscilloscope);
  }
  requestAnimationFrame(renderOscilloscope);

  // 3. Telemetry Polling (every 60ms)
  async function pollTelemetry() {
    try {
      const resp = await fetch("/api/telemetry");
      if (resp.ok) {
        const data = await resp.json();
        updateUI(data);
      }
    } catch (e) {
      // Backend brief disconnect
    }
    setTimeout(pollTelemetry, 60);
  }
  pollTelemetry();

  // 4. Update UI with Telemetry State
  function updateUI(data) {
    // Car Link Status
    if (data.car_connected) {
      valCarStatus.textContent = "ONLINE";
      dotCarStatus.className = "pill-dot dot-online";
    } else {
      valCarStatus.textContent = "STANDBY";
      dotCarStatus.className = "pill-dot";
    }

    // Gaze State
    const gaze = data.current_gaze || "CENTER";
    if (gazeBadge) gazeBadge.textContent = gaze;

    cardLeft.classList.toggle("active", gaze === "LEFT");
    cardRight.classList.toggle("active", gaze === "RIGHT");
    cardClench.classList.toggle("active", data.clench_active || data.blink_active);

    blinkFlash.style.display = data.blink_active ? "block" : "none";

    // PIP overlay gaze sync
    if (pipGazeLabel) pipGazeLabel.textContent = gaze;
    if (pipGazeReadout) pipGazeReadout.textContent = gaze;

    // Quick gesture strip highlights
    if (gqLeft) gqLeft.classList.toggle("gq-active", gaze === "LEFT");
    if (gqRight) gqRight.classList.toggle("gq-active", gaze === "RIGHT");
    if (gqClench) gqClench.classList.toggle("gq-active", !!(data.clench_active || data.blink_active));

    // Update HUD state text and propulsion strip
    const hudStateText = document.getElementById("hud-car-state-text");
    const hudRadarText = document.getElementById("hud-radar-text");
    const propStrip = document.getElementById("drive-state-banner");
    if (hudStateText) hudStateText.textContent = data.car_state || "STOPPED";
    if (hudRadarText) hudRadarText.textContent = `${data.ultrasonic_distance || 99} CM`;
    if (propStrip) {
      propStrip.classList.toggle("active-moving",
        !!(data.car_state && data.car_state !== "STOP" && data.car_state !== "STOPPED"));
    }

    // Propulsion Banner
    const state = data.car_state || "STOP";
    const stateWord = state === "STOP" ? "STOPPED" :
      state === "FORWARD" ? "FORWARD" :
      state.includes("LEFT") ? "LEFT" :
      state.includes("RIGHT") ? "RIGHT" :
      state === "REVERSE" ? "REVERSE" : state;
    stateTitle.textContent = stateWord;

    driveStateBanner.classList.remove("active-moving");
    if (state === "FORWARD") {
      driveStateBanner.classList.add("active-moving");
      stateIcon.textContent = "▲";
    } else if (state.includes("TURNING")) {
      driveStateBanner.classList.add("active-moving");
      stateIcon.textContent = state.includes("LEFT") ? "◄" : "►";
    } else if (state === "REVERSE") {
      stateIcon.textContent = "▼";
    } else {
      stateIcon.textContent = "■";
    }

    // Radar & Proximity (simplified — radar card removed from UI)
    const dist = data.ultrasonic_distance || 99;
    if (hudDistPill) hudDistPill.textContent = `RADAR: ${dist} CM`;
    if (obstacleBanner) {
      obstacleBanner.style.display = (dist < 30 || data.obstacle_alert) ? "block" : "none";
    }

    // Biosignal Readouts
    const eog = data.eog_value || 512;
    const piezo = data.piezo_value || 40;
    txtEogVal.textContent = `${eog} ADC`;
    txtPiezoVal.textContent = `${piezo} ADC`;

    barEog.style.width = `${Math.min(100, (eog / 1024) * 100)}%`;
    barPiezo.style.width = `${Math.min(100, (piezo / 600) * 100)}%`;

    if (data.eog_history && data.eog_history.length > 0) {
      eogHistory = data.eog_history;
    }
    if (data.piezo_history && data.piezo_history.length > 0) {
      piezoHistory = data.piezo_history;
    }

    // Dispatch Log
    if (data.command_log && data.command_log.length > 0) {
      commandLogList.innerHTML = data.command_log.map(item => `
        <div class="log-line">
          <span class="log-time font-mono">${item.time}</span>
          <span class="log-cmd">[${item.cmd}]</span>
          <span class="log-source">${item.source}</span>
        </div>
      `).join("");
    }
  }

  // 5. Native Browser Webcam Integration (For Fedora PipeWire / Wayland)
  if (btnToggleCam) {
    btnToggleCam.addEventListener("click", async () => {
      if (!usingLocalWebcam) {
        try {
          localMediaStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: "user" }
          });
          videoLocal.srcObject = localMediaStream;
          videoLocal.classList.remove("hidden");
          if (pipDriverStream) pipDriverStream.style.display = "none";
          usingLocalWebcam = true;
          btnToggleCam.textContent = "\u21BA NEURAL";
          startBrowserEyeTracking();
        } catch (err) {
          alert("Could not access browser webcam: " + err.message);
        }
      } else {
        if (localMediaStream) {
          localMediaStream.getTracks().forEach(track => track.stop());
        }
        videoLocal.classList.add("hidden");
        if (pipDriverStream) pipDriverStream.style.display = "block";
        usingLocalWebcam = false;
        btnToggleCam.textContent = "\u21BA CAM";
      }
    });
  }

  // Client-Side Vision Tracker Loop
  let lastGazeTrigger = 0;
  function startBrowserEyeTracking() {
    function trackFrame() {
      if (!usingLocalWebcam || videoLocal.paused || videoLocal.ended) return;

      faceOverlayCanvas.width = videoLocal.videoWidth || 480;
      faceOverlayCanvas.height = videoLocal.videoHeight || 360;
      const cw = faceOverlayCanvas.width;
      const ch = faceOverlayCanvas.height;

      faceOverlayCtx.clearRect(0, 0, cw, ch);

      // Draw driver focal ring
      faceOverlayCtx.strokeStyle = "rgba(255, 255, 255, 0.4)";
      faceOverlayCtx.lineWidth = 1.5;
      faceOverlayCtx.beginPath();
      faceOverlayCtx.ellipse(cw * 0.5, ch * 0.5, cw * 0.22, ch * 0.32, 0, 0, Math.PI * 2);
      faceOverlayCtx.stroke();

      // Eye tracker guide points
      faceOverlayCtx.fillStyle = "#ffffff";
      faceOverlayCtx.beginPath();
      faceOverlayCtx.arc(cw * 0.4, ch * 0.45, 4, 0, Math.PI * 2);
      faceOverlayCtx.arc(cw * 0.6, ch * 0.45, 4, 0, Math.PI * 2);
      faceOverlayCtx.fill();

      requestAnimationFrame(trackFrame);
    }
    requestAnimationFrame(trackFrame);
  }

  // 6. Command Dispatcher Helper
  async function sendCommand(cmd, source = "Manual UI") {
    try {
      await fetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: cmd, source: source })
      });
    } catch (e) {
      console.error("Failed to send command:", e);
    }
  }

  // 7. Virtual D-Pad Click Handlers
  document.getElementById("btn-cmd-f").addEventListener("click", () => sendCommand("F", "UI Forward"));
  document.getElementById("btn-cmd-l").addEventListener("click", () => sendCommand("L", "UI Steer Left"));
  document.getElementById("btn-cmd-r").addEventListener("click", () => sendCommand("R", "UI Steer Right"));
  document.getElementById("btn-cmd-s").addEventListener("click", () => sendCommand("S", "UI Emergency Brake"));
  document.getElementById("btn-cmd-b").addEventListener("click", () => sendCommand("B", "UI Reverse"));

  // 8. Keyboard Controls (W, A, S, D, Space)
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;

    const key = e.key.toLowerCase();
    if (key === "w" || e.key === "ArrowUp") {
      sendCommand("F", "Keyboard (W)");
    } else if (key === "a" || e.key === "ArrowLeft") {
      sendCommand("L", "Keyboard (A)");
    } else if (key === "d" || e.key === "ArrowRight") {
      sendCommand("R", "Keyboard (D)");
    } else if (key === "s" || e.key === "ArrowDown") {
      sendCommand("B", "Keyboard (S)");
    } else if (e.key === " " || key === "spacebar") {
      e.preventDefault();
      sendCommand("S", "Keyboard (Space Brake)");
    } else if (e.key === "Escape") {
      exitTheater();
    }
  });

  // 9. Configuration Modal Handlers
  btnOpenConfig.addEventListener("click", () => configModal.classList.add("open"));
  btnCloseConfig.addEventListener("click", () => configModal.classList.remove("open"));

  btnSaveConfig.addEventListener("click", async () => {
    const payload = {
      car_ip: document.getElementById("cfg-car-ip").value.trim(),
      car_port: parseInt(document.getElementById("cfg-car-port").value, 10),
      ai_autopilot_enabled: document.getElementById("cfg-ai-enabled").checked,
      clench_trigger_enabled: document.getElementById("cfg-clench-enabled").checked,
      blink_trigger_enabled: document.getElementById("cfg-blink-enabled").checked
    };

    try {
      await fetch("/api/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      configModal.classList.remove("open");
    } catch (e) {
      alert("Failed to save config: " + e.message);
    }
  });

  // 10. Theater / Maximize Mode
  const btnMaximize = document.getElementById("btn-maximize-stream");
  const btnExitTheater = document.getElementById("btn-exit-theater");

  function enterTheater() {
    document.body.classList.add("stream-maximized");
    // Scroll to top so stream fills screen from top
    window.scrollTo(0, 0);
    document.documentElement.style.overflow = "hidden";
  }

  function exitTheater() {
    document.body.classList.remove("stream-maximized");
    document.documentElement.style.overflow = "";
  }

  if (btnMaximize) {
    btnMaximize.addEventListener("click", () => {
      if (document.body.classList.contains("stream-maximized")) {
        exitTheater();
      } else {
        enterTheater();
      }
    });
  }

  if (btnExitTheater) {
    btnExitTheater.addEventListener("click", exitTheater);
  }
});
