/**
 * EGUP — Registration form validation (frontend copy).
 * Mirrors worker/src/lib/business.js's rules for a responsive UX — but
 * this copy is NOT the security boundary. The Worker re-validates
 * everything server-side before writing anything to the database; a
 * user with JavaScript disabled or a tampered request cannot bypass
 * anything that actually matters by skipping this file.
 */

const KENYA_PHONE_RE = /^(?:\+254|254|0)7\d{8}$/;
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function normalizeKenyanPhone(raw) {
  if (typeof raw !== "string") return null;
  const digits = raw.trim().replace(/[\s-]/g, "");
  if (!KENYA_PHONE_RE.test(digits)) return null;
  if (digits.startsWith("+254")) return digits.slice(1);
  if (digits.startsWith("254")) return digits;
  if (digits.startsWith("0")) return "254" + digits.slice(1);
  return null;
}

export function isValidEmail(value) {
  return !value || (typeof value === "string" && EMAIL_RE.test(value.trim()));
}

export function validateStep1Personal(data) {
  const errors = {};
  if (!data.surname?.trim()) errors.surname = "Surname is required.";
  if (!data.other_names?.trim()) errors.other_names = "Other names are required.";
  if (!data.phone || !normalizeKenyanPhone(data.phone)) errors.phone = "Enter a valid Kenyan phone number (e.g. 0712345678).";
  if (data.email && !isValidEmail(data.email)) errors.email = "Enter a valid email address.";
  if (!data.gender) errors.gender = "Please select a gender.";
  if (!data.county_id) errors.county_id = "Please select a county.";
  return { valid: Object.keys(errors).length === 0, errors };
}

export function validateStep2Profession() {
  // Profession/skills/departments are all optional at the field level —
  // nothing to hard-require here, but kept as its own step function for
  // symmetry and in case requirements tighten later.
  return { valid: true, errors: {} };
}

export function validateStep3Referee(data) {
  const errors = {};
  if (data.referee_phone && !normalizeKenyanPhone(data.referee_phone)) {
    errors.referee_phone = "Enter a valid Kenyan phone number for the referee.";
  }
  return { valid: Object.keys(errors).length === 0, errors };
}

export function validateAllSteps(data) {
  const s1 = validateStep1Personal(data);
  const s3 = validateStep3Referee(data);
  return { valid: s1.valid && s3.valid, errors: { ...s1.errors, ...s3.errors } };
}
