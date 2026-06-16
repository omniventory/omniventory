/**
 * Vitest global test setup.
 *
 * jsdom does not implement window.matchMedia or ResizeObserver, but Mantine
 * components (and useComputedColorScheme / AppShell) rely on them.  This setup
 * file provides minimal stubs so tests don't crash.
 *
 * Referenced from vite.config.ts → test.setupFiles.
 */

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
