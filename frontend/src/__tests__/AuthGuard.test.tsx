/**
 * Auth guard tests.
 *
 * Verifies that App.tsx's inline auth guard:
 * 1. Shows Login when GET /api/auth/me returns 401 (unauthenticated).
 * 2. Shows the shell (AppShell) when GET /api/auth/me returns 200 (authenticated).
 *
 * We mock the typed API client module directly (not fetch) because openapi-fetch
 * captures globalThis.fetch at createClient() time, so stubbing fetch after the
 * module loads has no effect.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import App from "../App.js";

/** Mock the typed client module. */
vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}));

/** Import the mocked client so we can configure its return values per test. */
import { client } from "../api/client.js";

function renderApp() {
  return render(
    <MantineProvider>
      <App />
    </MantineProvider>,
  );
}

describe("Auth guard", () => {
  describe("when /api/auth/me returns 401", () => {
    beforeEach(() => {
      vi.mocked(client.GET).mockResolvedValue({
        error: { detail: "Not authenticated" },
        response: new Response(null, { status: 401 }),
      });
    });

    it("shows the Login page (Sign in button visible)", async () => {
      renderApp();
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
      });
    });

    it("does NOT show the app shell logout button", async () => {
      renderApp();
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
      });
      expect(screen.queryByRole("button", { name: /logout/i })).toBeNull();
    });
  });

  describe("when /api/auth/me returns 200", () => {
    beforeEach(() => {
      vi.mocked(client.GET).mockResolvedValue({
        data: {
          user: {
            id: 1,
            email: "admin@example.com",
            role: "admin",
            is_active: true,
            created_at: "2025-01-01T00:00:00Z",
          },
        },
        response: new Response(null, { status: 200 }),
      });
      vi.mocked(client.POST).mockResolvedValue({
        data: { message: "Logged out" },
        response: new Response(null, { status: 200 }),
      });
    });

    it("shows the logout button in the shell header", async () => {
      renderApp();
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /logout/i })).toBeDefined();
      });
    });

    it("does NOT show the Login (sign-in) submit button", async () => {
      renderApp();
      await waitFor(() => {
        expect(screen.getByRole("button", { name: /logout/i })).toBeDefined();
      });
      expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
    });
  });
});
