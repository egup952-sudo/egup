/**
 * EGUP — public-side HTML escaping.
 * Identical logic to admin/js/escape-html.js — duplicated rather than
 * shared across the admin/public boundary since the two are separate,
 * independently-deployable bundles. Used by the Page Builder renderer
 * and anywhere else public pages insert database text into innerHTML.
 */
export function escapeHtmlPublic(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
