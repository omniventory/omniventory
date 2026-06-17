/**
 * Supported language codes and normalization utilities.
 *
 * The canonical set is ['en', 'zh']. Any BCP-47 variant of Chinese
 * (zh-CN, zh-TW, zh-Hans, etc.) normalizes to 'zh'; everything else
 * falls back to 'en'.
 */

export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;

export type LanguageCode = (typeof SUPPORTED_LANGUAGES)[number];

/**
 * Normalize a raw language string (from navigator.language, localStorage,
 * or user input) to one of the two supported canonical codes.
 *
 * Rules (case-insensitive):
 *   - Starts with "zh" → 'zh'  (handles zh, zh-CN, zh-TW, zh-Hans, zh-Hant, …)
 *   - Everything else  → 'en'  (canonical fallback)
 */
export function normalizeLanguage(
  input: string | undefined | null,
): LanguageCode {
  if (!input) return "en";
  const lower = input.toLowerCase();
  if (lower === "zh" || lower.startsWith("zh-")) return "zh";
  return "en";
}
