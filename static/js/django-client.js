/**
 * EGUP — Django API client.
 * Drop-in replacement for the original worker-client.js: same exported
 * function names and same {ok, data|error} return shape, so
 * membership-registration.js and renewal.js needed only their import
 * line changed, not their logic. Talks to Django's own /api/ endpoints
 * (apps.members.api) instead of the retired Cloudflare Worker.
 */
function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : null;
}

export async function callApi(path, options = {}) {
  try {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (options.method && options.method !== "GET") {
      headers["X-CSRFToken"] = getCookie("csrftoken");
    }
    const res = await fetch(path, { ...options, headers });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      return { ok: false, error: body.error || "Something went wrong. Please try again.", fieldErrors: body.fieldErrors };
    }
    return { ok: true, data: body };
  } catch (err) {
    console.warn("EGUP API call failed:", err);
    return { ok: false, error: "We couldn't reach the server. Please check your connection and try again." };
  }
}

export function registerMember(payload) {
  return callApi("/api/register", { method: "POST", body: JSON.stringify(payload) });
}

export function getPaymentModes() {
  return callApi("/api/payment-modes");
}

export function submitManualPayment(formData) {
  // formData is a FormData instance (screenshot upload support) — no
  // Content-Type header here, the browser sets the multipart boundary itself.
  return (async () => {
    try {
      const res = await fetch("/api/payment/manual-submit", {
        method: "POST",
        headers: { "X-CSRFToken": getCookie("csrftoken") },
        body: formData,
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) return { ok: false, error: body.error || "We couldn't submit that payment." };
      return { ok: true, data: body };
    } catch (err) {
      return { ok: false, error: "We couldn't reach the server. Please check your connection and try again." };
    }
  })();
}

export function initiatePayment(paymentId) {
  // Registration already initiates payment server-side in one step (see
  // apps.members.api.register) — this exists only so
  // membership-registration.js's call shape still works unmodified; the
  // paymentId here IS already a live, PROCESSING payment.
  return Promise.resolve({ ok: true, data: { payment_id: paymentId } });
}

export function verifyPayment(paymentId, accessToken) {
  return callApi(`/api/payment/verify?payment_id=${encodeURIComponent(paymentId)}&access_token=${encodeURIComponent(accessToken || "")}`);
}

export function renewMembership(payload) {
  return callApi("/api/renew", { method: "POST", body: JSON.stringify(payload) });
}

export function requestRenewalOtp(payload) {
  return callApi("/api/renewal/request-otp", { method: "POST", body: JSON.stringify(payload) });
}

export function verifyRenewalOtp(payload) {
  return callApi("/api/renewal/verify-otp", { method: "POST", body: JSON.stringify(payload) });
}

export async function pollPaymentStatus(paymentId, accessToken, { intervalMs = 4000, timeoutMs = 120000, onTick } = {}) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    // Spec section 41: stop polling if the user has navigated away from
    // this tab (backgrounded) rather than hammering the backend for a
    // page nobody is looking at — resumes automatically when they
    // return, still bounded by the same overall timeout.
    if (document.visibilityState === "hidden") {
      await new Promise((resolve) => {
        const onVisible = () => {
          if (document.visibilityState === "visible") {
            document.removeEventListener("visibilitychange", onVisible);
            resolve();
          }
        };
        document.addEventListener("visibilitychange", onVisible);
      });
      continue;
    }
    const result = await verifyPayment(paymentId, accessToken);
    if (!result.ok) return result;
    if (onTick) onTick(result.data);
    if (!["PENDING", "PROCESSING"].includes(result.data.status)) {
      return result;
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  return { ok: true, data: { status: "TIMEOUT" } };
}

export const IS_WORKER_CONFIGURED = true; // Django is always "configured" — no external Worker secret to check
