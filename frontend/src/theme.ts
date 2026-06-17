/**
 * Mantine theme tokens — the single "style foundation".
 *
 * A future re-skin = editing this one object.  Do not scatter Mantine theme
 * customizations elsewhere; reference these tokens (or Mantine's CSS variables)
 * throughout the app instead.
 *
 * Design language goal: "restrained, trustworthy, moderate information density."
 * All visual customisation lives here; components reference tokens or Mantine
 * CSS variables (var(--mantine-*), c="dimmed", light-dark()) — no magic numbers.
 *
 * Light / dark: fully theme-aware.  Both colour schemes must look correct.
 *
 * App background intent (applied to the shell in Step 2 — NOT wired here):
 *   light → var(--mantine-color-gray-0)   (one shade "deeper" than white so
 *   dark  → var(--mantine-color-dark-8)    cards/tables float above the page)
 *   Use:  background: light-dark(var(--mantine-color-gray-0),
 *                                var(--mantine-color-dark-8))
 */
import { createTheme } from "@mantine/core";

export const theme = createTheme({
  // ── Brand ────────────────────────────────────────────────────────────────
  /** Primary color — "trustworthy inventory" calm hue. */
  primaryColor: "teal",

  // ── Global shape & interaction ───────────────────────────────────────────
  /**
   * Unified corner radius: slightly rounder than the Mantine default ("sm"),
   * giving a modern but not bubbly feel.
   */
  defaultRadius: "md",

  /**
   * Show a pointer cursor on interactive controls (Checkbox, Radio, Switch,
   * etc.) — improves perceived affordance.
   */
  cursorType: "pointer",

  // ── Typography ───────────────────────────────────────────────────────────
  /**
   * Keep the system font stack (fontFamily / headings.fontFamily) so we avoid
   * web-font downloads and FOUT.  Only override fontWeight for headings:
   * "600" reads as authoritative without the heaviness of the default "700".
   */
  headings: {
    fontWeight: "600",
  },

  // ── Component defaults ───────────────────────────────────────────────────
  /**
   * Consolidate per-component prop defaults here so usage sites stay clean.
   * These propagate to every instance without explicit prop repetition.
   */
  components: {
    Card: {
      defaultProps: {
        radius: "md",
        withBorder: true,
        shadow: "sm",
        padding: "lg",
      },
    },
    Paper: {
      defaultProps: {
        radius: "md",
      },
    },
    Button: {
      defaultProps: {
        radius: "md",
      },
    },
    Modal: {
      defaultProps: {
        radius: "md",
        centered: true,
      },
    },
    Tooltip: {
      defaultProps: {
        withArrow: true,
      },
    },
  },
});
