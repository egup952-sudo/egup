import { renewMembership, requestRenewalOtp, verifyRenewalOtp, initiatePayment, pollPaymentStatus, getPaymentModes, submitManualPayment, IS_WORKER_CONFIGURED } from "./django-client.js";

function $(sel) { return document.querySelector(sel); }

let currentPaymentId = null;
let currentAccessToken = null;
let paymentModes = null;
let chosenMethod = null; // "AUTOMATIC" | "MANUAL"
let pendingLookup = null; // { member_number, phone } — kept between OTP request and verify
let renewalAuthToken = null; // issued only after OTP verification; required by /api/renew

function setLookupStatus(text, tone) {
  const el = $("[data-renewal-lookup-status]");
  el.textContent = text;
  el.className = tone ? `form-status is-visible form-status--${tone}` : "form-status";
}

function setOtpStatus(text, tone) {
  const el = $("[data-renewal-otp-status]");
  if (!el) return;
  el.textContent = text;
  el.className = tone ? `form-status is-visible form-status--${tone}` : "form-status";
}

function setPaymentStatus(text, tone = "info") {
  const el = $("[data-renewal-payment-status]");
  el.textContent = text;
  el.className = `payment-status payment-status--${tone}`;
}

async function ensurePaymentModes() {
  if (paymentModes) return paymentModes;
  const result = await getPaymentModes();
  paymentModes = result.ok ? result.data : { automatic_available: false, manual_available: true, manual: {} };
  return paymentModes;
}

async function handleRequestOtp(e) {
  e.preventDefault();
  const form = e.target;
  const memberNumber = form.member_number.value.trim();
  const phone = form.phone.value.trim();

  if (!memberNumber && !phone) {
    setLookupStatus("Enter your member number or phone number.", "error");
    return;
  }

  const modes = await ensurePaymentModes();
  if (!modes.automatic_available && !modes.manual_available) {
    setLookupStatus("Payment isn't available right now. Please contact EGUP directly.", "error");
    return;
  }

  const btn = form.querySelector("button[type='submit']");
  btn.disabled = true;
  btn.textContent = "Sending code\u2026";

  pendingLookup = { member_number: memberNumber || undefined, phone: phone || undefined };
  const result = await requestRenewalOtp(pendingLookup);

  btn.disabled = false;
  btn.textContent = "Find my membership";

  if (!result.ok) {
    setLookupStatus(result.error, "error");
    return;
  }

  // Deliberately generic either way (see api.renewal_request_otp) — we
  // always move to the "enter the code" step regardless of whether a
  // match was actually found, so the response itself never reveals
  // whether that membership number/phone exists.
  setLookupStatus("", null);
  $("[data-renewal-lookup-panel]").hidden = true;
  const otpPanel = $("[data-renewal-otp-panel]");
  if (otpPanel) {
    otpPanel.hidden = false;
    setOtpStatus("We've sent a verification code to the phone number on file, if that membership exists.", "info");
  }
}

async function handleVerifyOtp(e) {
  e.preventDefault();
  const form = e.target;
  const code = form.code.value.trim();
  if (!code) { setOtpStatus("Enter the code you received.", "error"); return; }

  const btn = form.querySelector("button[type='submit']");
  btn.disabled = true;
  btn.textContent = "Verifying\u2026";

  const result = await verifyRenewalOtp({ ...pendingLookup, code });

  btn.disabled = false;
  btn.textContent = "Verify code";

  if (!result.ok) {
    setOtpStatus(result.error, "error");
    return;
  }

  renewalAuthToken = result.data.renewal_auth_token;
  $("[data-renewal-otp-panel]").hidden = true;
  await proceedToPaymentChoice();
}

async function proceedToPaymentChoice() {
  const modes = await ensurePaymentModes();
  // If both are available and no choice has been made yet, ask first —
  // same intelligent mode selection as registration (spec section 24).
  if (modes.automatic_available && modes.manual_available && !chosenMethod) {
    const choiceEl = $("[data-renewal-method-choice]");
    if (choiceEl) { choiceEl.hidden = false; return; } // wait for the user to pick
  }
  if (!chosenMethod) {
    chosenMethod = modes.automatic_available ? "AUTOMATIC" : "MANUAL";
  }
  await submitRenewal();
}

async function submitRenewal() {
  setLookupStatus("Confirming\u2026", null);
  const result = await renewMembership({
    renewal_auth_token: renewalAuthToken, payment_method: chosenMethod,
  });

  if (!result.ok) {
    setOtpStatus(result.error, "error");
    // Token is single-use and now spent (or expired) — the applicant
    // needs a fresh code rather than retrying blindly.
    $("[data-renewal-otp-panel]").hidden = false;
    return;
  }

  currentPaymentId = result.data.payment_id;
  currentAccessToken = result.data.access_token;
  $("[data-renewal-name]").textContent = result.data.member.name;
  $("[data-renewal-number]").textContent = result.data.member.member_number || "N/A";
  $("[data-renewal-current-expiry]").textContent = result.data.member.current_expiry || "N/A";
  $("[data-renewal-amount]").textContent = `KES ${result.data.amount}`;

  $("[data-renewal-confirm-panel]").hidden = false;

  if (chosenMethod === "MANUAL") {
    // Payment already exists (provider=MANUAL) — go straight to
    // instructions instead of the "Renew & Pay" confirm-then-STK step.
    $("[data-renewal-confirm-panel]").hidden = true;
    renderManualInstructions(result.data.application_number);
  }
}

async function handlePay() {
  if (!IS_WORKER_CONFIGURED) {
    setPaymentStatus("Online payment isn't connected on this preview site yet.", "error");
    return;
  }

  $("[data-renewal-confirm-panel]").hidden = true;
  $("[data-renewal-payment-panel]").hidden = false;

  setPaymentStatus("Sending M-Pesa payment request\u2026", "info");
  const initResult = await initiatePayment(currentPaymentId);
  if (!initResult.ok) {
    setPaymentStatus(initResult.error, "error");
    return;
  }

  setPaymentStatus("Check your phone and enter your M-Pesa PIN to complete the renewal.", "info");
  $("[data-renewal-spinner]").hidden = false;

  const result = await pollPaymentStatus(currentPaymentId, currentAccessToken, {
    onTick: (data) => {
      if (data.status === "PROCESSING") setPaymentStatus("Waiting for payment confirmation\u2026", "info");
    },
  });

  $("[data-renewal-spinner]").hidden = true;

  if (!result.ok) {
    setPaymentStatus(result.error, "error");
    return;
  }

  if (result.data.status === "PAID") {
    $("[data-renewal-payment-panel]").hidden = true;
    $("[data-renewal-done-panel]").hidden = false;
    $("[data-renewal-new-expiry]").textContent = result.data.expiry_date || "N/A";
  } else if (result.data.status === "TIMEOUT") {
    setPaymentStatus("This is taking longer than expected. If you completed the M-Pesa prompt, your renewal will be confirmed shortly.", "error");
  } else {
    setPaymentStatus(`Payment ${result.data.status.toLowerCase()}. Please try again.`, "error");
  }
}

function renderManualInstructions(applicationNumber) {
  const panel = $("[data-renewal-manual-panel]");
  if (!panel) return;
  panel.hidden = false;

  const manual = (paymentModes && paymentModes.manual) || {};
  $("[data-renewal-manual-application-number]").textContent = applicationNumber || "N/A";
  if (manual.paybill) { $("[data-renewal-manual-paybill-row]").hidden = false; $("[data-renewal-manual-paybill]").textContent = manual.paybill; }
  if (manual.till) { $("[data-renewal-manual-till-row]").hidden = false; $("[data-renewal-manual-till]").textContent = manual.till; }
  $("[data-renewal-manual-account-note]").textContent = manual.account_note || `Use ${applicationNumber || "your application number"} as the account/reference.`;

  const form = $("[data-renewal-manual-form]");
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    const statusEl = $("[data-renewal-manual-submit-status]");
    statusEl.textContent = "Submitting payment for verification\u2026";
    statusEl.className = "payment-status payment-status--info";

    const fd = new FormData(form);
    fd.set("payment_id", currentPaymentId);
    fd.set("access_token", currentAccessToken || "");
    const result = await submitManualPayment(fd);
    submitBtn.disabled = false;

    if (!result.ok) {
      statusEl.textContent = result.error;
      statusEl.className = "payment-status payment-status--error";
      return;
    }
    panel.hidden = true;
    $("[data-renewal-pending-panel]").hidden = false;
    $("[data-renewal-pending-application-number]").textContent = result.data.application_number || "N/A";
  };
}

function init() {
  const lookupForm = $("#renewal-lookup-form");
  if (!lookupForm) return;
  lookupForm.addEventListener("submit", handleRequestOtp);
  $("[data-renewal-otp-form]")?.addEventListener("submit", handleVerifyOtp);
  $("[data-renewal-pay]")?.addEventListener("click", handlePay);
  $("[data-renewal-cancel]")?.addEventListener("click", () => {
    $("[data-renewal-confirm-panel]").hidden = true;
    $("[data-renewal-lookup-panel]").hidden = false;
  });
  $("[data-renewal-otp-back]")?.addEventListener("click", () => {
    $("[data-renewal-otp-panel]").hidden = true;
    $("[data-renewal-lookup-panel]").hidden = false;
  });

  $("[data-renewal-choose-automatic]")?.addEventListener("click", () => {
    chosenMethod = "AUTOMATIC";
    $("[data-renewal-method-choice]").hidden = true;
    submitRenewal();
  });
  $("[data-renewal-choose-manual]")?.addEventListener("click", () => {
    chosenMethod = "MANUAL";
    $("[data-renewal-method-choice]").hidden = true;
    submitRenewal();
  });
}

document.addEventListener("DOMContentLoaded", init);
