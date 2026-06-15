/**
 * App root.
 *
 * Auth-gate approach (lean, no router library for M0):
 *   - On mount, call GET /api/auth/me to determine if a session cookie exists.
 *   - authed=true  → render the AppShell with a placeholder welcome page.
 *   - authed=false → render the Login page.
 *   - authed=null  → still resolving (show nothing / brief flash avoided by
 *                    rendering a loading state).
 *
 * Session is 100% cookie-based.  Nothing auth-related is stored in
 * localStorage or sessionStorage.
 */
import { useEffect, useState } from "react";
import { LoadingOverlay, Box } from "@mantine/core";
import { AppShell } from "./shell/AppShell";
import { Login } from "./pages/Login";
import { PageShell } from "./components/PageShell";
import { client } from "./api/client";

type AuthState = "loading" | "authed" | "anon";

function App() {
  const [authState, setAuthState] = useState<AuthState>("loading");

  useEffect(() => {
    client
      .GET("/api/auth/me")
      .then(({ error }) => {
        setAuthState(error ? "anon" : "authed");
      })
      .catch(() => setAuthState("anon"));
  }, []);

  if (authState === "loading") {
    return (
      <Box pos="relative" h="100dvh">
        <LoadingOverlay visible />
      </Box>
    );
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
