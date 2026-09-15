const METRIC_LABELS = {
  bmi: (v) => v.toFixed(1),
  fat_percentage: (v) => `${v.toFixed(1)}%`,
  water_percentage: (v) => `${v.toFixed(1)}%`,
  bone_mass_kg: (v) => `${v.toFixed(2)} kg`,
  muscle_mass_kg: (v) => `${v.toFixed(1)} kg`,
  visceral_fat: (v) => v.toFixed(1),
  bmr_kcal: (v) => `${v.toFixed(0)} kcal`,
  protein_percentage: (v) => `${v.toFixed(1)}%`,
  metabolic_age: (v) => `${v.toFixed(0)} anos`,
};

const ALGORITHM_LABELS = { xiaomi: "Xiaomi/Zepp Life", science: "Científico" };

const state = {
  profiles: [],
  editingProfileId: null,
  historyProfileId: null,
};

// -- Elementos ---------------------------------------------------------

const bleStatus = document.getElementById("ble-status");
const weightValue = document.getElementById("weight-value");
const weightUnit = document.getElementById("weight-unit");
const weightOwner = document.getElementById("weight-owner");
const weightHint = document.getElementById("weight-hint");
const metricsGrid = document.getElementById("metrics-grid");
const bodyScoreBadge = document.getElementById("body-score");
const bodyScoreValue = bodyScoreBadge.querySelector(".body-score-value");
const confirmBanner = document.getElementById("confirm-banner");
const confirmWeight = document.getElementById("confirm-weight");
const confirmOptions = document.getElementById("confirm-options");

const profileList = document.getElementById("profile-list");
const profileForm = document.getElementById("profile-form");
const profileIdInput = document.getElementById("profile-id");
const profileName = document.getElementById("profile-name");
const profileHeight = document.getElementById("profile-height");
const profileAge = document.getElementById("profile-age");
const profileSex = document.getElementById("profile-sex");
const profileAlgorithm = document.getElementById("profile-algorithm");
const profileSubmit = document.getElementById("profile-submit");
const profileCancel = document.getElementById("profile-cancel");
const profileSaved = document.getElementById("profile-saved");

const historyProfileSelect = document.getElementById("history-profile");
const historyMetricSelect = document.getElementById("history-metric");
const exportCsvLink = document.getElementById("export-csv");
const exportJsonLink = document.getElementById("export-json");
const trendChart = document.getElementById("trend-chart");
const historyEmpty = document.getElementById("history-empty");

// -- Leitura da balança --------------------------------------------------

function setBleState(state_, label) {
  bleStatus.dataset.state = state_;
  bleStatus.querySelector(".label").textContent = label;
}

function resetMetrics() {
  metricsGrid.querySelectorAll(".metric").forEach((el) => {
    el.querySelector(".metric-value").textContent = "--";
  });
}

function renderReading(message) {
  if (message.type === "needs_confirmation") {
    showConfirmBanner(message);
    return;
  }

  hideConfirmBanner();
  weightValue.textContent = message.weight_kg.toFixed(2);
  weightUnit.textContent = message.unit;

  if (message.type === "partial") {
    weightOwner.textContent = "";
    weightHint.textContent = "medindo…";
    weightHint.dataset.warn = "false";
    resetMetrics();
    bodyScoreBadge.hidden = true;
    return;
  }

  if (message.is_guest) {
    weightOwner.textContent = "convidado";
  } else if (message.profile) {
    const algo = ALGORITHM_LABELS[message.algorithm] ?? message.algorithm;
    weightOwner.textContent = `${message.profile.name} · ${algo}`;
  } else {
    weightOwner.textContent = "";
  }

  if (message.warning) {
    weightHint.textContent = message.warning;
    weightHint.dataset.warn = "true";
  } else {
    weightHint.textContent = "medição estabilizada";
    weightHint.dataset.warn = "false";
  }

  if (message.metrics) {
    for (const [key, value] of Object.entries(message.metrics)) {
      const el = metricsGrid.querySelector(`[data-metric="${key}"] .metric-value`);
      const format = METRIC_LABELS[key];
      if (el && format) el.textContent = format(value);
    }
    const score = message.metrics.body_score;
    bodyScoreValue.textContent = score.toFixed(0);
    bodyScoreBadge.dataset.level = score < 40 ? "low" : score < 70 ? "mid" : "high";
    bodyScoreBadge.hidden = false;
  } else {
    resetMetrics();
    bodyScoreBadge.hidden = true;
  }

  if (message.profile && message.profile.id === state.historyProfileId) {
    loadHistory(state.historyProfileId);
  }
}

function showConfirmBanner(message) {
  confirmWeight.textContent = message.weight_kg.toFixed(2);
  confirmOptions.innerHTML = "";

  for (const candidate of message.candidates) {
    const button = document.createElement("button");
    button.textContent = candidate.name;
    button.addEventListener("click", () => confirmMeasurement(message.pending_id, candidate.id));
    confirmOptions.appendChild(button);
  }

  const guestButton = document.createElement("button");
  guestButton.textContent = "Convidado";
  guestButton.className = "guest";
  guestButton.addEventListener("click", () => confirmMeasurement(message.pending_id, null));
  confirmOptions.appendChild(guestButton);

  confirmBanner.hidden = false;
}

function hideConfirmBanner() {
  confirmBanner.hidden = true;
}

async function confirmMeasurement(pendingId, profileId) {
  await fetch("/api/measurements/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pending_id: pendingId, profile_id: profileId }),
  });
  hideConfirmBanner();
}

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
    renderReading(JSON.parse(event.data));
  });
}

// -- Perfis (RF05/RF06) ---------------------------------------------------

async function fetchProfiles() {
  const response = await fetch("/api/profiles");
  state.profiles = await response.json();
  renderProfileList();
  renderHistoryProfileSelect();
}

function renderProfileList() {
  profileList.innerHTML = "";
  if (state.profiles.length === 0) {
    const li = document.createElement("li");
    li.textContent = "nenhum perfil cadastrado — medições serão de convidado";
    profileList.appendChild(li);
    return;
  }

  for (const profile of state.profiles) {
    const li = document.createElement("li");

    const info = document.createElement("span");
    info.innerHTML = `${profile.name} <span class="profile-meta">${profile.height_cm}cm · ${profile.age}a · ${
      profile.sex === "female" ? "F" : "M"
    } · ${ALGORITHM_LABELS[profile.algorithm]}</span>`;

    const actions = document.createElement("div");
    actions.className = "profile-actions";

    const editButton = document.createElement("button");
    editButton.textContent = "Editar";
    editButton.addEventListener("click", () => startEditProfile(profile));

    const deleteButton = document.createElement("button");
    deleteButton.textContent = "Excluir";
    deleteButton.className = "danger";
    deleteButton.addEventListener("click", () => deleteProfile(profile.id));

    actions.append(editButton, deleteButton);
    li.append(info, actions);
    profileList.appendChild(li);
  }
}

function startEditProfile(profile) {
  state.editingProfileId = profile.id;
  profileIdInput.value = profile.id;
  profileName.value = profile.name;
  profileHeight.value = profile.height_cm;
  profileAge.value = profile.age;
  profileSex.value = profile.sex;
  profileAlgorithm.value = profile.algorithm;
  profileSubmit.textContent = "Salvar alterações";
  profileCancel.hidden = false;
}

function resetProfileForm() {
  state.editingProfileId = null;
  profileForm.reset();
  profileIdInput.value = "";
  profileSubmit.textContent = "Adicionar perfil";
  profileCancel.hidden = true;
}

profileCancel.addEventListener("click", resetProfileForm);

profileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = {
    name: profileName.value.trim(),
    height_cm: Number(profileHeight.value),
    age: Number(profileAge.value),
    sex: profileSex.value,
    algorithm: profileAlgorithm.value,
  };

  const isEditing = state.editingProfileId !== null;
  const url = isEditing ? `/api/profiles/${state.editingProfileId}` : "/api/profiles";
  const response = await fetch(url, {
    method: isEditing ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (response.ok) {
    profileSaved.textContent = isEditing ? "perfil atualizado" : "perfil criado";
    setTimeout(() => (profileSaved.textContent = ""), 2000);
    resetProfileForm();
    await fetchProfiles();
  } else {
    const error = await response.json();
    profileSaved.textContent = `erro: ${error.error ?? "não foi possível salvar"}`;
  }
});

async function deleteProfile(profileId) {
  await fetch(`/api/profiles/${profileId}`, { method: "DELETE" });
  if (state.editingProfileId === profileId) resetProfileForm();
  await fetchProfiles();
}

// -- Histórico e tendência (RF07/RF09) ------------------------------------

function renderHistoryProfileSelect() {
  const previous = historyProfileSelect.value;
  historyProfileSelect.innerHTML = "";

  for (const profile of state.profiles) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.name;
    historyProfileSelect.appendChild(option);
  }

  const restored = state.profiles.some((p) => String(p.id) === previous);
  historyProfileSelect.value = restored ? previous : state.profiles[0]?.id ?? "";
  state.historyProfileId = historyProfileSelect.value ? Number(historyProfileSelect.value) : null;
  loadHistory(state.historyProfileId);
}

historyProfileSelect.addEventListener("change", () => {
  state.historyProfileId = historyProfileSelect.value ? Number(historyProfileSelect.value) : null;
  loadHistory(state.historyProfileId);
});

historyMetricSelect.addEventListener("change", () => loadHistory(state.historyProfileId));

async function loadHistory(profileId) {
  if (!profileId) {
    trendChart.innerHTML = "";
    historyEmpty.hidden = false;
    exportCsvLink.removeAttribute("href");
    exportJsonLink.removeAttribute("href");
    return;
  }

  exportCsvLink.href = `/api/profiles/${profileId}/measurements/export?format=csv`;
  exportJsonLink.href = `/api/profiles/${profileId}/measurements/export?format=json`;

  const response = await fetch(`/api/profiles/${profileId}/measurements?limit=100`);
  const measurements = (await response.json()).reverse(); // API retorna mais recente primeiro
  renderTrendChart(measurements, historyMetricSelect.value);
}

function renderTrendChart(measurements, metricKey) {
  const points = measurements
    .map((m) => m[metricKey])
    .map((value, index) => ({ index, value }))
    .filter((p) => p.value !== null && p.value !== undefined);

  trendChart.innerHTML = "";

  if (points.length < 2) {
    historyEmpty.hidden = false;
    return;
  }
  historyEmpty.hidden = true;

  const width = 640;
  const height = 200;
  const padding = 16;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const xFor = (i) => padding + (i / (points.length - 1)) * (width - padding * 2);
  const yFor = (v) => height - padding - ((v - min) / range) * (height - padding * 2);

  const ns = "http://www.w3.org/2000/svg";

  const axis = document.createElementNS(ns, "line");
  axis.setAttribute("class", "axis");
  axis.setAttribute("x1", padding);
  axis.setAttribute("y1", height - padding);
  axis.setAttribute("x2", width - padding);
  axis.setAttribute("y2", height - padding);
  trendChart.appendChild(axis);

  const path = points.map((p, i) => `${i === 0 ? "M" : "L"} ${xFor(i)} ${yFor(p.value)}`).join(" ");
  const line = document.createElementNS(ns, "path");
  line.setAttribute("class", "line");
  line.setAttribute("d", path);
  trendChart.appendChild(line);

  for (const [i, p] of points.entries()) {
    const circle = document.createElementNS(ns, "circle");
    circle.setAttribute("class", "point");
    circle.setAttribute("cx", xFor(i));
    circle.setAttribute("cy", yFor(p.value));
    circle.setAttribute("r", 3);
    circle.appendChild(document.createElementNS(ns, "title")).textContent = p.value.toFixed(1);
    trendChart.appendChild(circle);
  }
}

// -- Boot ------------------------------------------------------------------

fetchProfiles();
connectWebSocket();
