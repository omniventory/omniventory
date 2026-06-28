/**
 * M6 Step 12 — Per-user notification preferences UI tests.
 *
 * Coverage (per §10 Step 12 blind-review checkpoints + §5 frontend quality gates):
 *
 *  1. Reflect server state: GET /api/auth/me returning notify_in_app=false /
 *     notify_email_digest=true renders the toggles in those states (off / on).
 *
 *  2. Reflect server state: both toggles on (notify_in_app=true /
 *     notify_email_digest=true) renders both checked.
 *
 *  3. Round-trip: toggling in-app off and saving PATCHes /api/auth/me with
 *     notify_in_app=false / notify_email_digest=true (the current digest state).
 *
 *  4. Round-trip: toggling email digest off and saving PATCHes /api/auth/me with
 *     notify_email_digest=false / notify_in_app=true.
 *
 *  5. Round-trip: both toggles off → PATCH carries notify_in_app=false /
 *     notify_email_digest=false.
 *
 *  6. Save calls refresh() so AuthContext is updated (refresh mock is called).
 *
 *  7. en+zh parity for account.notifications.* keys (covered by i18n-catalog.test.ts;
 *     noted here for blind reviewer reference).
 *
 * All tests pinned to 'en'. Client is mocked; AuthContext is provided via renderAuthed.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";

// i18n must be initialized before any component that calls useTranslation().
import "../i18n/index.js";

import { Account } from "../pages/Account";
import { AuthProvider } from "../auth/AuthContext";
import type { components } from "../api/schema";

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

const baseUser: UserResponse = {
  id: 1,
  email: "user@example.com",
  role: "member",
  is_active: true,
  notify_in_app: true,
  notify_email_digest: true,
  created_at: "2026-01-01T00:00:00Z",
  preferred_language: "en",
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

/**
 * Build a me-response fixture with the given notify prefs.
 * reminder lead days default to null (no overrides).
 */
function makeMe(notifyInApp: boolean, notifyEmailDigest: boolean): AnyResult {
  return {
    user: {
      ...baseUser,
      notify_in_app: notifyInApp,
      notify_email_digest: notifyEmailDigest,
      reminder_best_before_lead_days: null,
      reminder_warranty_lead_days: null,
    },
  };
}

/**
 * Wrap in AuthProvider + MantineProvider + MemoryRouter.
 * Accepts an optional onRefresh spy so tests can verify refresh() is called.
 */
function renderAuthed(node: React.ReactNode, onRefresh?: ReturnType<typeof vi.fn>) {
  const refreshSpy = onRefresh ?? vi.fn();
  return {
    refreshSpy,
    ...render(
      <MemoryRouter>
        <MantineProvider>
          <AuthProvider user={baseUser} onRefresh={refreshSpy} onLogout={vi.fn()}>
            {node}
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    ),
  };
}

/**
 * Set up the GET mock for a given me fixture.
 * GET /api/auth/me → me fixture; GET /api/settings → baseSettings.
 */
function mockLoad(me: AnyResult) {
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

/**
 * Get the inner <input> nested inside a Mantine wrapper element (Switch, NumberInput, etc.).
 */
function getInput(testId: string): HTMLInputElement {
  const wrapper = screen.getByTestId(testId);
  return (wrapper.querySelector("input") ?? wrapper) as HTMLInputElement;
}

/**
 * Wait for the Account page to finish loading (both toggles visible).
 */
async function waitForPage() {
  await waitFor(() => {
    expect(screen.getByTestId("notify-in-app-toggle")).toBeDefined();
    expect(screen.getByTestId("notify-email-digest-toggle")).toBeDefined();
  });
}

// ── 1–2. Reflect server state ─────────────────────────────────────────────────

describe("Account page — notification prefs: reflect server state", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("notify_in_app=false → in-app toggle is unchecked; notify_email_digest=true → email toggle is checked", async () => {
    mockLoad(makeMe(false, true));
    renderAuthed(<Account />);

    await waitForPage();

    const inAppInput = getInput("notify-in-app-toggle");
    const emailInput = getInput("notify-email-digest-toggle");

    expect(inAppInput.checked).toBe(false);
    expect(emailInput.checked).toBe(true);
  });

  it("both notify prefs true → both toggles are checked", async () => {
    mockLoad(makeMe(true, true));
    renderAuthed(<Account />);

    await waitForPage();

    const inAppInput = getInput("notify-in-app-toggle");
    const emailInput = getInput("notify-email-digest-toggle");

    expect(inAppInput.checked).toBe(true);
    expect(emailInput.checked).toBe(true);
  });

  it("notify_in_app=true, notify_email_digest=false → in-app checked; email unchecked", async () => {
    mockLoad(makeMe(true, false));
    renderAuthed(<Account />);

    await waitForPage();

    const inAppInput = getInput("notify-in-app-toggle");
    const emailInput = getInput("notify-email-digest-toggle");

    expect(inAppInput.checked).toBe(true);
    expect(emailInput.checked).toBe(false);
  });
});

// ── 3–5. Round-trip PATCH ─────────────────────────────────────────────────────

describe("Account page — notification prefs: round-trip PATCH /api/auth/me", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("toggling in-app off and saving PATCHes with notify_in_app=false / notify_email_digest=true", async () => {
    // Server starts with both on
    mockLoad(makeMe(true, true));

    let patchPath: AnyResult = null;
    let patchBody: AnyResult = null;
    vi.mocked(client.PATCH).mockImplementation(async (path: AnyResult, opts: AnyResult) => {
      patchPath = path;
      patchBody = opts?.body;
      return { data: makeMe(false, true), error: undefined, response: new Response(null, { status: 200 }) };
    });

    renderAuthed(<Account />);
    await waitForPage();

    // Toggle in-app off
    fireEvent.click(getInput("notify-in-app-toggle"));

    // Save
    await act(async () => {
      fireEvent.click(screen.getByTestId("save-notif-btn"));
    });

    await waitFor(() => {
      expect(patchPath).toBe("/api/auth/me");
    });

    expect(patchBody?.notify_in_app).toBe(false);
    expect(patchBody?.notify_email_digest).toBe(true);
  });

  it("toggling email digest off and saving PATCHes with notify_email_digest=false / notify_in_app=true", async () => {
    mockLoad(makeMe(true, true));

    let patchBody: AnyResult = null;
    vi.mocked(client.PATCH).mockImplementation(async (_path: AnyResult, opts: AnyResult) => {
      patchBody = opts?.body;
      return { data: makeMe(true, false), error: undefined, response: new Response(null, { status: 200 }) };
    });

    renderAuthed(<Account />);
    await waitForPage();

    // Toggle email digest off
    fireEvent.click(getInput("notify-email-digest-toggle"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("save-notif-btn"));
    });

    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody?.notify_in_app).toBe(true);
    expect(patchBody?.notify_email_digest).toBe(false);
  });

  it("both toggles off → PATCH carries notify_in_app=false / notify_email_digest=false", async () => {
    // Server starts with both off
    mockLoad(makeMe(false, false));

    let patchBody: AnyResult = null;
    vi.mocked(client.PATCH).mockImplementation(async (_path: AnyResult, opts: AnyResult) => {
      patchBody = opts?.body;
      return { data: makeMe(false, false), error: undefined, response: new Response(null, { status: 200 }) };
    });

    renderAuthed(<Account />);
    await waitForPage();

    // Both are already off (server state reflected); just save
    await act(async () => {
      fireEvent.click(screen.getByTestId("save-notif-btn"));
    });

    await waitFor(() => {
      expect(patchBody).not.toBeNull();
    });

    expect(patchBody?.notify_in_app).toBe(false);
    expect(patchBody?.notify_email_digest).toBe(false);
  });
});

// ── 6. refresh() is called after successful save ──────────────────────────────

describe("Account page — notification prefs: refresh() called after save", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("successful save calls AuthContext refresh() so the bell reflects the new pref", async () => {
    mockLoad(makeMe(true, true));

    vi.mocked(client.PATCH).mockResolvedValue({
      data: makeMe(false, true),
      error: undefined,
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    const onRefreshSpy = vi.fn();
    renderAuthed(<Account />, onRefreshSpy);
    await waitForPage();

    // Toggle in-app off then save
    fireEvent.click(getInput("notify-in-app-toggle"));

    await act(async () => {
      fireEvent.click(screen.getByTestId("save-notif-btn"));
    });

    // refresh() triggers GET /api/auth/me and calls onRefresh(user)
    // The GET mock returns the updated user, so onRefresh is called with the user object.
    await waitFor(() => {
      expect(onRefreshSpy).toHaveBeenCalled();
    });
  });
});
