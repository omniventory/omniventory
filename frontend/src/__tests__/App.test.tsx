/**
 * App-level login language preference regression tests.
 *
 * Covers the bug where logging in did not apply the account's
 * preferred_language — the UI stayed at whatever language was selected on
 * the login page, ignoring the persisted account preference.
 *
 * Design spec: review-notes/login-language-pref-fix-design.md §5.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import App from "../App.js";
import i18n from "../i18n";

/** Mock the typed client module. */
vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}));

import { client } from "../api/client.js";

function renderApp() {
  return render(
    <MantineProvider>
      <App />
    </MantineProvider>,
  );
}

/**
 * Helper: set up GET mocks so setup-status returns setup_required:false
 * and /api/auth/me returns 401 (unauthenticated → login page shown).
 */
function mockAnonState() {
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
}

/** Helper: fill login form and submit. */
async function submitLogin(email: string, password: string) {
  fireEvent.change(screen.getByLabelText(/email/i), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText(/password/i, { selector: "input" }), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

// ── Regression: preferred_language applied on login ───────────────────────────

describe("Login language preference — account preferred_language applied after login", () => {
  afterEach(() => {
    // Reset language and localStorage to avoid polluting other tests.
    localStorage.removeItem("omniventory_lang");
  });

  it("switches to account preferred_language (zh) even when login page was in en", async () => {
    // Pre-condition: simulate the user had switched the login page to 'en'.
    localStorage.setItem("omniventory_lang", "en");
    await i18n.changeLanguage("en");

    mockAnonState();

    // POST /api/auth/login returns a UserResponse with preferred_language: "zh"
    vi.mocked(client.POST).mockResolvedValue({
      data: {
        id: 1,
        email: "admin@example.com",
        role: "admin",
        is_active: true,
        created_at: "2025-01-01T00:00:00Z",
        preferred_language: "zh",
      },
      response: new Response(null, { status: 200 }),
    });

    renderApp();

    // Wait for the login page to appear.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
    });

    await submitLogin("admin@example.com", "secret");

    // After login the account preference (zh) must have been applied.
    await waitFor(() => {
      expect(document.documentElement.lang).toBe("zh");
    });
  });

  it("does NOT change language when account preferred_language is null", async () => {
    // Pre-condition: login page is in 'en'.
    localStorage.setItem("omniventory_lang", "en");
    await i18n.changeLanguage("en");

    mockAnonState();

    // POST /api/auth/login returns a UserResponse with preferred_language: null
    vi.mocked(client.POST).mockResolvedValue({
      data: {
        id: 1,
        email: "admin@example.com",
        role: "admin",
        is_active: true,
        created_at: "2025-01-01T00:00:00Z",
        preferred_language: null,
      },
      response: new Response(null, { status: 200 }),
    });

    renderApp();

    // Wait for the login page to appear.
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
    });

    await submitLogin("admin@example.com", "secret");

    // Language must remain 'en' — the null preference must not override it.
    await waitFor(() => {
      // The app transitions away from the login page after successful login.
      expect(screen.queryByRole("button", { name: /sign in/i })).toBeNull();
    });
    expect(document.documentElement.lang).toBe("en");
  });
});
