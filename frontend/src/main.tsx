/**
 * Application entry point.
 *
 * Wraps the React tree in:
 *   - MantineProvider (theme tokens from theme.ts)
 *   - ColorSchemeScript (prevents flash-of-wrong-theme on load)
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { MantineProvider, ColorSchemeScript } from "@mantine/core";

// Mantine core styles — must come before component styles
import "@mantine/core/styles.css";

import { theme } from "./theme";
import App from "./App";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element not found");
}

createRoot(rootElement).render(
  <StrictMode>
    {/*
     * ColorSchemeScript must render in <head> in production, but here inside
     * <body> it still sets the data-mantine-color-scheme attribute before
     * hydration to avoid a flash.  For Vite SPA we inject it just before the
     * React tree; the effect is the same.
     */}
    <ColorSchemeScript defaultColorScheme="auto" />
    <MantineProvider theme={theme} defaultColorScheme="auto">
      <App />
    </MantineProvider>
  </StrictMode>,
);
