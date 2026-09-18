import { loadReferenceData } from "./reference-data.js";
import { validateStep1Personal, validateStep3Referee, normalizeKenyanPhone } from "./registration-validation.js";
import { registerMember, initiatePayment, pollPaymentStatus, getPaymentModes, submitManualPayment, IS_WORKER_CONFIGURED } from "./django-client.js";
import { escapeHtmlPublic as e } from "./escape-html-public.js";

const state = {
  step: 1,
  data: {
    surname: "", other_names: "", phone: "", email: "", gender: "", county_id: "",
    location: "", home_town: "", religion: "", church_id: "",
    profession_id: "", experience: "", gift: "", skill_ids: [], department_ids: [],
    referee_name: "", referee_phone: "", referee_location: "",
  },
  refData: null,
  paymentModes: null,
  paymentId: null,
  memberId: null,
  accessToken: null,
  chosenMethod: null, // "AUTOMATIC" | "MANUAL"
};

const TOTAL_STEPS = 6;

function $(sel, root = document) { return root.querySelector(sel); }
function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

function goToStep(step) {
  state.step = step;
  $$(".reg-step").forEach((el) => (el.hidden = Number(el.dataset.step) !== step));
  $$(".reg-progress__item").forEach((el) => {
    const n = Number(el.dataset.step);
    el.classList.toggle("is-active", n === step);
    el.classList.toggle("is-done", n < step);
  });
  window.scrollTo({
    top: $(".reg-wizard").offsetTop - 100,
    behavior: window.egupPrefersReducedMotion && window.egupPrefersReducedMotion() ? "auto" : "smooth",
  });

  // Move focus to the new step's heading so keyboard/screen-reader users
  // land on the new content instead of staying on a now-hidden button —
  // a real gap in most multi-step wizards, not just a nice-to-have.
  const activeStep = document.querySelector(`.reg-step[data-step="${step}"]`);
  const heading = activeStep?.querySelector("h2");
  if (heading) {
    heading.setAttribute("tabindex", "-1");
    heading.focus({ preventScroll: true });
  }
}

function showFieldErrors(errors) {
  // Clear previous error state — both the visible message and the ARIA
  // wiring, so a field that's since become valid doesn't stay marked
  // invalid for screen-reader users.
  $$(".form-field").forEach((f) => {
    f.querySelector(".field-error")?.remove();
    const field = f.querySelector("input,select,textarea");
    if (field) {
      field.removeAttribute("aria-invalid");
      field.removeAttribute("aria-describedby");
    }
  });

  let firstInvalidField = null;
  Object.entries(errors).forEach(([field, message]) => {
    const input = document.querySelector(`[name="${field}"]`);
    const container = input?.closest(".form-field");
    if (!container || !input) return;

    const errorId = `${input.id || field}-error`;
    const span = document.createElement("p");
    span.className = "field-error";
    span.id = errorId;
    span.setAttribute("role", "alert");
    span.textContent = message;
    container.appendChild(span);

    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", errorId);

    if (!firstInvalidField) firstInvalidField = input;
  });

  // Move focus to the first invalid field so keyboard/screen-reader users
  // land directly on what needs fixing, instead of having to hunt for it
  // — the sighted-user equivalent is the red text already being visible.
  if (firstInvalidField) firstInvalidField.focus();
}

function readFormValues(form) {
  const fd = new FormData(form);
  const values = {};
  for (const [key, value] of fd.entries()) {
    if (key.endsWith("[]")) {
      const cleanKey = key.slice(0, -2);
      values[cleanKey] = values[cleanKey] || [];
      values[cleanKey].push(value);
    } else {
      values[key] = value;
    }
  }
  return values;
}

function populateReferenceSelects() {
  const { counties, churches, professions, skills, departments } = state.refData;
  fillSelect($("[name='county_id']"), counties, "Select your county");
  fillSelect($("[name='church_id']"), churches, "Select your church (optional)");
  fillSelect($("[name='profession_id']"), professions, "Select your profession (optional)");
  fillChecklist($("[data-skills-list]"), skills, "skill_ids");
  fillChecklist($("[data-departments-list]"), departments, "department_ids");
}

function fillSelect(select, items, placeholder) {
  if (!select) return;
  select.innerHTML = `<option value="">${e(placeholder)}</option>` + items.map((i) => `<option value="${e(i.id)}">${e(i.name)}</option>`).join("");
}

function fillChecklist(container, items, fieldName) {
  if (!container) return;
  container.innerHTML = items
    .map(
      (item, i) => `
      <label class="checklist-item">
        <input type="checkbox" name="${e(fieldName)}[]" value="${e(item.id)}" id="${e(fieldName)}-${i}">
        <span>${e(item.name)}</span>
      </label>`
    )
    .join("");
}

/* ---------------- Step 1: Personal ---------------- */
function initStep1() {
  $("[data-step-1-next]").addEventListener("click", () => {
    const values = readFormValues($("#reg-step-1"));
    Object.assign(state.data, values);
    const { valid, errors } = validateStep1Personal(state.data);
    if (!valid) { showFieldErrors(errors); return; }
    showFieldErrors({});
    goToStep(2);
  });
}

/* ---------------- Step 2: Profession/Skills/Departments ---------------- */
function initStep2() {
  $("[data-step-2-back]").addEventListener("click", () => goToStep(1));
  $("[data-step-2-next]").addEventListener("click", () => {
    const values = readFormValues($("#reg-step-2"));
    Object.assign(state.data, values);
    state.data.skill_ids = values.skill_ids || [];
    state.data.department_ids = values.department_ids || [];
    goToStep(3);
  });
}

/* ---------------- Step 3: Referee ---------------- */
function initStep3() {
  $("[data-step-3-back]").addEventListener("click", () => goToStep(2));
  $("[data-step-3-next]").addEventListener("click", () => {
    const values = readFormValues($("#reg-step-3"));
    Object.assign(state.data, values);
    const { valid, errors } = validateStep3Referee(state.data);
    if (!valid) { showFieldErrors(errors); return; }
    showFieldErrors({});
    renderReview();
    goToStep(4);
  });
}

/* ---------------- Step 4: Review ---------------- */
function findName(list, id) { return list.find((i) => i.id === id)?.name || "N/A"; }

function renderReview() {
  const d = state.data;
  const r = state.refData;
  $("[data-review-output]").innerHTML = `
    <dl class="review-list">
      <dt>Name</dt><dd>${e(d.other_names)} ${e(d.surname)}</dd>
      <dt>Phone</dt><dd>${e(d.phone)}</dd>
      <dt>Email</dt><dd>${e(d.email) || "N/A"}</dd>
      <dt>Gender</dt><dd>${d.gender === "MALE" ? "Male" : d.gender === "FEMALE" ? "Female" : "N/A"}</dd>
      <dt>County</dt><dd>${e(findName(r.counties, d.county_id))}</dd>
      <dt>Location</dt><dd>${e(d.location) || "N/A"}</dd>
      <dt>Home town</dt><dd>${e(d.home_town) || "N/A"}</dd>
      <dt>Religion</dt><dd>${e(d.religion) || "N/A"}</dd>
      <dt>Church</dt><dd>${d.church_id ? e(findName(r.churches, d.church_id)) : "N/A"}</dd>
      <dt>Profession</dt><dd>${d.profession_id ? e(findName(r.professions, d.profession_id)) : "N/A"}</dd>
      <dt>Experience</dt><dd>${e(d.experience) || "N/A"}</dd>
      <dt>Gift</dt><dd>${e(d.gift) || "N/A"}</dd>
      <dt>Skills</dt><dd>${d.skill_ids.length ? e(d.skill_ids.map((id) => findName(r.skills, id)).join(", ")) : "N/A"}</dd>
      <dt>Departments</dt><dd>${d.department_ids.length ? e(d.department_ids.map((id) => findName(r.departments, id)).join(", ")) : "N/A"}</dd>
      <dt>Referee</dt><dd>${e(d.referee_name) || "N/A"}</dd>
      <dt>Referee phone</dt><dd>${e(d.referee_phone) || "N/A"}</dd>
      <dt>Referee location</dt><dd>${e(d.referee_location) || "N/A"}</dd>
    </dl>`;
}

function initStep4() {
  $("[data-step-4-back]").addEventListener("click", () => goToStep(3));
  $("[data-step-4-next]").addEventListener("click", () => {
    goToStep(5);
    startPayment();
  });
}

/* ---------------- Step 5: Payment ---------------- */
function setPaymentStatusMessage(text, tone = "info") {
  const el = $("[data-payment-status-message]");
  el.textContent = text;
  el.className = `payment-status payment-status--${tone}`;
}

function applyFeeAmount() {
  const amount = state.paymentModes && state.paymentModes.registration_fee_kes;
  if (amount == null) return;
  $$("[data-fee-amount]").forEach((el) => (el.textContent = amount));
}

async function startPayment() {
  setPaymentStatusMessage("Checking available payment methods\u2026", "info");
  const modesResult = await getPaymentModes();
  state.paymentModes = modesResult.ok ? modesResult.data : { automatic_available: false, manual_available: true, manual: {} };
  applyFeeAmount();

  const { automatic_available, manual_available } = state.paymentModes;

  if (!automatic_available && !manual_available) {
    setPaymentStatusMessage("Payment isn't available right now. Please contact EGUP directly to complete your registration.", "error");
    return;
  }

  renderPaymentMethodChoice();
}

function renderPaymentMethodChoice() {
  const container = $("[data-payment-method-choice]");
  if (!container) {
    // Markup wasn't updated in this environment — fall back to automatic only.
    state.chosenMethod = "AUTOMATIC";
    startAutomaticPayment();
    return;
  }
  const { automatic_available, manual_available } = state.paymentModes;

  // Both cards are always shown — the applicant must explicitly click
  // one. An unavailable method is shown disabled with a label, never
  // silently skipped or auto-selected on their behalf.
  const autoCard = $("[data-automatic-card]");
  const manualCard = $("[data-manual-card]");
  const autoBtn = $("[data-choose-automatic]");
  const manualBtn = $("[data-choose-manual]");

  autoCard.classList.toggle("is-disabled", !automatic_available);
  $("[data-automatic-unavailable-label]").hidden = !!automatic_available;
  autoBtn.disabled = !automatic_available;

  manualCard.classList.toggle("is-disabled", !manual_available);
  $("[data-manual-unavailable-label]").hidden = !!manual_available;
  manualBtn.disabled = !manual_available;

  container.hidden = false;
  setPaymentStatusMessage("", "info");

  autoBtn.onclick = () => {
    container.hidden = true;
    state.chosenMethod = "AUTOMATIC";
    renderAutomaticPhoneConfirm();
  };
  manualBtn.onclick = () => {
    container.hidden = true;
    state.chosenMethod = "MANUAL";
    startManualPayment();
  };
}

/* ---------------- Automatic path: confirm phone, then pay ---------------- */
function renderAutomaticPhoneConfirm() {
  const panel = $("[data-automatic-phone-panel]");
  if (!panel) {
    // Markup not present in this build — go straight to payment with
    // the phone already collected in Step 1.
    startAutomaticPayment();
    return;
  }
  panel.hidden = false;
  const input = $("#mp-auto-phone");
  input.value = state.data.phone || "";
  const statusEl = $("[data-automatic-phone-status]");
  statusEl.textContent = "";

  $("[data-automatic-phone-back]").onclick = () => {
    panel.hidden = true;
    renderPaymentMethodChoice();
  };

  const form = $("[data-automatic-phone-form]");
  form.onsubmit = (ev) => {
    ev.preventDefault();
    const normalized = normalizeKenyanPhone(input.value);
    if (!normalized) {
      statusEl.textContent = "Enter a valid Kenyan phone number (e.g. 0712345678).";
      statusEl.className = "payment-status payment-status--error";
      return;
    }
    state.data.phone = normalized;
    panel.hidden = true;
    startAutomaticPayment();
  };
}

async function startAutomaticPayment() {
  if (!IS_WORKER_CONFIGURED) {
    setPaymentStatusMessage(
      "Online payment isn't connected on this preview site yet. In production, this step sends an M-Pesa prompt to your phone automatically.",
      "error"
    );
    return;
  }

  setPaymentStatusMessage("Sending your M-Pesa payment request\u2026", "info");
  const regResult = await registerMember({ ...state.data, payment_method: "AUTOMATIC" });
  if (!regResult.ok) {
    setPaymentStatusMessage(regResult.error, "error");
    return;
  }
  state.memberId = regResult.data.member_id;
  state.paymentId = regResult.data.payment_id;
  state.accessToken = regResult.data.access_token;

  await initiatePayment(state.paymentId);

  setPaymentStatusMessage("Check your phone and enter your M-Pesa PIN to complete the payment.", "info");
  $("[data-payment-spinner]").hidden = false;

  const result = await pollPaymentStatus(state.paymentId, state.accessToken, {
    onTick: (data) => {
      if (data.status === "PROCESSING") setPaymentStatusMessage("Waiting for M-Pesa confirmation\u2026", "info");
    },
  });

  $("[data-payment-spinner]").hidden = true;

  if (!result.ok) {
    setPaymentStatusMessage(result.error, "error");
    return;
  }

  if (result.data.status === "PAID") {
    setPaymentStatusMessage("Payment confirmed.", "success");
    renderConfirmation(result.data);
    goToStep(6);
  } else if (result.data.status === "TIMEOUT") {
    setPaymentStatusMessage("This is taking longer than expected. If you completed the M-Pesa prompt, your registration will be confirmed shortly. You can check back, or contact EGUP with your phone number.", "error");
  } else {
    setPaymentStatusMessage("We could not confirm the payment. Please try again.", "error");
    $("[data-payment-retry]").hidden = false;
  }
}

/* ---------------- Manual payment path ---------------- */
async function startManualPayment() {
  setPaymentStatusMessage("Submitting registration\u2026", "info");
  const regResult = await registerMember({ ...state.data, payment_method: "MANUAL" });
  if (!regResult.ok) {
    setPaymentStatusMessage(regResult.error, "error");
    return;
  }
  state.memberId = regResult.data.member_id;
  state.paymentId = regResult.data.payment_id;
  state.accessToken = regResult.data.access_token;
  renderManualInstructions(regResult.data.application_number);
}

function renderManualInstructions(applicationNumber) {
  setPaymentStatusMessage("", "info");
  const panel = $("[data-manual-payment-panel]");
  if (!panel) return; // markup not present in this build — nothing more we can do client-side
  panel.hidden = false;

  const manual = (state.paymentModes && state.paymentModes.manual) || {};
  const amount = state.paymentModes && state.paymentModes.registration_fee_kes;
  $("[data-manual-application-number]").textContent = applicationNumber || "N/A";
  if (manual.paybill) $("[data-manual-paybill]").closest(".manual-instructions__row").hidden = false, $("[data-manual-paybill]").textContent = manual.paybill;
  if (manual.till) $("[data-manual-till]").closest(".manual-instructions__row").hidden = false, $("[data-manual-till]").textContent = manual.till;
  $("[data-manual-account-note]").textContent = manual.account_note || `Use ${applicationNumber || "your application number"} as the account/reference.`;
  if (amount != null) $("[data-manual-amount]").textContent = amount;
  if (manual.instructions) $("[data-manual-extra-instructions]").textContent = manual.instructions;

  $("[data-manual-back]").onclick = () => {
    panel.hidden = true;
    renderPaymentMethodChoice();
  };

  const form = $("[data-manual-payment-form]");
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    const statusEl = $("[data-manual-submit-status]");
    statusEl.textContent = "Submitting payment for verification\u2026";
    statusEl.className = "payment-status payment-status--info";

    const fd = new FormData(form);
    fd.set("payment_id", state.paymentId);
    fd.set("access_token", state.accessToken || "");
    const result = await submitManualPayment(fd);
    submitBtn.disabled = false;

    if (!result.ok) {
      statusEl.textContent = result.error;
      statusEl.className = "payment-status payment-status--error";
      return;
    }
    panel.hidden = true;
    renderPendingVerification(result.data.application_number);
    goToStep(6);
  };
}

function renderPendingVerification(applicationNumber) {
  const confirmPanel = $("[data-confirm-pending-verification]");
  if (confirmPanel) {
    confirmPanel.hidden = false;
    $("[data-confirm-application-number]").textContent = applicationNumber || "N/A";
  }
  // Hide the "paid" version of the confirmation content, if present, so
  // the two states never both show at once.
  const paidContent = $("[data-confirm-paid-content]");
  if (paidContent) paidContent.hidden = true;
}

/* ---------------- Step 6: Confirmation ---------------- */
function renderConfirmation(data) {
  $("[data-confirm-member-number]").textContent = data.member_number || "N/A";
  $("[data-confirm-expiry]").textContent = data.expiry_date || "N/A";
  $("[data-confirm-date]").textContent = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

/* ---------------- Boot ---------------- */
async function init() {
  const wizard = $(".reg-wizard");
  if (!wizard) return;

  state.refData = await loadReferenceData();
  populateReferenceSelects();

  initStep1();
  initStep2();
  initStep3();
  initStep4();

  $("[data-payment-retry]")?.addEventListener("click", () => {
    $("[data-payment-retry]").hidden = true;
    startPayment();
  });

  $("[data-confirm-print]")?.addEventListener("click", () => window.print());

  goToStep(1);

  // Fetch the fee up front (not just when Step 5 loads) so Step 4's
  // "Register & Pay KES ..." button shows the real, admin-configured
  // amount rather than the placeholder from first paint.
  getPaymentModes().then((modesResult) => {
    if (modesResult.ok) {
      state.paymentModes = modesResult.data;
      applyFeeAmount();
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
