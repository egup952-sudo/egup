function getCookie(name) {
  const match = document.cookie.match(new RegExp(`(^| )${name}=([^;]+)`));
  return match ? decodeURIComponent(match[2]) : null;
}

function init() {
  const form = document.getElementById("contact-form");
  if (!form) return;
  const statusEl = form.querySelector(".form-status");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button[type='submit']");
    btn.disabled = true;
    const originalText = btn.textContent;
    btn.textContent = "Sending\u2026";

    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
        body: JSON.stringify(payload),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.error || "Something went wrong.");
      statusEl.textContent = "Thank you. Your message has been sent. We'll get back to you soon.";
      statusEl.className = "form-status is-visible form-status--success";
      form.reset();
    } catch (err) {
      statusEl.textContent = err.message || "We couldn't send your message. Please try again.";
      statusEl.className = "form-status is-visible form-status--error";
    } finally {
      btn.disabled = false;
      btn.textContent = originalText;
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
