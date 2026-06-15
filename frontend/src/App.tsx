/**
 * App root.
 *
 * Auth-gate approach (lean, no router library for M0):
 *   1. On mount, call GET /api/auth/setup-status.
 *      - setup_required: true  → show Setup page (first-run onboarding).
 *   2. If setup is not required, call GET /api/auth/me.
 *      - 200  → show the authenticated AppShell.
 *      - 401  → show the Login page.
 *   3. Loading state while resolving.
 *
 * After setup success → transition to Login (anon state; user must log in).
 * Session is 100% cookie-based.  Nothing auth-related is stored in
 * localStorage or sessionStorage.
 */
import { useEffect, useState } from "react";
import { LoadingOverlay, Box } from "@mantine/core";
import { AppShell } from "./shell/AppShell";
import { Login } from "./pages/Login";
import { Setup } from "./pages/Setup";
import { PageShell } from "./components/PageShell";
import { client } from "./api/client";

type AuthState = "loading" | "setup" | "authed" | "anon";

function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    async function checkState() {
      // Step 1: check if first-run setup is required.
      const { data: setupData, error: setupError } = await client.GET(
        "/api/auth/setup-status",
      );
      if (setupError || !setupData) {
        // If setup-status fails for any reason, fall through to auth check.
        // (Shouldn't happen in normal operation.)
      } else if (setupData.setup_required) {
        setAuthState("setup");
        return;
      }

      // Step 2: check if user is already authenticated.
      const { error: meError } = await client.GET("/api/auth/me");
      setAuthState(meError ? "anon" : "authed");
    }

    checkState().catch(() => setAuthState("anon"));
  }, []);

  if (authState === "loading") {
    return (
      <Box pos="relative" h="100dvh">
        <LoadingOverlay visible />
      </Box>
    );
  }

  if (authState === "setup") {
    // After setup, go to login (do NOT auto-login).
    return <Setup onSuccess={() => setAuthState("anon")} />;
  }

  if (authState === "anon") {
    return <Login onSuccess={() => setAuthState("authed")} />;
  }

  return (
    <AppShell onLogout={() => setAuthState("anon")}>
      <PageShell title="Welcome" />
    </AppShell>
  );
}

export default App;
