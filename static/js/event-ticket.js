import { callApi, submitManualPayment, pollPaymentStatus } from "./django-client.js";
import { normalizeKenyanPhone } from "./registration-validation.js";

function $(sel, root = document) { return root.querySelector(sel); }

(function () {
  const section = document.querySelector("[data-ticket-section]");
  if (!section) return;
  const slug = section.dataset.eventSlug;

  const state = { modes: null, formData: null, paymentId: null, accessToken: null };

  function setStatus(text, tone = "info") {
    const el = $("[data-ticket-status-message]", section);
    if (!el) return;
    el.textContent = text;
    el.className = `payment-status payment-status--${tone}`;
  }

  function hideAll() {
    ["[data-ticket-payment-choice]", "[data-ticket-automatic-phone-panel]", "[data-ticket-manual-panel]", "[data-ticket-confirmation]"].forEach((sel) => {
      const el = $(sel, section);
      if (el) el.hidden = true;
    });
  }

  function showConfirmation(referenceCode, title) {
    hideAll();
    $("[data-ticket-form]", section).hidden = true;
    $("[data-ticket-confirmation]", section).hidden = false;
    $("[data-ticket-confirmation-title]", section).textContent = title;
    $("[data-ticket-reference]", section).textContent = referenceCode;
    setStatus("", "info");
  }

  async function loadModes() {
    const result = await callApi(`/api/events/${slug}/ticket-modes`);
    if (!result.ok) return null;
    state.modes = result.data;
    section.querySelectorAll("[data-ticket-amount]").forEach((el) => (el.textContent = result.data.price_kes));
    return result.data;
  }

  function renderPaymentChoice() {
    hideAll();
    const choice = $("[data-ticket-payment-choice]", section);
    choice.hidden = false;
    const { automatic_available, manual_available } = state.modes;

    const autoCard = $("[data-ticket-automatic-card]", section);
    const manualCard = $("[data-ticket-manual-card]", section);
    autoCard.classList.toggle("is-disabled", !automatic_available);
    $("[data-ticket-automatic-unavailable]", section).hidden = !!automatic_available;
    $("[data-ticket-choose-automatic]", section).disabled = !automatic_available;
    manualCard.classList.toggle("is-disabled", !manual_available);
    $("[data-ticket-manual-unavailable]", section).hidden = !!manual_available;
    $("[data-ticket-choose-manual]", section).disabled = !manual_available;

    $("[data-ticket-choose-automatic]", section).onclick = () => {
      if (!automatic_available) return;
      choice.hidden = true;
      const phonePanel = $("[data-ticket-automatic-phone-panel]", section);
      phonePanel.hidden = false;
      $("#tk-auto-phone", section).value = state.formData.phone;
    };
    $("[data-ticket-choose-manual]", section).onclick = () => {
      if (!manual_available) return;
      choice.hidden = true;
      startManualBooking();
    };
  }

  async function bookTicket(paymentMethod) {
    setStatus("Booking your ticket\u2026", "info");
    const result = await callApi(`/api/events/${slug}/book-ticket`, {
      method: "POST",
      body: JSON.stringify({ ...state.formData, payment_method: paymentMethod }),
    });
    if (!result.ok) {
      setStatus(result.error, "error");
      return null;
    }
    return result.data;
  }

  async function startFreeBooking() {
    const data = await bookTicket(null);
    if (!data) return;
    showConfirmation(data.ticket_reference, "Your ticket is confirmed!");
  }

  async function startAutomaticBooking() {
    setStatus("Sending your M-Pesa payment request\u2026", "info");
    const data = await bookTicket("AUTOMATIC");
    if (!data) return;
    state.paymentId = data.payment_id;
    state.accessToken = data.access_token;
    setStatus("Check your phone and enter your M-Pesa PIN to complete the payment.", "info");
    const result = await pollPaymentStatus(state.paymentId, state.accessToken, {
      onTick: (d) => { if (d.status === "PROCESSING") setStatus("Waiting for M-Pesa confirmation\u2026", "info"); },
    });
    if (!result.ok) { setStatus(result.error, "error"); return; }
    if (result.data.status === "PAID") {
      showConfirmation(data.ticket_reference, "Payment confirmed, your ticket is booked!");
    } else {
      setStatus("We could not confirm the payment. Please try again.", "error");
      hideAll();
    }
  }

  async function startManualBooking() {
    const data = await bookTicket("MANUAL");
    if (!data) return;
    state.paymentId = data.payment_id;
    state.accessToken = data.access_token;
    state.ticketReference = data.ticket_reference;
    const manual = state.modes.manual || {};
    $("[data-ticket-manual-paybill]", section).textContent = manual.paybill || "";
    $("[data-ticket-manual-account]", section).textContent = manual.account_note || data.ticket_reference;
    $("[data-ticket-manual-amount]", section).textContent = data.amount;
    $("[data-ticket-manual-panel]", section).hidden = false;
    setStatus("", "info");
  }

  $("[data-ticket-form]", section)?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const phone = normalizeKenyanPhone(form.phone.value);
    if (!phone) { setStatus("Enter a valid Kenyan phone number.", "error"); return; }
    state.formData = {
      full_name: form.full_name.value.trim(), email: form.email.value.trim(),
      phone, quantity: parseInt(form.quantity.value, 10) || 1,
    };

    const modes = state.modes || (await loadModes());
    if (!modes) { setStatus("Couldn't check ticket availability. Please try again.", "error"); return; }
    if (modes.is_sold_out) { setStatus("Sorry, this event just sold out.", "error"); return; }

    form.hidden = true;
    if (modes.is_free) {
      await startFreeBooking();
    } else {
      renderPaymentChoice();
    }
  });

  $("[data-ticket-automatic-phone-form]", section)?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const phone = normalizeKenyanPhone($("#tk-auto-phone", section).value);
    if (!phone) return;
    state.formData.phone = phone;
    $("[data-ticket-automatic-phone-panel]", section).hidden = true;
    await startAutomaticBooking();
  });
  $("[data-ticket-automatic-back]", section)?.addEventListener("click", () => {
    $("[data-ticket-automatic-phone-panel]", section).hidden = true;
    renderPaymentChoice();
  });
  $("[data-ticket-manual-back]", section)?.addEventListener("click", () => {
    $("[data-ticket-manual-panel]", section).hidden = true;
    renderPaymentChoice();
  });

  $("[data-ticket-manual-form]", section)?.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const form = ev.target;
    const submitBtn = form.querySelector("button[type=submit]");
    submitBtn.disabled = true;
    setStatus("Submitting for verification\u2026", "info");
    const fd = new FormData(form);
    fd.set("payment_id", state.paymentId);
    fd.set("access_token", state.accessToken || "");
    const result = await submitManualPayment(fd);
    submitBtn.disabled = false;
    if (!result.ok) { setStatus(result.error, "error"); return; }
    showConfirmation(state.ticketReference, "Submitted! Your ticket will be confirmed once payment is verified.");
  });

  loadModes();
})();
