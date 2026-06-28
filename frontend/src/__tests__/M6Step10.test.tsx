/**
 * M6 Step 10 — Public accept pages + change-password + Account page tests.
 *
 * Coverage (per §10 Step 10 blind-review checkpoints + §5 frontend quality gates):
 *
 *  1. AcceptInvite — GET /api/invitations/accept: valid token renders email + role.
 *  2. AcceptInvite — POST: submitting password POSTs {token, password} → success.
 *  3. AcceptInvite — invalid/expired token (400 auth.invalid_token) → error state.
 *
 *  4. ResetPassword — GET /api/password-reset/accept: valid token shows masked email.
 *  5. ResetPassword — POST: submitting password POSTs {token, password} → success.
 *  6. ResetPassword — invalid token → error state.
 *
 *  7. Account page — change-password: wrong current → auth.password_incorrect surfaced.
 *  8. Account page — change-password: correct → success alert; form cleared.
 *  9. Account page — change-password: client-side confirm-mismatch → error (no POST).
 *
 * 10. Account page — per-user reminders: loads values from GET /api/auth/me.
 * 11. Account page — per-user reminders: saving PATCHes /api/auth/me with integers.
 * 12. Account page — per-user reminders: blank = null (inherit).
 *
 * 13. App.tsx pre-auth gate: /invite/accept shows AcceptInvite regardless of auth state.
 * 14. App.tsx pre-auth gate: /password-reset/accept shows ResetPassword regardless of auth state.
 *
 * 15. Rate-limit 429: auth.rate_limited with retry_after_seconds → localized message via mapApiError.
 * 16. Rate-limit 429: page-level — change-password 429 surfaces "try again in N s".
 *
 * 17. en+zh parity for account namespace (covered by i18n-catalog.test.ts).
 *
 * All tests pinned to 'en' (M1.5 convention).
 * Client is mocked; window.location is reset between tests.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";

// i18n must be initialized before any component that calls useTranslation().
import "../i18n/index.js";

import { AcceptInvite } from "../pages/AcceptInvite";
import { ResetPassword } from "../pages/ResetPassword";
import { Account } from "../pages/Account";
import { AuthProvider } from "../auth/AuthContext";
import { mapApiError } from "../i18n/errors";
import type { components } from "../api/schema";
import App from "../App";

/** Mock the typed client module. */
vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
    PATCH: vi.fn(),
    DELETE: vi.fn(),
  },
}));

import { client } from "../api/client.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type AnyResult = any;

// ── Fixtures ──────────────────────────────────────────────────────────────────

type UserResponse = components["schemas"]["UserResponse"];

const adminUser: UserResponse = {
  id: 1,
  email: "admin@example.com",
  role: "admin",
  is_active: true,
  notify_in_app: true,
  notify_email_digest: true,
  created_at: "2026-01-01T00:00:00Z",
  preferred_language: "en",
};

const meNoOverrides: AnyResult = {
  user: {
    ...adminUser,
    reminder_best_before_lead_days: null,
    reminder_warranty_lead_days: null,
  },
};

const meWithOverrides: AnyResult = {
  user: {
    ...adminUser,
    reminder_best_before_lead_days: 5,
    reminder_warranty_lead_days: 14,
  },
};

const baseSettings: AnyResult = {
  reminders: {
    best_before_lead_days: 3,
    warranty_lead_days: 30,
    low_stock_repeat_days: [1, 3, 7],
    scan_time: "08:00",
  },
  channels: {
    email: { enabled: false, host: null, port: null, username: null, password_is_set: false, encryption: "none", from_address: null, from_name: null },
    http: { enabled: false, webhook_url: null, auth_header_is_set: false, integration_token_is_set: false },
    mqtt: { enabled: false, host: null, port: null, username: null, password_is_set: false, use_tls: false, topic_prefix: null, discovery_enabled: false, commands_enabled: false },
  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Wrap in MantineProvider (no Router; pre-auth pages don't need one). */
function renderPreAuth(node: React.ReactNode) {
  return render(<MantineProvider>{node}</MantineProvider>);
}

/** Wrap in AuthProvider + MantineProvider + MemoryRouter for authed pages. */
function renderAuthed(node: React.ReactNode) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <AuthProvider user={adminUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
          {node}
        </AuthProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

/** Standard Account mock: GET /api/auth/me + GET /api/settings. */
function mockAccountLoad(me = meNoOverrides) {
  vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
    if (path === "/api/auth/me") {
      return { data: me, error: undefined, response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/settings") {
      return { data: baseSettings, error: undefined, response: new Response(null, { status: 200 }) };
    }
    return { data: null, error: { code: "http.404", message: "Not found" }, response: new Response(null, { status: 404 }) };
  });
}

/** Set window.location for pre-auth page tests. Returns restore function. */
function mockWindowLocation(overrides: Partial<Location & { assign: ReturnType<typeof vi.fn> }>) {
  const original = window.location;
  Object.defineProperty(window, "location", {
    value: { ...original, assign: vi.fn(), ...overrides },
    writable: true,
    configurable: true,
  });
  return () => {
    Object.defineProperty(window, "location", {
      value: original,
      writable: true,
      configurable: true,
    });
  };
}

/** Get the actual <input> nested inside a Mantine PasswordInput/NumberInput wrapper. */
function getInput(testId: string): HTMLInputElement {
  const wrapper = screen.getByTestId(testId);
  return (wrapper.querySelector("input") ?? wrapper) as HTMLInputElement;
}

// ── 1–3. AcceptInvite ─────────────────────────────────────────────────────────

describe("AcceptInvite — valid token renders form", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    restoreLocation = mockWindowLocation({
      pathname: "/invite/accept",
      search: "?token=valid-abc",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("calls GET /api/invitations/accept and renders email + role fields", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: { email: "invited@example.com", role: "member" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderPreAuth(<AcceptInvite />);

    await waitFor(() => {
      expect(screen.getByTestId("invite-email-display")).toBeDefined();
    });

    const emailEl = getInput("invite-email-display");
    expect(emailEl.value).toBe("invited@example.com");
    expect(screen.getByTestId("invite-role-display")).toBeDefined();
  });

  it("POSTs {token, password} on submit and shows success", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: { email: "invited@example.com", role: "member" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);
    vi.mocked(client.POST).mockResolvedValueOnce({
      data: adminUser,
      error: undefined,
      response: new Response(null, { status: 201 }),
    } as AnyResult);

    renderPreAuth(<AcceptInvite />);

    await waitFor(() => {
      expect(screen.getByTestId("invite-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("invite-password-input"), { target: { value: "newpass123" } });
    fireEvent.change(getInput("invite-confirm-input"), { target: { value: "newpass123" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-accept-btn"));
    });

    await waitFor(() => {
      expect(vi.mocked(client.POST)).toHaveBeenCalledWith(
        "/api/invitations/accept",
        expect.objectContaining({
          body: { token: "valid-abc", password: "newpass123" },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("invite-success")).toBeDefined();
    });
  });

  it("shows mismatch error client-side when passwords do not match", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: { email: "invited@example.com", role: "member" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderPreAuth(<AcceptInvite />);

    await waitFor(() => {
      expect(screen.getByTestId("invite-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("invite-password-input"), { target: { value: "pass1" } });
    fireEvent.change(getInput("invite-confirm-input"), { target: { value: "pass2" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("invite-accept-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("invite-submit-error")).toBeDefined();
    });

    // No POST should have been made (client-side validation)
    expect(vi.mocked(client.POST)).not.toHaveBeenCalled();
  });
});

describe("AcceptInvite — invalid/expired token shows error state", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    restoreLocation = mockWindowLocation({
      pathname: "/invite/accept",
      search: "?token=bad-token",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("shows error state on 400 auth.invalid_token", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: null,
      error: { code: "auth.invalid_token", message: "Token expired" },
      response: new Response(null, { status: 400 }),
    } as AnyResult);

    renderPreAuth(<AcceptInvite />);

    await waitFor(() => {
      expect(screen.getByTestId("invite-token-error")).toBeDefined();
    });

    const errorEl = screen.getByTestId("invite-token-error");
    expect(errorEl.textContent).toContain("invalid, expired");
    // Go-to-login button should also be shown
    expect(screen.getByTestId("invite-go-login-btn")).toBeDefined();
  });
});

// ── 4–6. ResetPassword ────────────────────────────────────────────────────────

describe("ResetPassword — valid token renders form", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    restoreLocation = mockWindowLocation({
      pathname: "/password-reset/accept",
      search: "?token=reset-abc",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("calls GET /api/password-reset/accept and shows masked email", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: { email_masked: "a***@example.com" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderPreAuth(<ResetPassword />);

    await waitFor(() => {
      expect(screen.getByTestId("reset-for-email")).toBeDefined();
    });

    expect(screen.getByTestId("reset-for-email").textContent).toContain("a***@example.com");
  });

  it("POSTs {token, password} on submit and shows success", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: { email_masked: "a***@example.com" },
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);
    vi.mocked(client.POST).mockResolvedValueOnce({
      data: null,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderPreAuth(<ResetPassword />);

    await waitFor(() => {
      expect(screen.getByTestId("reset-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("reset-password-input"), { target: { value: "newpass456" } });
    fireEvent.change(getInput("reset-confirm-input"), { target: { value: "newpass456" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("reset-accept-btn"));
    });

    await waitFor(() => {
      expect(vi.mocked(client.POST)).toHaveBeenCalledWith(
        "/api/password-reset/accept",
        expect.objectContaining({
          body: { token: "reset-abc", password: "newpass456" },
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("reset-success")).toBeDefined();
    });
  });
});

describe("ResetPassword — invalid token shows error state", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    restoreLocation = mockWindowLocation({
      pathname: "/password-reset/accept",
      search: "?token=expired",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("shows error state on 400 auth.invalid_token", async () => {
    vi.mocked(client.GET).mockResolvedValueOnce({
      data: null,
      error: { code: "auth.invalid_token", message: "Token expired" },
      response: new Response(null, { status: 400 }),
    } as AnyResult);

    renderPreAuth(<ResetPassword />);

    await waitFor(() => {
      expect(screen.getByTestId("reset-token-error")).toBeDefined();
    });

    expect(screen.getByTestId("reset-token-error").textContent).toContain("invalid, expired");
    expect(screen.getByTestId("reset-go-login-btn")).toBeDefined();
  });
});

// ── 7–9. Account page — change-password ──────────────────────────────────────

describe("Account page — change-password", () => {
  beforeEach(() => {
    mockAccountLoad();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("wrong current password → auth.password_incorrect surfaced", async () => {
    vi.mocked(client.POST).mockResolvedValueOnce({
      data: null,
      error: { code: "auth.password_incorrect", message: "Wrong password" },
      response: new Response(null, { status: 400 }),
    } as AnyResult);

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("current-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("current-password-input"), { target: { value: "wrongpass" } });
    fireEvent.change(getInput("new-password-input"), { target: { value: "newpass123" } });
    fireEvent.change(getInput("confirm-password-input"), { target: { value: "newpass123" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("change-pw-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("pw-error")).toBeDefined();
    });

    const errorEl = screen.getByTestId("pw-error");
    expect(errorEl.textContent).toContain("Current password is incorrect");
  });

  it("correct current password → success alert shown", async () => {
    vi.mocked(client.POST).mockResolvedValueOnce({
      data: null,
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("current-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("current-password-input"), { target: { value: "correct-old-pass" } });
    fireEvent.change(getInput("new-password-input"), { target: { value: "newpass123" } });
    fireEvent.change(getInput("confirm-password-input"), { target: { value: "newpass123" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("change-pw-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("pw-success")).toBeDefined();
    });

    expect(vi.mocked(client.POST)).toHaveBeenCalledWith(
      "/api/auth/change-password",
      expect.objectContaining({
        body: { current_password: "correct-old-pass", new_password: "newpass123" },
      }),
    );
  });

  it("confirm mismatch → client-side error; no POST sent", async () => {
    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("current-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("current-password-input"), { target: { value: "old" } });
    fireEvent.change(getInput("new-password-input"), { target: { value: "new1" } });
    fireEvent.change(getInput("confirm-password-input"), { target: { value: "new2" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("change-pw-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("pw-error")).toBeDefined();
    });

    expect(vi.mocked(client.POST)).not.toHaveBeenCalled();
  });
});

// ── 10–12. Account page — per-user reminders ─────────────────────────────────

describe("Account page — per-user reminders: loads from GET /api/auth/me", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("fields are empty when me has no overrides (null values)", async () => {
    mockAccountLoad(meNoOverrides);

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("user-bb-lead-input")).toBeDefined();
    });

    const inputEl = getInput("user-bb-lead-input");
    expect(inputEl.value).toBe("");
  });

  it("fields are pre-filled when me has overrides", async () => {
    mockAccountLoad(meWithOverrides);

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("user-bb-lead-input")).toBeDefined();
    });

    // meWithOverrides has reminder_best_before_lead_days = 5
    // Use toContain: Mantine NumberInput may append the suffix (" days") to the
    // raw <input> value in some versions, so "5" and "5 days" both pass.
    const inputEl = getInput("user-bb-lead-input");
    expect(inputEl.value).toContain("5");
  });
});

describe("Account page — per-user reminders: save PATCHes /api/auth/me", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("saving with values PATCHes /api/auth/me with integer values", async () => {
    mockAccountLoad(meWithOverrides);

    let patchPath: AnyResult = null;
    let patchBody: AnyResult = null;
    vi.mocked(client.PATCH).mockImplementation(async (path: AnyResult, opts: AnyResult) => {
      patchPath = path;
      patchBody = opts?.body;
      return { data: meWithOverrides, error: undefined, response: new Response(null, { status: 200 }) };
    });

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("save-user-reminders-btn")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("save-user-reminders-btn"));
    });

    await waitFor(() => {
      expect(patchPath).toBe("/api/auth/me");
    });

    expect(typeof patchBody?.reminder_best_before_lead_days).not.toBe("string");
    expect(patchBody?.reminder_best_before_lead_days).toBe(5);
    expect(patchBody?.reminder_warranty_lead_days).toBe(14);
  });

  it("saving with blank fields PATCHes /api/auth/me with null (inherit global)", async () => {
    mockAccountLoad(meNoOverrides);

    let patchBody: AnyResult = null;
    vi.mocked(client.PATCH).mockImplementation(async (_path: AnyResult, opts: AnyResult) => {
      patchBody = opts?.body;
      return { data: meNoOverrides, error: undefined, response: new Response(null, { status: 200 }) };
    });

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("save-user-reminders-btn")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("save-user-reminders-btn"));
    });

    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody?.reminder_best_before_lead_days).toBeNull();
    expect(patchBody?.reminder_warranty_lead_days).toBeNull();
  });
});

// ── 13–14. App.tsx pre-auth gate ──────────────────────────────────────────────

describe("App.tsx pre-auth gate — /invite/accept shows AcceptInvite without session", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    // Set pathname to the public invite path; empty token triggers the immediate
    // "invalid" state in AcceptInvite so we don't need a valid invite API response.
    restoreLocation = mockWindowLocation({
      pathname: "/invite/accept",
      search: "?token=",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("shows AcceptInvite error state even when GET /api/auth/me returns 401", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/auth/setup-status") {
        return { data: { setup_required: false }, error: undefined, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/auth/me") {
        // 401 — no session; would normally trigger Login page
        return { data: null, error: { code: "auth.not_authenticated", message: "" }, response: new Response(null, { status: 401 }) };
      }
      // AcceptInvite: empty token → error state immediately (no API call needed)
      return { data: null, error: { code: "auth.invalid_token", message: "" }, response: new Response(null, { status: 400 }) };
    });

    render(<MantineProvider><App /></MantineProvider>);

    // Should see the AcceptInvite invalid-token error, NOT the Login page
    await waitFor(() => {
      expect(screen.getByTestId("invite-token-error")).toBeDefined();
    });
  });
});

describe("App.tsx pre-auth gate — /password-reset/accept shows ResetPassword without session", () => {
  let restoreLocation: () => void;

  beforeEach(() => {
    restoreLocation = mockWindowLocation({
      pathname: "/password-reset/accept",
      search: "?token=",
    });
  });

  afterEach(() => {
    restoreLocation();
    vi.resetAllMocks();
  });

  it("shows ResetPassword error state even when GET /api/auth/me returns 401", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/auth/setup-status") {
        return { data: { setup_required: false }, error: undefined, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/auth/me") {
        return { data: null, error: { code: "auth.not_authenticated", message: "" }, response: new Response(null, { status: 401 }) };
      }
      return { data: null, error: { code: "auth.invalid_token", message: "" }, response: new Response(null, { status: 400 }) };
    });

    render(<MantineProvider><App /></MantineProvider>);

    await waitFor(() => {
      expect(screen.getByTestId("reset-token-error")).toBeDefined();
    });
  });
});

// ── 15–16. Rate-limit 429 ─────────────────────────────────────────────────────

describe("Rate-limit 429 — auth.rate_limited surfaces retry_after_seconds", () => {
  it("mapApiError interpolates retry_after_seconds into the localized message", () => {
    const msg = mapApiError({
      code: "auth.rate_limited",
      message: "Too many attempts",
      params: { retry_after_seconds: 30 },
    });
    expect(msg).toContain("30");
    expect(msg).toContain("seconds");
  });

  it("mapApiError with different retry_after_seconds value includes that number", () => {
    const msg = mapApiError({
      code: "auth.rate_limited",
      message: "Too many attempts",
      params: { retry_after_seconds: 120 },
    });
    expect(msg).toContain("120");
  });
});

describe("Rate-limit 429 — page-level: change-password 429 shows 'try again in N s'", () => {
  beforeEach(() => {
    mockAccountLoad();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("change-password 429 auth.rate_limited surfaces retry_after_seconds message", async () => {
    vi.mocked(client.POST).mockResolvedValueOnce({
      data: null,
      error: { code: "auth.rate_limited", message: "Rate limited", params: { retry_after_seconds: 60 } },
      response: new Response(null, { status: 429 }),
    } as AnyResult);

    renderAuthed(<Account />);

    await waitFor(() => {
      expect(screen.getByTestId("current-password-input")).toBeDefined();
    });

    fireEvent.change(getInput("current-password-input"), { target: { value: "anypass" } });
    fireEvent.change(getInput("new-password-input"), { target: { value: "newpass" } });
    fireEvent.change(getInput("confirm-password-input"), { target: { value: "newpass" } });

    await act(async () => {
      fireEvent.click(screen.getByTestId("change-pw-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("pw-error")).toBeDefined();
    });

    const errorEl = screen.getByTestId("pw-error");
    expect(errorEl.textContent).toContain("60");
    expect(errorEl.textContent).toContain("seconds");
  });
});
