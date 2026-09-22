const DOCUMENT_MAX_LEN = 11;
const PIN_LEN = 4;
const SESSION_TIMEOUT_SECONDS = 30;
const ALGORITHM_LABELS = { xiaomi: "Xiaomi/Zepp Life", science: "Científico" };
const SEX_LABELS = { male: "M", female: "F" };

const ATTRACT_IDLE_TIMEOUT_MS = 45000; // volta pro descanso de tela depois de tanto tempo parado no id/pin

const state = {
  screen: "attract", // attract | idle | pin | session
  documentBuffer: "",
  pendingIdentifier: null, // { document } ou { client_id }
  pinBuffer: "",
  lastTouchSentAt: 0,
  history: [], // medições recentes do cliente autenticado, mais recente primeiro (até 60)
  countdownSecondsLeft: SESSION_TIMEOUT_SECONDS,
  countdownTimer: null,
  clockTimer: null,
};

// -- Elementos --------------------------------------------------------

const bleStatus = document.getElementById("ble-status");
const hardwareInput = document.getElementById("hardware-input");

const screens = {
  attract: document.getElementById("screen-attract"),
  idle: document.getElementById("screen-idle"),
  pin: document.getElementById("screen-pin"),
  session: document.getElementById("screen-session"),
};

const idDigits = document.querySelectorAll("#id-display .id-digit");
const idError = document.getElementById("id-error");
const suggestionsBlock = document.getElementById("suggestions");
const suggestionCards = document.getElementById("suggestion-cards");

const pinHint = document.getElementById("pin-hint");
const pinDots = document.querySelectorAll("#pin-display .pin-dot");
const pinError = document.getElementById("pin-error");

const avatarCircle = document.getElementById("avatar-circle");
const sessionName = document.getElementById("session-name");
const sessionSub = document.getElementById("session-sub");
const sessionClock = document.getElementById("session-clock");
const statusPill = document.getElementById("status-pill");
const statusText = document.getElementById("status-text");
const logoutBtn = document.getElementById("logout-btn");
const waitingCard = document.getElementById("waiting-card");
const sessionResults = document.getElementById("session-results");

const weightValue = document.getElementById("weight-value");
const weightUnit = document.getElementById("weight-unit");
const weightTrend = document.getElementById("weight-trend");
const weightHint = document.getElementById("weight-hint");

const scoreValueBig = document.getElementById("score-value-big");
const scoreTier = document.getElementById("score-tier");
const scoreBarFill = document.getElementById("score-bar-fill");
const journeyWeeks = document.getElementById("journey-weeks");
const journeyCount = document.getElementById("journey-count");

const bioColLeft = document.getElementById("bio-col-left");
const bioColRight = document.getElementById("bio-col-right");

const compareBeforeDate = document.getElementById("compare-before-date");
const compareAfterDate = document.getElementById("compare-after-date");
const compareWeeks = document.getElementById("compare-weeks");
const compareBeforeStats = document.getElementById("compare-before-stats");
const compareAfterStats = document.getElementById("compare-after-stats");
const deltaBadgesRow = document.getElementById("delta-badges-row");

const trendChart = document.getElementById("trend-chart");
const trendMonthLabels = document.getElementById("trend-month-labels");

const countdownPill = document.getElementById("countdown-pill");
const countdownText = document.getElementById("countdown-text");

const attractEyebrowText = document.getElementById("attract-eyebrow-text");
const attractLine1 = document.getElementById("attract-line1");
const attractLine2 = document.getElementById("attract-line2");
const attractCtaText = document.getElementById("attract-cta-text");
const attractTiles = document.getElementById("attract-tiles");
const attractTime = document.getElementById("attract-time");
const attractDate = document.getElementById("attract-date");

function speak(text) {
  if (!("speechSynthesis" in window)) return;
  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "pt-BR";
  utterance.rate = 0.95;
  window.speechSynthesis.speak(utterance);
}

function ptBr(value, decimals) {
  return value.toLocaleString("pt-BR", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

function setBleState(value, label) {
  bleStatus.dataset.state = value;
  bleStatus.querySelector(".label").textContent = label;
}

// -- Tela de descanso / mídia ------------------------------------------

const ATTRACT_MESSAGES = [
  {
    eyebrow: "MISCALE ANALYTICS · BIOIMPEDÂNCIA",
    line1: "ANÁLISE CORPORAL",
    line2: "INTELIGENTE",
    cta: "TOQUE PARA COMEÇAR",
    tiles: [
      { v: "60s", l: "Medição completa" },
      { v: "12", l: "Indicadores corporais" },
      { v: "Antes/Depois", l: "Fotos da sua evolução" },
    ],
  },
  {
    eyebrow: "BIOIMPEDÂNCIA ELÉTRICA",
    line1: "DESCUBRA O QUE",
    line2: "A BALANÇA ESCONDE",
    cta: "COMECE SUA MEDIÇÃO",
    tiles: [
      { v: "Músculo", l: "Massa muscular estimada" },
      { v: "Gordura", l: "Visceral e corporal" },
      { v: "Água", l: "Hidratação corporal" },
    ],
  },
  {
    eyebrow: "ACOMPANHE SUA EVOLUÇÃO",
    line1: "SEU CORPO EM",
    line2: "NÚMEROS REAIS",
    cta: "TOQUE E MEÇA AGORA",
    tiles: [
      { v: "Score", l: "Pontuação corporal 0–100" },
      { v: "Histórico", l: "Todas as suas medições" },
      { v: "PDF", l: "Relatório automático" },
    ],
  },
  {
    eyebrow: "SIMPLES E RÁPIDO",
    line1: "SUBA NA BALANÇA.",
    line2: "PRONTO.",
    cta: "INICIAR AGORA",
    tiles: [
      { v: "BMR", l: "Sua taxa metabólica" },
      { v: "IMC", l: "Índice de massa corporal" },
      { v: "Grátis", l: "Incluso no seu plano" },
    ],
  },
];
const ATTRACT_ROTATE_MS = 18000;

const attractState = { index: 0, rotateTimer: null, clockTimer: null };

function renderAttractMessage(index) {
  const m = ATTRACT_MESSAGES[index];
  attractEyebrowText.textContent = m.eyebrow;
  attractLine1.textContent = m.line1;
  attractLine2.textContent = m.line2;
  attractCtaText.textContent = m.cta;
  attractTiles.innerHTML = "";
  for (const tile of m.tiles) {
    const el = document.createElement("div");
    el.className = "attract-tile";
    const value = document.createElement("div");
    value.className = "attract-tile-value";
    value.textContent = tile.v;
    const label = document.createElement("div");
    label.className = "attract-tile-label";
    label.textContent = tile.l;
    el.append(value, label);
    attractTiles.appendChild(el);
  }
}

function updateAttractClock() {
  const now = new Date();
  const dias = ["domingo", "segunda", "terça", "quarta", "quinta", "sexta", "sábado"];
  const meses = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
  ];
  const p = (n) => String(n).padStart(2, "0");
  attractTime.textContent = `${p(now.getHours())}:${p(now.getMinutes())}`;
  attractDate.textContent = `${dias[now.getDay()]}, ${now.getDate()} de ${meses[now.getMonth()]}`;
}

function attractFadables() {
  return [attractEyebrowText, attractLine1, attractLine2, attractCtaText, ...attractTiles.children];
}

function startAttractRotation() {
  attractState.index = 0;
  renderAttractMessage(0);
  updateAttractClock();
  attractState.clockTimer = setInterval(updateAttractClock, 1000);
  attractState.rotateTimer = setInterval(() => {
    for (const el of attractFadables()) el.style.opacity = "0";
    setTimeout(() => {
      attractState.index = (attractState.index + 1) % ATTRACT_MESSAGES.length;
      renderAttractMessage(attractState.index);
      for (const el of attractFadables()) el.style.opacity = "1";
    }, 700);
  }, ATTRACT_ROTATE_MS);
}

function stopAttractRotation() {
  clearInterval(attractState.rotateTimer);
  clearInterval(attractState.clockTimer);
  attractState.rotateTimer = null;
  attractState.clockTimer = null;
}

// -- Navegação entre telas ----------------------------------------------

let attractIdleTimer = null;

function armAttractIdleTimer() {
  clearTimeout(attractIdleTimer);
  if (state.screen === "idle" || state.screen === "pin") {
    attractIdleTimer = setTimeout(goToAttract, ATTRACT_IDLE_TIMEOUT_MS);
  }
}

function showScreen(name) {
  if (state.screen === "attract" && name !== "attract") stopAttractRotation();
  state.screen = name;
  for (const [key, el] of Object.entries(screens)) el.hidden = key !== name;
  if (name === "attract") startAttractRotation();
  armAttractIdleTimer();
}

function _clearAuthState() {
  if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  state.documentBuffer = "";
  state.pendingIdentifier = null;
  state.pinBuffer = "";
  idError.textContent = "";
  pinError.textContent = "";
  renderIdDisplay();
  renderPinDisplay();
  stopCountdown();
  stopClock();
}

function resetToIdle() {
  _clearAuthState();
  showScreen("idle");
}

function goToAttract() {
  _clearAuthState();
  showScreen("attract");
}

function goToPin() {
  state.pinBuffer = "";
  pinError.textContent = "";
  pinHint.textContent = "Digite seu PIN de 4 dígitos";
  renderPinDisplay();
  showScreen("pin");
}

// -- Tela de identificação -------------------------------------------------

function renderIdDisplay() {
  idDigits.forEach((el, i) => {
    const filled = i < state.documentBuffer.length;
    el.textContent = filled ? state.documentBuffer[i] : "_";
    el.dataset.filled = filled ? "true" : "false";
  });
}

function handleIdDigit(digit) {
  if (state.documentBuffer.length >= DOCUMENT_MAX_LEN) return;
  state.documentBuffer += digit;
  renderIdDisplay();
  if (state.documentBuffer.length === DOCUMENT_MAX_LEN) {
    state.pendingIdentifier = { document: state.documentBuffer };
    goToPin();
  }
}

function handleIdEnter() {
  if (state.documentBuffer.length >= 10) {
    state.pendingIdentifier = { document: state.documentBuffer };
    goToPin();
  }
}

function handleIdBackspace() {
  state.documentBuffer = state.documentBuffer.slice(0, -1);
  renderIdDisplay();
}

function renderSuggestions(suggestions) {
  suggestionCards.innerHTML = "";
  if (!suggestions || suggestions.length === 0) {
    suggestionsBlock.hidden = true;
    return;
  }
  suggestionsBlock.hidden = false;
  for (const candidate of suggestions) {
    const card = document.createElement("button");
    card.type = "button";
    card.className = "suggestion-card";
    card.textContent = candidate.name;
    card.addEventListener("click", () => {
      state.pendingIdentifier = { client_id: candidate.id };
      goToPin();
    });
    suggestionCards.appendChild(card);
  }
}

// -- Tela de PIN -------------------------------------------------------

function renderPinDisplay() {
  pinDots.forEach((el, i) => {
    el.dataset.filled = i < state.pinBuffer.length ? "true" : "false";
  });
}

async function handlePinDigit(digit) {
  if (state.pinBuffer.length >= PIN_LEN) return;
  state.pinBuffer += digit;
  renderPinDisplay();
  if (state.pinBuffer.length === PIN_LEN) {
    await submitLogin();
  }
}

function handlePinBackspace() {
  if (state.pinBuffer.length > 0) {
    state.pinBuffer = state.pinBuffer.slice(0, -1);
    renderPinDisplay();
  } else {
    resetToIdle();
  }
}

async function submitLogin() {
  const body = { pin: state.pinBuffer, ...state.pendingIdentifier };
  const response = await fetch("/api/kiosk/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (response.ok) {
    return; // a tela muda ao receber "session_started" pelo WebSocket
  }

  const error = await response.json().catch(() => ({}));
  pinError.textContent = error.error ?? "não foi possível entrar";
  state.pinBuffer = "";
  renderPinDisplay();
}

// -- Cabeçalho da sessão: avatar, subtítulo, relógio -----------------------

function initialsFor(fullName) {
  const parts = fullName.trim().split(/\s+/);
  const first = parts[0]?.[0] ?? "?";
  const last = parts.length > 1 ? parts[parts.length - 1][0] : "";
  return (first + last).toUpperCase();
}

function renderSessionHeader(client) {
  avatarCircle.textContent = initialsFor(client.full_name);
  sessionName.textContent = client.full_name;
  const sex = SEX_LABELS[client.sex] ?? client.sex;
  const algorithm = ALGORITHM_LABELS[client.algorithm] ?? client.algorithm;
  sessionSub.textContent = `${client.age} anos · ${sex} · ${ptBr(client.height_cm, 0)} cm · ${algorithm}`;
}

function updateClock() {
  const now = new Date();
  const p = (n) => String(n).padStart(2, "0");
  sessionClock.textContent = `${p(now.getHours())}:${p(now.getMinutes())}`;
}

function startClock() {
  stopClock();
  updateClock();
  state.clockTimer = setInterval(updateClock, 15000);
}

function stopClock() {
  if (state.clockTimer) {
    clearInterval(state.clockTimer);
    state.clockTimer = null;
  }
}

// -- Tela de sessão (medição) --------------------------------------------

function resetMetrics() {
  bioColLeft.innerHTML = "";
  bioColRight.innerHTML = "";
  scoreValueBig.textContent = "--";
  scoreTier.textContent = "—";
  scoreBarFill.style.height = "0%";
  weightTrend.textContent = "";
}

function scoreTierLabel(score) {
  if (score >= 80) return "EXCELENTE";
  if (score >= 65) return "BOM";
  if (score >= 45) return "REGULAR";
  return "ATENÇÃO";
}

async function fetchHistory() {
  try {
    // limit alto o bastante pra "Jornada" e a tendência refletirem o
    // histórico real do cliente, não só a janela recente
    const response = await fetch("/api/kiosk/history?limit=60");
    state.history = response.ok ? await response.json() : [];
  } catch (e) {
    state.history = [];
  }
}

function previousValueFor(metricId) {
  // state.history[0] é a medição que acabou de ser salva; a anterior é [1]
  const entry = state.history[1];
  const value = entry ? entry[metricId] : null;
  return value === undefined ? null : value;
}

function computeTrend(current, previous, decimals, unit) {
  if (previous === null || previous === undefined) return { text: "", dir: "flat" };
  const delta = current - previous;
  if (Math.abs(delta) < 0.5 / 10 ** decimals) return { text: "—", dir: "flat" };
  const arrow = delta > 0 ? "↗" : "↘";
  const sign = delta > 0 ? "+" : "";
  return { text: `${arrow} ${sign}${ptBr(delta, decimals)}${unit}`, dir: delta > 0 ? "up" : "down" };
}

function formatShortDate(iso) {
  return new Date(iso).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
}

function weeksBetween(isoA, isoB) {
  const ms = Math.abs(new Date(isoB) - new Date(isoA));
  return Math.round(ms / (7 * 24 * 60 * 60 * 1000));
}

// -- Cartões da coluna esquerda/direita (em volta da silhueta) -------------

function buildBioCard({ accent, label, valueText, unitText, note, noteDir }) {
  const card = document.createElement("div");
  card.className = "bio-metric-card";
  if (accent && accent !== "none") card.dataset.accent = accent;

  const labelEl = document.createElement("div");
  labelEl.className = "bio-metric-label";
  labelEl.textContent = label;
  card.appendChild(labelEl);

  const valueRow = document.createElement("div");
  valueRow.className = "bio-metric-value-row";
  const valueEl = document.createElement("span");
  valueEl.className = "bio-metric-value";
  valueEl.textContent = valueText;
  valueRow.appendChild(valueEl);
  if (unitText) {
    const unitEl = document.createElement("span");
    unitEl.className = "bio-metric-unit";
    unitEl.textContent = unitText;
    valueRow.appendChild(unitEl);
  }
  card.appendChild(valueRow);

  if (note) {
    const noteEl = document.createElement("div");
    noteEl.className = "bio-metric-note";
    noteEl.dataset.dir = noteDir || "flat";
    noteEl.textContent = note;
    card.appendChild(noteEl);
  }

  return card;
}

function hydrationStatus(waterPct) {
  if (waterPct < 45) return "Hidratação baixa";
  if (waterPct > 65) return "Hidratação elevada";
  return "Hidratação ideal";
}

function bmiStatus(bmi, range) {
  if (!range) return "";
  if (range.low != null && bmi < range.low) return "Abaixo do peso";
  if (range.high != null && bmi > range.high) return "Acima do peso";
  return "Peso normal";
}

function renderBioColumns(message) {
  const m = message.metrics;
  const w = message.weight_kg;
  const prev = state.history[1] || null;

  const fatMassKg = (w * m.fat_percentage) / 100;
  const prevFatMassKg = prev ? (prev.weight_kg * prev.fat_percentage) / 100 : null;
  const waterLiters = (w * m.water_percentage) / 100;
  const musclePct = (m.muscle_mass_kg / w) * 100;
  const lbmKg = w - fatMassKg;

  const muscleTrend = computeTrend(m.muscle_mass_kg, prev?.muscle_mass_kg ?? null, 1, " kg");
  const fatTrend = computeTrend(fatMassKg, prevFatMassKg, 1, " kg");
  const visceralTrend = computeTrend(Math.round(m.visceral_fat), prev ? Math.round(prev.visceral_fat) : null, 0, " níveis");
  const bmrTrend = computeTrend(m.bmr_kcal, prev?.bmr_kcal ?? null, 0, " kcal");

  bioColLeft.innerHTML = "";
  bioColLeft.append(
    buildBioCard({
      accent: "cyan",
      label: "MASSA MUSCULAR",
      valueText: ptBr(m.muscle_mass_kg, 1),
      unitText: `kg · ${ptBr(musclePct, 0)}%`,
      note: muscleTrend.text,
      noteDir: muscleTrend.dir,
    }),
    buildBioCard({
      accent: "orange",
      label: "GORDURA CORPORAL",
      valueText: ptBr(fatMassKg, 1),
      unitText: `kg · ${ptBr(m.fat_percentage, 1)}%`,
      note: fatTrend.text,
      noteDir: fatTrend.dir,
    }),
    buildBioCard({
      accent: "none",
      label: "ÁGUA CORPORAL",
      valueText: ptBr(waterLiters, 1),
      unitText: `L · ${ptBr(m.water_percentage, 1)}%`,
      note: hydrationStatus(m.water_percentage),
      noteDir: "flat",
    })
  );

  const visceralRange = message.ranges?.visceral_fat;
  const visceralNote =
    visceralTrend.text && visceralRange && m.visceral_fat < (visceralRange.high ?? Infinity)
      ? `${visceralTrend.text} · faixa saudável`
      : visceralTrend.text || (visceralRange && m.visceral_fat < (visceralRange.high ?? Infinity) ? "faixa saudável" : "");

  bioColRight.innerHTML = "";
  bioColRight.append(
    buildBioCard({
      accent: "amber",
      label: "GORDURA VISCERAL",
      valueText: `Nível ${ptBr(m.visceral_fat, 0)}`,
      unitText: "",
      note: visceralNote,
      noteDir: visceralTrend.dir,
    }),
    buildBioCard({
      accent: "none",
      label: "TAXA METABÓLICA (BMR)",
      valueText: ptBr(m.bmr_kcal, 0),
      unitText: "kcal/dia",
      note: bmrTrend.text,
      noteDir: bmrTrend.dir,
    }),
    buildBioCard({
      accent: "none",
      label: "IMC / MASSA MAGRA",
      valueText: ptBr(m.bmi, 1),
      unitText: `· ${ptBr(lbmKg, 1)} kg LBM`,
      note: bmiStatus(m.bmi, message.ranges?.bmi),
      noteDir: "flat",
    })
  );
}

// -- Antes / Depois + selos de delta ---------------------------------------

function buildCompareStat(label, value, unit, decimals) {
  const stat = document.createElement("div");
  stat.className = "compare-stat";
  const labelEl = document.createElement("span");
  labelEl.className = "compare-stat-label";
  labelEl.textContent = label;
  const valueEl = document.createElement("span");
  valueEl.className = "compare-stat-value";
  valueEl.textContent = value === null || value === undefined ? "—" : `${ptBr(value, decimals)}${unit}`;
  stat.append(labelEl, valueEl);
  return stat;
}

function buildDeltaBadge(accent, valueText, label) {
  const badge = document.createElement("div");
  badge.className = "delta-badge";
  badge.dataset.accent = accent;
  const valueEl = document.createElement("span");
  valueEl.className = "delta-badge-value";
  valueEl.textContent = valueText;
  const labelEl = document.createElement("span");
  labelEl.className = "delta-badge-label";
  labelEl.textContent = label;
  badge.append(valueEl, labelEl);
  return badge;
}

function renderCompareSection(message) {
  // Fotos de evolução ainda não são capturadas pelo quiosque (RF futuro) —
  // esta seção usa peso/gordura/músculo reais do histórico só pra já
  // validar o layout; o slot de foto fica como placeholder de propósito.
  compareBeforeStats.innerHTML = "";
  compareAfterStats.innerHTML = "";
  deltaBadgesRow.innerHTML = "";

  if (state.history.length === 0) {
    compareBeforeDate.textContent = "—";
    compareAfterDate.textContent = "—";
    compareWeeks.textContent = "—";
    return;
  }

  const newest = state.history[0];
  const oldest = state.history[state.history.length - 1];
  const hasBefore = state.history.length > 1;

  compareAfterDate.textContent = formatShortDate(newest.recorded_at);
  compareBeforeDate.textContent = hasBefore ? formatShortDate(oldest.recorded_at) : "primeira medição";
  compareWeeks.textContent = hasBefore ? `${weeksBetween(oldest.recorded_at, newest.recorded_at)} semanas` : "—";

  compareBeforeStats.append(
    buildCompareStat("Peso", hasBefore ? oldest.weight_kg : null, " kg", 1),
    buildCompareStat("Gordura", hasBefore ? oldest.fat_percentage : null, "%", 1),
    buildCompareStat("Músculo", hasBefore ? oldest.muscle_mass_kg : null, " kg", 1)
  );
  compareAfterStats.append(
    buildCompareStat("Peso", newest.weight_kg, " kg", 1),
    buildCompareStat("Gordura", newest.fat_percentage, "%", 1),
    buildCompareStat("Músculo", newest.muscle_mass_kg, " kg", 1)
  );

  if (!hasBefore) return;

  const fatMassNow = (newest.weight_kg * newest.fat_percentage) / 100;
  const fatMassBefore = (oldest.weight_kg * oldest.fat_percentage) / 100;
  const fatDelta = fatMassNow - fatMassBefore;
  const muscleDelta = newest.muscle_mass_kg - oldest.muscle_mass_kg;
  const scoreDelta =
    newest.body_score != null && oldest.body_score != null ? Math.round(newest.body_score - oldest.body_score) : null;

  deltaBadgesRow.append(
    buildDeltaBadge("orange", `${fatDelta >= 0 ? "+" : ""}${ptBr(fatDelta, 1)} kg`, "de gordura"),
    buildDeltaBadge("cyan", `${muscleDelta >= 0 ? "+" : ""}${ptBr(muscleDelta, 1)} kg`, "de músculo"),
    ...(scoreDelta === null
      ? []
      : [buildDeltaBadge("purple", `${scoreDelta >= 0 ? "+" : ""}${scoreDelta}`, "pontos de score")])
  );
}

// -- Tendência histórica (gordura % · massa muscular) -----------------------

function renderTrendChart() {
  const ns = "http://www.w3.org/2000/svg";
  trendChart.innerHTML = "";
  trendMonthLabels.innerHTML = "";

  const points = [...state.history]
    .reverse()
    .filter((p) => p.fat_percentage != null && p.muscle_mass_kg != null)
    .slice(-8);

  if (points.length < 2) {
    const empty = document.createElementNS(ns, "text");
    empty.setAttribute("x", "500");
    empty.setAttribute("y", "95");
    empty.setAttribute("text-anchor", "middle");
    empty.setAttribute("fill", "var(--ink-faint)");
    empty.setAttribute("font-size", "14");
    empty.textContent = "ainda sem histórico suficiente pra mostrar tendência";
    trendChart.appendChild(empty);
    return;
  }

  const width = 1000;
  const height = 190;
  const padX = 20;
  const padY = 30;

  [30, 95, 160].forEach((y) => {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("class", "grid-line");
    line.setAttribute("x1", "0");
    line.setAttribute("y1", y);
    line.setAttribute("x2", width);
    line.setAttribute("y2", y);
    trendChart.appendChild(line);
  });

  const xFor = (i) => padX + (i / (points.length - 1)) * (width - padX * 2);
  const drawSeries = (values, lineClass, pointClass) => {
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || 1;
    const yFor = (v) => height - padY - ((v - min) / range) * (height - padY * 2);

    const path = values.map((v, i) => `${i === 0 ? "M" : "L"} ${xFor(i)} ${yFor(v)}`).join(" ");
    const line = document.createElementNS(ns, "path");
    line.setAttribute("class", lineClass);
    line.setAttribute("d", path);
    trendChart.appendChild(line);

    values.forEach((v, i) => {
      const circle = document.createElementNS(ns, "circle");
      circle.setAttribute("class", pointClass);
      circle.setAttribute("cx", xFor(i));
      circle.setAttribute("cy", yFor(v));
      circle.setAttribute("r", i === values.length - 1 ? 7 : 4);
      circle.appendChild(document.createElementNS(ns, "title")).textContent = ptBr(v, 1);
      trendChart.appendChild(circle);
    });
  };

  drawSeries(points.map((p) => p.fat_percentage), "fat-line", "fat-point");
  drawSeries(points.map((p) => p.muscle_mass_kg), "muscle-line", "muscle-point");

  for (const p of points) {
    const label = document.createElement("span");
    label.textContent = new Date(p.recorded_at).toLocaleDateString("pt-BR", { month: "short" }).replace(".", "");
    trendMonthLabels.appendChild(label);
  }
}

// -- Orquestração do resultado ---------------------------------------------

async function renderMetricCards(message) {
  if (!message.metrics) {
    resetMetrics();
    return;
  }

  if (message.measurement_id) await fetchHistory();

  const weightTrendInfo = computeTrend(message.weight_kg, previousValueFor("weight_kg"), 1, " kg");
  weightTrend.textContent = weightTrendInfo.text;
  weightTrend.dataset.dir = weightTrendInfo.dir;

  const score = message.metrics.body_score;
  scoreValueBig.textContent = score.toFixed(0);
  scoreTier.textContent = scoreTierLabel(score);
  scoreBarFill.style.height = `${Math.max(0, Math.min(100, score))}%`;

  if (state.history.length > 1) {
    const oldest = state.history[state.history.length - 1];
    journeyWeeks.textContent = weeksBetween(oldest.recorded_at, state.history[0].recorded_at);
    journeyCount.textContent = `${state.history.length}ª medição registrada`;
  } else {
    journeyWeeks.textContent = "0";
    journeyCount.textContent = "primeira medição registrada";
  }

  renderBioColumns(message);
  renderCompareSection(message);
  renderTrendChart();
}

function setStatusPill(state_) {
  statusPill.dataset.state = state_;
  statusText.textContent = state_ === "measuring" ? "MEDINDO" : "MEDIÇÃO CONCLUÍDA";
}

function renderReading(message) {
  resetCountdown(); // espelha o timeout do servidor: toda leitura nova reseta os 30s

  if (!waitingCard.hidden) {
    waitingCard.hidden = true;
    sessionResults.hidden = false;
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
  }

  weightValue.textContent = ptBr(message.weight_kg, 1);
  weightUnit.textContent = message.unit;

  if (message.type === "partial") {
    weightHint.textContent = "medindo…";
    weightHint.dataset.warn = "false";
    setStatusPill("measuring");
    resetMetrics();
    return;
  }

  if (message.warning) {
    weightHint.textContent = message.warning;
    weightHint.dataset.warn = "true";
  } else {
    weightHint.textContent = "medição estabilizada";
    weightHint.dataset.warn = "false";
  }
  setStatusPill("done");

  renderMetricCards(message);
}

async function logout() {
  await fetch("/api/kiosk/logout", { method: "POST" });
}

logoutBtn.addEventListener("click", logout);

async function sendTouch() {
  const now = Date.now();
  if (now - state.lastTouchSentAt < 4000) return;
  state.lastTouchSentAt = now;
  resetCountdown();
  await fetch("/api/kiosk/touch", { method: "POST" });
}

// -- Contador de sessão (espelha o timeout de 30s do servidor) -------------

function updateCountdownDisplay() {
  countdownText.textContent = `tela libera em ${state.countdownSecondsLeft}s`;
}

function resetCountdown() {
  state.countdownSecondsLeft = SESSION_TIMEOUT_SECONDS;
  updateCountdownDisplay();
}

function startCountdown() {
  stopCountdown();
  countdownPill.hidden = false;
  resetCountdown();
  state.countdownTimer = setInterval(() => {
    state.countdownSecondsLeft = Math.max(0, state.countdownSecondsLeft - 1);
    updateCountdownDisplay();
  }, 1000);
}

function stopCountdown() {
  if (state.countdownTimer) {
    clearInterval(state.countdownTimer);
    state.countdownTimer = null;
  }
  countdownPill.hidden = true;
}

// -- Entrada do teclado numérico físico (USB) -----------------------------

function focusHardwareInput() {
  hardwareInput.focus({ preventScroll: true });
}

hardwareInput.addEventListener("keydown", (event) => {
  const key = event.key;

  if (state.screen === "session") {
    sendTouch();
    return; // nenhuma tecla controla a tela de sessão
  }

  if (state.screen === "attract") showScreen("idle"); // qualquer tecla acorda o descanso de tela

  if (/^[0-9]$/.test(key)) {
    event.preventDefault();
    if (state.screen === "idle") handleIdDigit(key);
    else if (state.screen === "pin") handlePinDigit(key);
  } else if (key === "Enter") {
    event.preventDefault();
    if (state.screen === "idle") handleIdEnter();
  } else if (key === "Backspace") {
    event.preventDefault();
    if (state.screen === "idle") handleIdBackspace();
    else if (state.screen === "pin") handlePinBackspace();
  }
  armAttractIdleTimer();
});

hardwareInput.addEventListener("input", () => {
  hardwareInput.value = ""; // o estado vive em `state`, não no input
});

document.addEventListener("click", (event) => {
  if (!event.target.closest("button")) focusHardwareInput();
});
document.addEventListener("click", () => {
  if (state.screen === "attract") showScreen("idle"); // toque também acorda o descanso de tela
});
document.addEventListener("click", (event) => {
  if (state.screen === "session") sendTouch();
});

setInterval(focusHardwareInput, 1000);

// -- WebSocket -----------------------------------------------------------

function connectWebSocket() {
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.addEventListener("open", () => setBleState("connected", "conectado"));
  ws.addEventListener("close", () => {
    setBleState("disconnected", "desconectado — tentando reconectar…");
    setTimeout(connectWebSocket, 2000);
  });
  ws.addEventListener("error", () => ws.close());
  ws.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);

    if (message.type === "idle_weight") {
      if (state.screen === "idle") renderSuggestions(message.suggestions);
      return;
    }
    if (message.type === "session_started") {
      state.documentBuffer = "";
      state.pendingIdentifier = null;
      state.pinBuffer = "";
      state.history = [];
      renderSessionHeader(message.client);
      weightValue.textContent = "--,-";
      weightHint.textContent = "suba na balança";
      weightHint.dataset.warn = "false";
      resetMetrics();
      setStatusPill("measuring");
      waitingCard.hidden = false;
      sessionResults.hidden = true;
      startCountdown();
      startClock();
      showScreen("session");
      speak("Suba na balança descalço, com um pé sobre cada par de sensores, e fique parado até a leitura ser concluída.");
      return;
    }
    if (message.type === "session_ended") {
      goToAttract();
      return;
    }
    if (message.type === "partial" || message.type === "final") {
      if (state.screen === "session") renderReading(message);
      return;
    }
  });
}

// -- Boot ------------------------------------------------------------------

async function boot() {
  try {
    const response = await fetch("/api/kiosk/state");
    const data = await response.json();
    if (data.status === "authenticated") {
      renderSessionHeader(data.client);
      setStatusPill("measuring");
      startCountdown();
      startClock();
      showScreen("session");
    } else {
      goToAttract();
    }
  } catch (e) {
    goToAttract();
  }
  focusHardwareInput();
}

boot();
connectWebSocket();
