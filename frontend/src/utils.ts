/**
 * Shared formatting utilities.
 *
 * These helpers operate on values as received from the API — Decimal quantities
 * come over the wire as strings (e.g. "1.000000") and must be formatted for
 * display without converting to a JS floating-point number (which risks
 * introducing rounding artefacts or re-attaching fixed decimals).
 */

/**
 * Format a Decimal quantity string for human display by trimming trailing zeros
 * after the decimal point, and dropping a dangling decimal point if nothing
 * meaningful remains after it.
 *
 * Examples:
 *   "1.000000" → "1"
 *   "1.200000" → "1.2"
 *   "1.210000" → "1.21"
 *   "5"        → "5"
 *   "0.5"      → "0.5"
 *   5           → "5"    (number input also accepted)
 *   ""          → ""     (empty falls back to original)
 *   "bad"       → "bad"  (malformed falls back to original)
 *
 * @param value - The raw quantity value from the API (string or number).
 * @returns A human-readable string with trailing zeros stripped.
 */
export function formatQuantity(value: string | number): string {
  const str = String(value);

  // If there is no decimal point, nothing to strip — return as-is.
  if (!str.includes(".")) {
    return str;
  }

  // Strip trailing zeros after the decimal point, then a dangling dot.
  const trimmed = str.replace(/\.?0+$/, "");

  // Guard: if stripping produced an empty string or just a sign character,
  // fall back to the original to avoid confusing output.
  if (trimmed === "" || trimmed === "-") {
    return str;
  }

  return trimmed;
}
