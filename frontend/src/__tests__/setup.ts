/**
 * Vitest global test setup.
 *
 * jsdom does not implement window.matchMedia or ResizeObserver, but Mantine
 * components (and useComputedColorScheme / AppShell) rely on them.  This setup
 * file provides minimal stubs so tests don't crash.
 *
 * Referenced from vite.config.ts → test.setupFiles.
 *
 * i18n pinning: we force the language to 'en' before every test suite so
 * that assertions matching English copy are deterministic.  Tests that
 * exercise language-switching must explicitly call i18n.changeLanguage('zh')
 * (and can rely on the afterEach reset in their own describe block).
 */

// Initialize i18n (synchronous; registers the i18next singleton).
import i18n from "../i18n";
import { beforeEach } from "vitest";

// Pin to English before each test file runs.
// Using beforeEach ensures any test that switches language gets reset.
beforeEach(async () => {
  // Clear any leftover omniventory_lang in localStorage so the detector
  // does not override our pin.
  localStorage.removeItem("omniventory_lang");
  await i18n.changeLanguage("en");
});

/** Stub window.matchMedia (Mantine's color-scheme hook uses it). */
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});

/** Stub ResizeObserver (Mantine's AppShell and other layout components use it). */
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}

Object.defineProperty(window, "ResizeObserver", {
  writable: true,
  value: ResizeObserverStub,
});

/**
 * Stub Element.prototype.scrollIntoView (jsdom does not implement it).
 * Mantine's Combobox (the engine behind Select) scrolls the active option
 * into view when its dropdown opens, which otherwise throws in jsdom.
 */
Object.defineProperty(Element.prototype, "scrollIntoView", {
  writable: true,
  value: () => {},
});

/**
 * Stub document.fonts (the FontFaceSet API; jsdom does not implement it).
 * Mantine 9's Textarea autosize subscribes to font-loading events
 * (document.fonts.addEventListener("loadingdone", …)) on mount, which
 * otherwise throws "Cannot read properties of undefined" in jsdom and
 * crashes any test that renders a Textarea with the `autosize` prop.
 */
Object.defineProperty(document, "fonts", {
  writable: true,
  value: {
    ready: Promise.resolve(),
    status: "loaded",
    addEventListener: () => {},
    removeEventListener: () => {},
    check: () => true,
    load: () => Promise.resolve([]),
  },
});
