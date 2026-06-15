/**
 * Mantine theme tokens — the single "style foundation".
 *
 * A future re-skin = editing this one object.  Do not scatter Mantine theme
 * customizations elsewhere; reference these tokens (or Mantine's CSS variables)
 * throughout the app instead.
 */
import { createTheme } from "@mantine/core";

export const theme = createTheme({
  /** Primary color — "trustworthy inventory" calm hue. */
  primaryColor: "teal",

  /**
   * Font, radius, and spacing use Mantine defaults so we don't fight the
   * library.  Override here (not inline) if that ever changes.
   */
});
