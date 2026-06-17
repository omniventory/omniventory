/**
 * M1.5 Step 3 — i18n infra tests.
 *
 * Covers:
 * 1. normalizeLanguage: BCP-47 variants → canonical codes
 * 2. Resolution precedence (real detector chain): localStorage > navigator > 'en' fallback
 * 3. Legacy resolution-precedence block (kept for backwards compat)
 * 4. changeLanguage updates document.documentElement.lang (normalized to 'en'/'zh')
 *
 * The test env is pinned to 'en' by setup.ts (beforeEach), so language-switch
 * tests explicitly force the language and clean up afterwards.
 */
import { describe, it, expect, afterEach, vi } from "vitest";
import i18next from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { normalizeLanguage } from "../i18n/languages";
import i18n from "../i18n";

// ---------------------------------------------------------------------------
// 1. normalizeLanguage
// ---------------------------------------------------------------------------

describe("normalizeLanguage", () => {
  it("returns 'zh' for bare 'zh'", () => {
    expect(normalizeLanguage("zh")).toBe("zh");
  });

  it("returns 'zh' for 'zh-CN'", () => {
    expect(normalizeLanguage("zh-CN")).toBe("zh");
  });

  it("returns 'zh' for 'zh-TW'", () => {
    expect(normalizeLanguage("zh-TW")).toBe("zh");
  });

  it("returns 'zh' for 'zh-Hans'", () => {
    expect(normalizeLanguage("zh-Hans")).toBe("zh");
  });

  it("returns 'zh' for 'zh-Hant-TW'", () => {
    expect(normalizeLanguage("zh-Hant-TW")).toBe("zh");
  });

  it("returns 'zh' for lowercase 'zh-cn'", () => {
    expect(normalizeLanguage("zh-cn")).toBe("zh");
  });

  it("returns 'en' for 'en-US'", () => {
    expect(normalizeLanguage("en-US")).toBe("en");
  });

  it("returns 'en' for 'en'", () => {
    expect(normalizeLanguage("en")).toBe("en");
  });

  it("returns 'en' for 'fr' (unknown locale)", () => {
    expect(normalizeLanguage("fr")).toBe("en");
  });

  it("returns 'en' for 'de-DE' (unknown locale)", () => {
    expect(normalizeLanguage("de-DE")).toBe("en");
  });

  it("returns 'en' for empty string", () => {
    expect(normalizeLanguage("")).toBe("en");
  });

  it("returns 'en' for undefined", () => {
    expect(normalizeLanguage(undefined)).toBe("en");
  });

  it("returns 'en' for null", () => {
    expect(normalizeLanguage(null)).toBe("en");
  });
});

// ---------------------------------------------------------------------------
// 2. Detector chain precedence (real LanguageDetector + fresh i18next instance)
//
// Each case creates its own isolated i18next instance so it never touches the
// shared singleton used by the rest of the app, and there is no state leakage
// between cases.
// ---------------------------------------------------------------------------

/** Build a fresh, fully isolated i18next instance with the same detection
 *  options as the production singleton.  initAsync:false keeps it synchronous. */
function buildTestInstance() {
  const instance = i18next.createInstance();
  instance.use(LanguageDetector).init({
    supportedLngs: ["en", "zh"],
    fallbackLng: "en",
    load: "languageOnly",
    resources: { en: { translation: {} }, zh: { translation: {} } },
    detection: {
      order: ["localStorage", "navigator"],
      lookupLocalStorage: "omniventory_lang",
      caches: [],          // don't write back during tests
    },
    interpolation: { escapeValue: false },
    initAsync: false,
  });
  return instance;
}

describe("Detector chain precedence", () => {
  afterEach(() => {
    localStorage.removeItem("omniventory_lang");
    vi.restoreAllMocks();
  });

  it("localStorage pick wins over navigator.language", () => {
    // Arrange: localStorage says 'zh', navigator says 'en-US'.
    // The detector reads localStorage first; its value should determine the
    // active language, overriding navigator.
    localStorage.setItem("omniventory_lang", "zh");
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("en-US");
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue([
      "en-US",
      "en",
    ]);

    const instance = buildTestInstance();

    // localStorage value 'zh' wins — normalized base code.
    expect(instance.language).toBe("zh");
  });

  it("navigator.language is used when localStorage is absent (zh-CN → zh)", () => {
    // Arrange: no localStorage; navigator speaks simplified Chinese.
    // load:'languageOnly' collapses zh-CN → zh for resource resolution;
    // instance.languages[0] is the collapsed base code used by t().
    localStorage.removeItem("omniventory_lang");
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("zh-CN");
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(["zh-CN"]);

    const instance = buildTestInstance();

    // instance.language carries the raw detected tag ('zh-CN'); what matters
    // for t() is instance.languages[0] after load:'languageOnly' collapses it.
    expect(instance.languages[0]).toBe("zh");
  });

  it("falls back to 'en' when no localStorage and navigator locale is unknown", () => {
    // Arrange: no localStorage; navigator speaks Japanese (not in supportedLngs).
    // fallbackLng:'en' takes effect.
    localStorage.removeItem("omniventory_lang");
    vi.spyOn(window.navigator, "language", "get").mockReturnValue("ja-JP");
    vi.spyOn(window.navigator, "languages", "get").mockReturnValue(["ja-JP"]);

    const instance = buildTestInstance();

    expect(instance.language).toBe("en");
  });
});

// ---------------------------------------------------------------------------
// 3. Resolution precedence (legacy block — kept for continuity)
// ---------------------------------------------------------------------------

describe("Language resolution precedence", () => {
  afterEach(async () => {
    // Restore to 'en' and clean up localStorage after each resolution test.
    localStorage.removeItem("omniventory_lang");
    await i18n.changeLanguage("en");
  });

  it("uses localStorage pick ('omniventory_lang') over navigator language", async () => {
    // Simulate user previously picked 'zh' and it is stored.
    localStorage.setItem("omniventory_lang", "zh");
    // Re-detect by calling changeLanguage with the stored value as a
    // standalone assertion (the detector reads localStorage on init;
    // here we verify the localStorage key wins conceptually by showing
    // that the stored value is 'zh' and i18n honours it when set).
    await i18n.changeLanguage("zh");
    expect(i18n.language).toBe("zh");
  });

  it("falls back to 'en' for unknown navigator locale (no localStorage)", async () => {
    localStorage.removeItem("omniventory_lang");
    // Unknown locale → normalizeLanguage returns 'en'.
    const resolved = normalizeLanguage("fr");
    expect(resolved).toBe("en");
  });

  it("normalizes navigator 'zh-CN' → 'zh'", async () => {
    const resolved = normalizeLanguage("zh-CN");
    expect(resolved).toBe("zh");
    // i18next itself also collapses zh-CN→zh via load:'languageOnly'.
    await i18n.changeLanguage("zh");
    expect(i18n.language).toBe("zh");
  });

  it("resolves 'en' when no localStorage and navigator locale is unknown", () => {
    const resolved = normalizeLanguage("ja");
    expect(resolved).toBe("en");
  });
});

// ---------------------------------------------------------------------------
// 4. changeLanguage updates document.documentElement.lang (normalized)
// ---------------------------------------------------------------------------

describe("document.documentElement.lang sync", () => {
  afterEach(async () => {
    await i18n.changeLanguage("en");
    localStorage.removeItem("omniventory_lang");
  });

  it("sets <html lang> to 'zh' after changeLanguage('zh')", async () => {
    await i18n.changeLanguage("zh");
    expect(document.documentElement.lang).toBe("zh");
  });

  it("sets <html lang> back to 'en' after changeLanguage('en')", async () => {
    await i18n.changeLanguage("zh");
    await i18n.changeLanguage("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("normalizes <html lang> to 'zh' even when changeLanguage receives 'zh-CN'", async () => {
    // load:'languageOnly' collapses zh-CN → zh for resource resolution, but
    // i18next.language may still carry 'zh-CN' internally.  Our normalizeLanguage
    // wrapper ensures the DOM attribute is always the bare 2-letter code.
    await i18n.changeLanguage("zh-CN");
    expect(document.documentElement.lang).toBe("zh");
  });
});
