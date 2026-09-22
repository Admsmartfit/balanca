const ALGORITHM_LABELS = { xiaomi: "Xiaomi/Zepp Life", science: "Científico" };
const SEX_LABELS = { male: "M", female: "F" };

const state = { editingClientId: null, resetPinClientId: null, clients: [] };

// -- Elementos --------------------------------------------------------

const loginScreen = document.getElementById("login-screen");
const appScreen = document.getElementById("app-screen");
const loginForm = document.getElementById("login-form");
const loginEmail = document.getElementById("login-email");
const loginPassword = document.getElementById("login-password");
const loginError = document.getElementById("login-error");
const adminEmailEl = document.getElementById("admin-email");
const logoutBtn = document.getElementById("logout-btn");

const clientsTbody = document.getElementById("clients-tbody");
const clientsEmpty = document.getElementById("clients-empty");
const newClientBtn = document.getElementById("new-client-btn");

const clientFormPanel = document.getElementById("client-form-panel");
const clientForm = document.getElementById("client-form");
const clientFormTitle = document.getElementById("client-form-title");
const clientIdInput = document.getElementById("client-id");
const clientName = document.getElementById("client-name");
const clientDocument = document.getElementById("client-document");
const clientBirthdate = document.getElementById("client-birthdate");
const clientSex = document.getElementById("client-sex");
const clientHeight = document.getElementById("client-height");
const clientAlgorithm = document.getElementById("client-algorithm");
const clientPinField = document.getElementById("client-pin-field");
const clientPin = document.getElementById("client-pin");
const clientTermsRow = document.getElementById("client-terms-row");
const clientTerms = document.getElementById("client-terms");
const clientFormCancel = document.getElementById("client-form-cancel");
const clientFormError = document.getElementById("client-form-error");

const historyPanel = document.getElementById("history-panel");
const historyTitle = document.getElementById("history-title");
const historyTbody = document.getElementById("history-tbody");
const historyEmpty = document.getElementById("history-empty");
const historyClose = document.getElementById("history-close");
const exportCsvLink = document.getElementById("export-csv");
const exportJsonLink = document.getElementById("export-json");

const pinModal = document.getElementById("pin-modal");
const pinModalName = document.getElementById("pin-modal-name");
const pinModalForm = document.getElementById("pin-modal-form");
const pinModalValue = document.getElementById("pin-modal-value");
const pinModalCancel = document.getElementById("pin-modal-cancel");
const pinModalError = document.getElementById("pin-modal-error");

// -- Sessão --------------------------------------------------------------

async function checkSession() {
  const response = await fetch("/api/admin/me");
  if (response.ok) {
    const admin = await response.json();
    adminEmailEl.textContent = admin.email;
    loginScreen.hidden = true;
    appScreen.hidden = false;
    await loadClients();
  } else {
    loginScreen.hidden = false;
    appScreen.hidden = true;
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.textContent = "";
  const response = await fetch("/api/admin/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email: loginEmail.value, password: loginPassword.value }),
  });
  if (response.ok) {
    loginPassword.value = "";
    await checkSession();
  } else {
    const error = await response.json().catch(() => ({}));
    loginError.textContent = error.error ?? "não foi possível entrar";
  }
});

logoutBtn.addEventListener("click", async () => {
  await fetch("/api/admin/logout", { method: "POST" });
  await checkSession();
});

// -- Lista de clientes -----------------------------------------------------

async function loadClients() {
  const response = await fetch("/api/admin/clients");
  if (response.status === 401) return checkSession();
  state.clients = await response.json();
  renderClients();
}

function renderClients() {
  clientsTbody.innerHTML = "";
  clientsEmpty.hidden = state.clients.length > 0;

  for (const client of state.clients) {
    const tr = document.createElement("tr");

    const cells = [
      client.full_name,
      client.document,
      `${client.age}`,
      SEX_LABELS[client.sex] ?? client.sex,
      `${client.height_cm} cm`,
      ALGORITHM_LABELS[client.algorithm] ?? client.algorithm,
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }

    const actionsTd = document.createElement("td");
    actionsTd.className = "row-actions";

    const historyBtn = _actionButton("Histórico", () => openHistory(client));
    const editBtn = _actionButton("Editar", () => startEditClient(client));
    const pinBtn = _actionButton("Resetar PIN", () => openPinModal(client));
    const deleteBtn = _actionButton("Excluir", () => deleteClient(client), true);

    actionsTd.append(historyBtn, editBtn, pinBtn, deleteBtn);
    tr.appendChild(actionsTd);
    clientsTbody.appendChild(tr);
  }
}

function _actionButton(label, onClick, danger = false) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.textContent = label;
  if (danger) btn.className = "danger";
  btn.addEventListener("click", onClick);
  return btn;
}

// -- Formulário de cliente (criar/editar) ---------------------------------

function openClientForm({ editing }) {
  clientFormError.textContent = "";
  clientPinField.hidden = editing;
  clientPin.required = !editing;
  clientTermsRow.hidden = editing;
  clientFormPanel.hidden = false;
  clientFormPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

newClientBtn.addEventListener("click", () => {
  state.editingClientId = null;
  clientForm.reset();
  clientIdInput.value = "";
  clientFormTitle.textContent = "Novo cliente";
  openClientForm({ editing: false });
});

function startEditClient(client) {
  state.editingClientId = client.id;
  clientIdInput.value = client.id;
  clientName.value = client.full_name;
  clientDocument.value = client.document;
  clientBirthdate.value = client.birthdate;
  clientSex.value = client.sex;
  clientHeight.value = client.height_cm;
  clientAlgorithm.value = client.algorithm;
  clientFormTitle.textContent = `Editar ${client.full_name}`;
  openClientForm({ editing: true });
}

clientFormCancel.addEventListener("click", () => {
  clientFormPanel.hidden = true;
});

clientForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clientFormError.textContent = "";

  const isEditing = state.editingClientId !== null;
  const body = {
    full_name: clientName.value.trim(),
    document: clientDocument.value.trim(),
    birthdate: clientBirthdate.value,
    sex: clientSex.value,
    height_cm: Number(clientHeight.value),
    algorithm: clientAlgorithm.value,
  };
  if (!isEditing) {
    body.pin = clientPin.value.trim();
    body.accepted_terms = clientTerms.checked;
  }

  const url = isEditing ? `/api/admin/clients/${state.editingClientId}` : "/api/admin/clients";
  const response = await fetch(url, {
    method: isEditing ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (response.ok) {
    clientFormPanel.hidden = true;
    await loadClients();
  } else {
    const error = await response.json().catch(() => ({}));
    clientFormError.textContent = error.error ?? "não foi possível salvar";
  }
});

async function deleteClient(client) {
  if (!confirm(`Excluir ${client.full_name}? O histórico de medições também será apagado.`)) return;
  await fetch(`/api/admin/clients/${client.id}`, { method: "DELETE" });
  await loadClients();
}

// -- Reset de PIN ------------------------------------------------------

function openPinModal(client) {
  state.resetPinClientId = client.id;
  pinModalName.textContent = client.full_name;
  pinModalValue.value = "";
  pinModalError.textContent = "";
  pinModal.hidden = false;
}

pinModalCancel.addEventListener("click", () => (pinModal.hidden = true));

pinModalForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const response = await fetch(`/api/admin/clients/${state.resetPinClientId}/reset-pin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ new_pin: pinModalValue.value.trim() }),
  });
  if (response.ok) {
    pinModal.hidden = true;
  } else {
    const error = await response.json().catch(() => ({}));
    pinModalError.textContent = error.error ?? "não foi possível resetar o PIN";
  }
});

// -- Histórico -----------------------------------------------------------

async function openHistory(client) {
  state.historyClientId = client.id;
  historyTitle.textContent = `Histórico — ${client.full_name}`;
  exportCsvLink.href = `/api/admin/clients/${client.id}/measurements/export?format=csv`;
  exportJsonLink.href = `/api/admin/clients/${client.id}/measurements/export?format=json`;

  const response = await fetch(`/api/admin/clients/${client.id}/measurements?limit=100`);
  const measurements = await response.json();

  historyTbody.innerHTML = "";
  historyEmpty.hidden = measurements.length > 0;
  for (const m of measurements) {
    const tr = document.createElement("tr");
    const cells = [
      new Date(m.recorded_at).toLocaleString("pt-BR"),
      `${m.weight_kg.toFixed(1)} ${m.unit}`,
      m.bmi != null ? m.bmi.toFixed(1) : "—",
      m.fat_percentage != null ? `${m.fat_percentage.toFixed(1)}%` : "—",
      m.body_score != null ? m.body_score.toFixed(0) : "—",
    ];
    for (const text of cells) {
      const td = document.createElement("td");
      td.textContent = text;
      tr.appendChild(td);
    }

    const pdfTd = document.createElement("td");
    if (m.bmi != null) {
      // medições só de peso (sem impedância válida) não geram relatório de composição corporal
      const pdfLink = document.createElement("a");
      pdfLink.className = "pdf-link";
      pdfLink.textContent = "PDF";
      pdfLink.href = `/api/admin/clients/${client.id}/measurements/${m.id}/report`;
      pdfLink.target = "_blank";
      pdfTd.appendChild(pdfLink);
    } else {
      pdfTd.textContent = "—";
    }
    tr.appendChild(pdfTd);

    historyTbody.appendChild(tr);
  }

  await loadPhotos(client.id);

  historyPanel.hidden = false;
  historyPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

historyClose.addEventListener("click", () => (historyPanel.hidden = true));

// -- Fotos de evolução -----------------------------------------------------

const photoInput = document.getElementById("photo-input");
const photoGrid = document.getElementById("photo-grid");
const photosEmpty = document.getElementById("photos-empty");
const photoModal = document.getElementById("photo-modal");
const photoModalImg = document.getElementById("photo-modal-img");
const photoModalClose = document.getElementById("photo-modal-close");
const photoModalDelete = document.getElementById("photo-modal-delete");

async function loadPhotos(clientId) {
  const response = await fetch(`/api/admin/clients/${clientId}/photos`);
  const photos = response.ok ? await response.json() : [];

  photoGrid.innerHTML = "";
  photosEmpty.hidden = photos.length > 0;
  for (const photo of photos) {
    const thumb = document.createElement("div");
    thumb.className = "photo-thumb";

    const img = document.createElement("img");
    img.src = `/api/admin/clients/${clientId}/photos/${photo.id}/file`;
    img.alt = `Foto de evolução de ${new Date(photo.taken_at).toLocaleDateString("pt-BR")}`;
    thumb.appendChild(img);

    const dateLabel = document.createElement("span");
    dateLabel.className = "photo-date";
    dateLabel.textContent = new Date(photo.taken_at).toLocaleDateString("pt-BR");
    thumb.appendChild(dateLabel);

    thumb.addEventListener("click", () => openPhotoModal(clientId, photo, img.src));
    photoGrid.appendChild(thumb);
  }
}

function openPhotoModal(clientId, photo, src) {
  photoModalImg.src = src;
  photoModalDelete.onclick = async () => {
    if (!confirm("Excluir esta foto?")) return;
    await fetch(`/api/admin/clients/${clientId}/photos/${photo.id}`, { method: "DELETE" });
    photoModal.hidden = true;
    await loadPhotos(clientId);
  };
  photoModal.hidden = false;
}

photoModalClose.addEventListener("click", () => (photoModal.hidden = true));

photoInput.addEventListener("change", async () => {
  const file = photoInput.files[0];
  if (!file || !state.historyClientId) return;

  const formData = new FormData();
  formData.append("file", file);
  await fetch(`/api/admin/clients/${state.historyClientId}/photos`, { method: "POST", body: formData });
  photoInput.value = "";
  await loadPhotos(state.historyClientId);
});

// -- Boot ------------------------------------------------------------------

checkSession();
