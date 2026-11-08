const fieldLabels = {
  login: "Login",
  password: "Password",
  email: "Email",
  first_name: "First name",
  last_name: "Last name",
  phone: "Phone",
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function storageError(error) {
  if (error.message.includes("REPROBE_CREDENTIAL_KEY")) {
    return "Credential storage is not set up yet. Contact the person who manages this Reprobe installation.";
  }
  return error.message;
}

export function mountCredentials(api, preview) {
  const get = (id) => document.getElementById(id);
  const picker = get("credential-picker");
  const manager = get("credential-manager");
  const form = get("credential-form");
  const message = get("credential-message");
  const manage = get("credential-manage");
  const verification = get("credential-verification");
  const fallback = get("credential-fallback");
  const inputs = {};
  const placeholders = {};
  for (const field of Object.keys(fieldLabels)) {
    inputs[field] = get(`credential-${field.replaceAll("_", "-")}`);
    placeholders[field] = inputs[field].placeholder;
  }
  let credentials = [];
  let editingId = null;
  let busy = false;
  let loaded = false;
  const selected = new Set();

  function showMessage(text, success = false) {
    message.textContent = text;
    message.classList.toggle("success", success);
  }

  function selectedIds() {
    const ids = [];
    for (const input of picker.querySelectorAll("input:checked")) {
      ids.push(input.value);
    }
    return ids;
  }

  function setBusy(value) {
    busy = value;
    get("credential-selection").disabled = value || preview;
    get("credential-editor").disabled = value || preview;
    get("credential-close").disabled = value;
    get("credential-retry").disabled = value;
    get("start-run").disabled = value;
    manage.disabled = value || preview;
    for (const button of get("credential-list").querySelectorAll("button")) {
      button.disabled = value;
    }
  }

  function targetHost() {
    try {
      const url = new URL(get("target-url").value);
      if (!["http:", "https:"].includes(url.protocol)) return "";
      return url.hostname.replace(/\.$/, "");
    } catch {
      return "";
    }
  }

  function matchesHost(credential, host) {
    for (const domain of credential.allowed_domains) {
      if (domain === host) return true;
      if (domain.startsWith("*.")) {
        const base = domain.slice(2);
        if (host === base || host.endsWith(`.${base}`)) return true;
      }
    }
    return false;
  }

  function renderPicker() {
    picker.replaceChildren();
    const host = targetHost();
    if (!credentials.length) {
      picker.append(element("p", "No saved credentials. Use Manage credentials to add one.", "muted"));
      return;
    }
    if (!host) {
      picker.append(element("p", "Add an app URL to see matching credentials.", "muted"));
      return;
    }
    let matches = 0;
    for (const credential of credentials) {
      if (!matchesHost(credential, host)) continue;
      matches++;
      const label = element("label", "", "credential-choice");
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.value = credential.id;
      checkbox.checked = selected.has(credential.id);
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) selected.add(credential.id);
        else selected.delete(credential.id);
      });
      const description = element("span");
      description.append(element("strong", credential.name), element("small", credential.allowed_domains.join(", ")));
      label.append(checkbox, description);
      picker.append(label);
    }
    if (!matches) picker.append(element("p", "No saved credentials match this app URL. Manage credentials to add an allowed domain.", "muted"));
  }

  function renderList() {
    const list = get("credential-list");
    list.replaceChildren();
    for (const credential of credentials) {
      const item = element("li");
      const description = element("div", "", "credential-description");
      const name = element("strong", credential.name);
      if (credential.is_default) name.append(element("span", "Default", "credential-default-label"));
      description.append(name);
      const details = [];
      if (credential.login_hint) details.push(credential.login_hint);
      details.push(credential.allowed_domains.join(", "));
      description.append(element("p", details.join(" · "), "muted"));
      const actions = element("div", "", "credential-row-actions");
      const edit = element("button", "Edit", "text-button");
      edit.type = "button";
      edit.setAttribute("aria-label", `Edit ${credential.name}`);
      edit.addEventListener("click", () => editCredential(credential));
      const remove = element("button", "Delete", "text-button");
      remove.type = "button";
      remove.setAttribute("aria-label", `Delete ${credential.name}`);
      remove.addEventListener("click", () => deleteCredential(credential));
      actions.append(edit, remove);
      item.append(description, actions);
      list.append(item);
    }
  }

  async function loadCredentials() {
    get("credential-load-message").textContent = "";
    get("credential-retry").hidden = true;
    try {
      const response = await api("/api/credentials");
      credentials = response.credentials;
      if (!loaded) {
        for (const credential of credentials) {
          if (credential.is_default) selected.add(credential.id);
        }
      }
      loaded = true;
      renderPicker();
      renderList();
    } catch (error) {
      if (!credentials.length) picker.replaceChildren(element("p", "No credentials loaded.", "muted"));
      get("credential-load-message").textContent = `Could not load saved credentials. ${storageError(error)}`;
      get("credential-retry").hidden = false;
    }
  }

  function resetForm() {
    editingId = null;
    form.reset();
    for (const field of Object.keys(inputs)) {
      inputs[field].placeholder = placeholders[field];
      inputs[field].disabled = false;
    }
    get("credential-remove").hidden = true;
    get("credential-remove-options").replaceChildren();
    get("credential-editor-heading").textContent = "Add a credential";
    get("credential-save").textContent = "Save credential";
    get("credential-cancel").hidden = true;
    form.querySelector("details").open = false;
    fallback.disabled = true;
    showMessage("");
  }

  function editCredential(credential) {
    resetForm();
    editingId = credential.id;
    get("credential-name").value = credential.name;
    get("credential-domains").value = credential.allowed_domains.join(", ");
    get("credential-default").checked = credential.is_default;
    verification.value = credential.preferred_verification[0] || "";
    fallback.value = credential.preferred_verification[1] || "";
    fallback.disabled = !verification.value;
    for (const field of credential.available_fields) {
      const input = inputs[field];
      input.placeholder = "Leave blank to keep saved value";
      const label = element("label", "", "credential-check");
      const checkbox = element("input");
      checkbox.type = "checkbox";
      checkbox.addEventListener("change", () => { input.disabled = checkbox.checked; });
      label.append(checkbox, fieldLabels[field]);
      get("credential-remove-options").append(label);
      if (["email", "first_name", "last_name", "phone"].includes(field)) {
        form.querySelector("details").open = true;
      }
    }
    get("credential-remove").hidden = false;
    get("credential-editor-heading").textContent = `Edit ${credential.name}`;
    get("credential-save").textContent = "Save changes";
    get("credential-cancel").hidden = false;
    get("credential-name").focus();
  }

  async function deleteCredential(credential) {
    if (busy || !window.confirm(`Delete ${credential.name}? Runs using it will lose access to its saved values.`)) return;
    let deleted = false;
    setBusy(true);
    showMessage("");
    try {
      await api(`/api/credentials/${credential.id}`, { method: "DELETE" });
      if (editingId === credential.id) resetForm();
      selected.delete(credential.id);
      const remaining = [];
      for (const item of credentials) {
        if (item.id !== credential.id) remaining.push(item);
      }
      credentials = remaining;
      renderPicker();
      renderList();
      showMessage("Credential deleted.", true);
      deleted = true;
    } catch (error) {
      showMessage(storageError(error));
    } finally {
      setBusy(false);
    }
    if (deleted) get("credential-name").focus();
  }

  manage.addEventListener("click", () => {
    manager.hidden = false;
    manage.setAttribute("aria-expanded", "true");
    get("credential-name").focus();
  });
  get("credential-close").addEventListener("click", () => {
    manager.hidden = true;
    manage.setAttribute("aria-expanded", "false");
    resetForm();
    manage.focus();
  });
  get("credential-cancel").addEventListener("click", () => {
    resetForm();
    get("credential-name").focus();
  });
  verification.addEventListener("change", () => {
    fallback.disabled = !verification.value;
    if (!verification.value) fallback.value = "";
  });
  get("credential-retry").addEventListener("click", async () => {
    setBusy(true);
    await loadCredentials();
    setBusy(false);
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (busy || preview) return;
    showMessage("");
    const domains = [];
    for (const entry of get("credential-domains").value.split(",")) {
      if (entry.trim()) domains.push(entry.trim());
    }
    if (!domains.length || !get("credential-name").value.trim()) {
      showMessage("Add a name and at least one allowed domain.");
      return;
    }
    const methods = [];
    if (verification.value) {
      methods.push(verification.value);
      if (fallback.value && fallback.value !== verification.value) methods.push(fallback.value);
    }
    const body = {
      name: get("credential-name").value.trim(),
      allowed_domains: domains,
      is_default: get("credential-default").checked,
      preferred_verification: methods,
    };
    let hasValue = false;
    for (const field of Object.keys(inputs)) {
      const input = inputs[field];
      const value = field === "password" ? input.value : input.value.trim();
      if (input.disabled) body[field] = null;
      else if (value) {
        body[field] = value;
        hasValue = true;
      }
    }
    if (!editingId && !hasValue) {
      showMessage("Add at least one login, password, or contact detail.");
      return;
    }
    setBusy(true);
    try {
      const saved = await api(editingId ? `/api/credentials/${editingId}` : "/api/credentials", {
        method: editingId ? "PATCH" : "POST",
        body: JSON.stringify(body),
      });
      selected.add(saved.id);
      let replaced = false;
      for (let index = 0; index < credentials.length; index++) {
        if (credentials[index].id === saved.id) {
          credentials[index] = saved;
          replaced = true;
          break;
        }
      }
      if (!replaced) credentials.push(saved);
      renderPicker();
      renderList();
      resetForm();
      const status = matchesHost(saved, targetHost())
        ? "Credential saved and selected for this run."
        : "Credential saved. It will be available for runs on its allowed domains.";
      showMessage(status, true);
    } catch (error) {
      showMessage(storageError(error));
    } finally {
      setBusy(false);
    }
  });

  let ready = Promise.resolve();
  get("target-url").addEventListener("input", () => { if (!preview && loaded) renderPicker(); });
  if (preview) {
    picker.replaceChildren(element("p", "Saved credentials are available after you log in.", "muted"));
    setBusy(false);
  } else {
    setBusy(true);
    ready = loadCredentials().finally(() => setBusy(false));
  }
  return { ready, selectedIds, setBusy };
}
