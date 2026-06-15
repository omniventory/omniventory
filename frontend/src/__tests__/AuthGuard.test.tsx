/**
 * Auth guard tests.
 *
 * Verifies that App.tsx's inline auth gate:
 * 1. Shows the Setup page when GET /api/auth/setup-status returns setup_required:true.
 * 2. Shows Login when setup_required:false AND /api/auth/me returns 401 (unauthenticated).
 * 3. Shows the shell (AppShell) when setup_required:false AND /api/auth/me returns 200.
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

describe("Auth gate — setup required", () => {
  beforeEach(() => {
    vi.mocked(client.GET).mockImplementation((path) => {
      if (path === "/api/auth/setup-status") {
        return Promise.resolve({
          data: { setup_required: true },
          response: new Response(null, { status: 200 }),
        });
      }
      // /api/auth/me should not be called when setup is required, but handle defensively
      return Promise.resolve({
        error: { detail: "Not authenticated" },
        response: new Response(null, { status: 401 }),
      });
    });
  });

  it("shows the Setup page (create admin account button visible)", async () => {
    renderApp();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create admin account/i }),
      ).toBeDefined();
    });
  });

  it("does NOT show the Login (sign-in) button when setup is required", async () => {
    renderApp();
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /create admin account/i }),
      ).toBeDefined();
    });
    expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
  });
});

describe("Auth gate — setup not required, unauthenticated", () => {
  beforeEach(() => {
    vi.mocked(client.GET).mockImplementation((path) => {
      if (path === "/api/auth/setup-status") {
        return Promise.resolve({
          data: { setup_required: false },
          response: new Response(null, { status: 200 }),
        });
      }
      // /api/auth/me → 401
      return Promise.resolve({
        error: { detail: "Not authenticated" },
        response: new Response(null, { status: 401 }),
      });
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

describe("Auth gate — setup not required, authenticated", () => {
  beforeEach(() => {
    vi.mocked(client.GET).mockImplementation((path) => {
      if (path === "/api/auth/setup-status") {
        return Promise.resolve({
          data: { setup_required: false },
          response: new Response(null, { status: 200 }),
        });
      }
      // /api/auth/me → 200
      return Promise.resolve({
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
