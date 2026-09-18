/**
 * EGUP — Registration reference data.
 * Loads counties/churches/professions/skills/departments from Django
 * (apps.members.api.reference_data) instead of Supabase. Same exported
 * function name/shape as the original so membership-registration.js
 * needed no changes beyond its own import line (which already points
 * here — this file keeps the same path/name as the original).
 */
export async function loadReferenceData() {
  try {
    const res = await fetch("/api/reference-data");
    if (!res.ok) throw new Error("reference-data request failed");
    return await res.json();
  } catch (err) {
    console.warn("EGUP: failed to load reference data", err);
    return { counties: [], churches: [], professions: [], skills: [], departments: [] };
  }
}
