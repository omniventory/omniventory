/**
 * M6 Step 13 — Audit log page tests.
 *
 * Coverage (per §10 Step 13 blind-review checkpoints + §5 frontend quality gates):
 *
 *  1. List renders: GET /api/audit rows shown (time/event/actor/target/detail).
 *  2. Null-actor row: failed-login row with actor_email=null renders the
 *     nullActor placeholder.
 *  3. Event-type filter: changing the NativeSelect refetches GET /api/audit
 *     with event_type in the query.
 *  4. Actor-id filter: changing the actor-id input refetches with actor_id.
 *  5. Date-range filters: changing from/to refetches with the date strings.
 *  6. Pagination — next: clicking "next" increments offset by the limit and
 *     refetches.
 *  7. Pagination — prev: clicking "prev" decrements offset (back to 0) and
 *     refetches.
 *  8. Pagination total drives controls: "next" disabled when last page.
 *  9. Admin-gated nav: Audit item present for admin, absent for member/viewer.
 * 10. Admin-gated route: /audit redirects a non-admin to /.
 * 11. en+zh parity for the audit namespace (asserted directly; also enforced
 *     by the i18n-catalog.test.ts suite).
 *
 * All tests are pinned to 'en' (M1.5 convention).
 * The typed client is mocked; components are wrapped in:
 *   AuthProvider (admin) + MantineProvider + MemoryRouter.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// i18n must be initialized before any component that calls useTranslation().
import "../i18n/index.js";

import { AuthProvider } from "../auth/AuthContext";
import { RequirePermission } from "../auth/RequirePermission";
import { NavContent_testable } from "../shell/AppShell";
import { Audit } from "../pages/Audit";
import type { components } from "../api/schema";

import enAudit from "../i18n/locales/en/audit.json";
import zhAudit from "../i18n/locales/zh/audit.json";

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

// ── Types ──────────────────────────────────────────────────────────────────────

type UserResponse = components["schemas"]["UserResponse"];
type AuditLogResponse = components["schemas"]["AuditLogResponse"];
type AuditLogListResponse = components["schemas"]["AuditLogListResponse"];

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeUser(role: "admin" | "member" | "viewer"): UserResponse {
  return {
    id: 1,
    email: `${role}@example.com`,
    role,
    is_active: true,
    notify_in_app: true,
    notify_email_digest: true,
    created_at: "2026-01-01T00:00:00Z",
    preferred_language: "en",
  };
}

const adminUser = makeUser("admin");
const memberUser = makeUser("member");
const viewerUser = makeUser("viewer");

const rowLoginSucceeded: AuditLogResponse = {
  id: 1,
  event_type: "auth.login_succeeded",
  actor_email: "admin@example.com",
  target_type: null,
  target_id: null,
  params: null,
  ip_address: "127.0.0.1",
  created_at: "2026-06-01T10:00:00Z",
};

const rowLoginFailed: AuditLogResponse = {
  id: 2,
  event_type: "auth.login_failed",
  actor_email: null, // failed login: no actor user
  target_type: null,
  target_id: null,
  params: { email: "attacker@example.com" },
  ip_address: "10.0.0.5",
  created_at: "2026-06-01T09:00:00Z",
};

const rowRoleChanged: AuditLogResponse = {
  id: 3,
  event_type: "user.role_changed",
  actor_email: "admin@example.com",
  target_type: "user",
  target_id: 2,
  params: { old_role: "member", new_role: "admin" },
  ip_address: "192.168.1.1",
  created_at: "2026-06-01T08:00:00Z",
};

function makeListResponse(
  items: AuditLogResponse[],
  total = items.length,
  offset = 0,
  limit = 50,
): AuditLogListResponse {
  return { items, total, offset, limit };
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Wrap in admin AuthProvider + MantineProvider + MemoryRouter. */
function withAdminAuth(children: React.ReactNode) {
  return (
    <AuthProvider user={adminUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
      {children}
    </AuthProvider>
  );
}

/** Render the Audit page as admin. */
function renderAuditPage() {
  return render(
    <MemoryRouter>
      <MantineProvider>
        {withAdminAuth(<Audit />)}
      </MantineProvider>
    </MemoryRouter>,
  );
}

/** Standard GET /api/audit mock returning the given list response. */
function mockAuditGet(response: AuditLogListResponse) {
  vi.mocked(client.GET).mockResolvedValue({
    data: response,
    error: undefined,
    response: new Response(null, { status: 200 }),
  } as AnyResult);
}

/** Wait for the table body to render (loading spinner gone). */
async function waitForTable() {
  await waitFor(() => {
    // The "Time" column header is only visible when loading is done.
    expect(screen.getAllByRole("columnheader").length).toBeGreaterThan(0);
  });
}

// ── 1. List renders ────────────────────────────────────────────────────────────

describe("Audit page — list renders", () => {
  beforeEach(() => {
    mockAuditGet(makeListResponse([rowLoginSucceeded, rowLoginFailed, rowRoleChanged]));
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("shows the page title", async () => {
    renderAuditPage();
    await waitForTable();
    expect(screen.getByText("Audit Log")).toBeDefined();
  });

  it("renders a row for a login_succeeded event with actor email", async () => {
    renderAuditPage();
    await waitForTable();
    expect(screen.getByTestId("audit-row-1")).toBeDefined();
    // Two rows share actor_email "admin@example.com" (row-1 and row-3); use
    // getAllByText to avoid "multiple elements found".
    expect(screen.getAllByText("admin@example.com").length).toBeGreaterThan(0);
    // "Login succeeded" appears both in the filter <option> and in the table row.
    expect(screen.getAllByText("Login succeeded").length).toBeGreaterThan(0);
  });

  it("renders the target cell for a user.role_changed event", async () => {
    renderAuditPage();
    await waitForTable();
    expect(screen.getByText("user #2")).toBeDefined();
  });

  it("renders params for a row that has params", async () => {
    renderAuditPage();
    await waitForTable();
    // rowRoleChanged has params { old_role: "member", new_role: "admin" }
    // rendered as "old_role=member, new_role=admin" inside a Code element
    expect(screen.getByText("old_role=member, new_role=admin")).toBeDefined();
  });

  it("shows '—' for params when params is null", async () => {
    renderAuditPage();
    await waitForTable();
    // rowLoginSucceeded has params: null → rendered as "—"
    // There will be multiple "—" cells but we just need at least one present.
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThan(0);
  });
});

// ── 2. Null-actor row renders placeholder ─────────────────────────────────────

describe("Audit page — null actor placeholder", () => {
  beforeEach(() => {
    mockAuditGet(makeListResponse([rowLoginFailed]));
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("renders 'System / Unknown' when actor_email is null", async () => {
    renderAuditPage();
    await waitForTable();
    expect(screen.getByText("System / Unknown")).toBeDefined();
  });

  it("renders the login_failed event label", async () => {
    renderAuditPage();
    await waitForTable();
    // "Login failed" appears both in the filter <option> and in the table row.
    expect(screen.getAllByText("Login failed").length).toBeGreaterThan(0);
  });
});

// ── 3. Event-type filter ──────────────────────────────────────────────────────

describe("Audit page — event-type filter", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("refetches GET /api/audit with event_type when filter changes", async () => {
    // Initial load: return all events
    mockAuditGet(makeListResponse([rowLoginSucceeded]));
    renderAuditPage();
    await waitForTable();

    // Change the event-type filter
    const select = screen.getByTestId("filter-event-type");
    fireEvent.change(select, { target: { value: "auth.login_failed" } });

    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      // The second call should include event_type: "auth.login_failed"
      const lastCall = calls[calls.length - 1];
      expect(lastCall[0]).toBe("/api/audit");
      const query = (lastCall[1] as AnyResult)?.params?.query;
      expect(query?.event_type).toBe("auth.login_failed");
    });
  });

  it("sends event_type: undefined when 'All events' is selected", async () => {
    mockAuditGet(makeListResponse([rowLoginSucceeded]));
    renderAuditPage();
    await waitForTable();

    // Select a specific type first
    const select = screen.getByTestId("filter-event-type");
    fireEvent.change(select, { target: { value: "auth.logout" } });
    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      expect((last[1] as AnyResult)?.params?.query?.event_type).toBe("auth.logout");
    });

    // Now reset to "all"
    fireEvent.change(select, { target: { value: "" } });
    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      const query = (last[1] as AnyResult)?.params?.query;
      // Empty string becomes undefined (or absent) so the filter is cleared
      expect(query?.event_type == null || query?.event_type === "").toBe(true);
    });
  });
});

// ── 4. Actor-id filter ────────────────────────────────────────────────────────

describe("Audit page — actor-id filter", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("refetches with actor_id when actor-id input changes", async () => {
    mockAuditGet(makeListResponse([rowLoginSucceeded]));
    renderAuditPage();
    await waitForTable();

    const actorInput = screen.getByTestId("filter-actor-id");
    fireEvent.change(actorInput, { target: { value: "42" } });

    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      const query = (last[1] as AnyResult)?.params?.query;
      expect(query?.actor_id).toBe(42);
    });
  });
});

// ── 5. Date-range filters ─────────────────────────────────────────────────────

describe("Audit page — date-range filters", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("refetches with from when 'from' date input changes", async () => {
    mockAuditGet(makeListResponse([rowLoginSucceeded]));
    renderAuditPage();
    await waitForTable();

    const fromInput = screen.getByTestId("filter-from");
    fireEvent.change(fromInput, { target: { value: "2026-06-01" } });

    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      const query = (last[1] as AnyResult)?.params?.query;
      expect(query?.from).toBe("2026-06-01");
    });
  });

  it("refetches with to when 'to' date input changes", async () => {
    mockAuditGet(makeListResponse([rowLoginSucceeded]));
    renderAuditPage();
    await waitForTable();

    const toInput = screen.getByTestId("filter-to");
    fireEvent.change(toInput, { target: { value: "2026-06-30" } });

    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      const query = (last[1] as AnyResult)?.params?.query;
      expect(query?.to).toBe("2026-06-30");
    });
  });
});

// ── 6–8. Pagination ───────────────────────────────────────────────────────────

describe("Audit page — pagination", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("clicking 'next' increments offset by limit and refetches", async () => {
    // 100 total events, first page of 50
    mockAuditGet(makeListResponse([rowLoginSucceeded], 100, 0, 50));
    renderAuditPage();
    await waitForTable();

    const nextBtn = screen.getByTestId("next-btn");
    fireEvent.click(nextBtn);

    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      const query = (last[1] as AnyResult)?.params?.query;
      expect(query?.offset).toBe(50);
    });
  });

  it("clicking 'prev' decrements offset and refetches", async () => {
    // Render with offset=50 by setting initial state via next, then prev
    mockAuditGet(makeListResponse([rowLoginSucceeded], 100, 0, 50));
    renderAuditPage();
    await waitForTable();

    // Go to page 2
    fireEvent.click(screen.getByTestId("next-btn"));
    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      expect((last[1] as AnyResult)?.params?.query?.offset).toBe(50);
    });

    // Go back to page 1
    fireEvent.click(screen.getByTestId("prev-btn"));
    await waitFor(() => {
      const calls = vi.mocked(client.GET).mock.calls;
      const last = calls[calls.length - 1];
      expect((last[1] as AnyResult)?.params?.query?.offset).toBe(0);
    });
  });

  it("'next' button is disabled when on the last page (offset+limit >= total)", async () => {
    // 30 total events, limit=50, offset=0 → next should be disabled
    mockAuditGet(makeListResponse([rowLoginSucceeded, rowLoginFailed], 2, 0, 50));
    renderAuditPage();
    await waitForTable();

    const nextBtn = screen.getByTestId("next-btn");
    expect((nextBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("'prev' button is disabled when on the first page (offset=0)", async () => {
    mockAuditGet(makeListResponse([rowLoginSucceeded], 100, 0, 50));
    renderAuditPage();
    await waitForTable();

    const prevBtn = screen.getByTestId("prev-btn");
    expect((prevBtn as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows 'total drives controls' — Showing X–Y of Z text when events exist", async () => {
    // 100 total, showing first 50 → "Showing 1–50 of 100"
    mockAuditGet(makeListResponse([rowLoginSucceeded], 100, 0, 50));
    renderAuditPage();
    await waitForTable();

    // The exact text depends on i18n: "Showing 1–50 of 100"
    await waitFor(() => {
      expect(screen.getByText(/Showing 1/)).toBeDefined();
    });
  });
});

// ── 9. Admin-gated nav ────────────────────────────────────────────────────────

describe("Audit — admin-gated nav item", () => {
  it("Audit nav item present for admin", () => {
    render(
      <MemoryRouter>
        <MantineProvider>
          <AuthProvider user={adminUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
            <NavContent_testable />
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    );
    expect(screen.getByText("Audit Log")).toBeDefined();
  });

  it("Audit nav item absent for member", () => {
    render(
      <MemoryRouter>
        <MantineProvider>
          <AuthProvider user={memberUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
            <NavContent_testable />
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByText("Audit Log")).toBeNull();
  });

  it("Audit nav item absent for viewer", () => {
    render(
      <MemoryRouter>
        <MantineProvider>
          <AuthProvider user={viewerUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
            <NavContent_testable />
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    );
    expect(screen.queryByText("Audit Log")).toBeNull();
  });
});

// ── 10. Admin-gated route ─────────────────────────────────────────────────────

describe("Audit — admin-gated route redirect", () => {
  it("redirects a non-admin to / when navigating to /audit", () => {
    // Render a minimal router with /audit (RequirePermission) + / (home sentinel)
    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <MantineProvider>
          <AuthProvider user={memberUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
            <Routes>
              <Route
                path="/audit"
                element={
                  <RequirePermission permission="VIEW_AUDIT">
                    <Audit />
                  </RequirePermission>
                }
              />
              <Route path="/" element={<div data-testid="home-page">Home</div>} />
            </Routes>
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    );

    // RequirePermission redirects to / — home-page sentinel should render.
    expect(screen.getByTestId("home-page")).toBeDefined();
  });

  it("admin can access /audit without redirect", async () => {
    mockAuditGet(makeListResponse([]));
    render(
      <MemoryRouter initialEntries={["/audit"]}>
        <MantineProvider>
          <AuthProvider user={adminUser} onRefresh={vi.fn()} onLogout={vi.fn()}>
            <Routes>
              <Route
                path="/audit"
                element={
                  <RequirePermission permission="VIEW_AUDIT">
                    <Audit />
                  </RequirePermission>
                }
              />
              <Route path="/" element={<div data-testid="home-page">Home</div>} />
            </Routes>
          </AuthProvider>
        </MantineProvider>
      </MemoryRouter>,
    );

    await waitForTable();
    // The Audit page title should be visible (not the home sentinel).
    expect(screen.getByText("Audit Log")).toBeDefined();
    expect(screen.queryByTestId("home-page")).toBeNull();
  });
});

// ── 11. en+zh parity for audit namespace ─────────────────────────────────────

describe("Audit i18n — en+zh parity", () => {
  /**
   * Recursively collect all leaf key paths from a nested object.
   * Mirrors the helper in i18n-catalog.test.ts.
   */
  function collectKeys(obj: unknown, prefix = ""): string[] {
    if (typeof obj !== "object" || obj === null) return [prefix];
    const keys: string[] = [];
    for (const [key, value] of Object.entries(obj as Record<string, unknown>)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (typeof value === "object" && value !== null && !Array.isArray(value)) {
        keys.push(...collectKeys(value, path));
      } else {
        keys.push(path);
      }
    }
    return keys;
  }

  it("audit namespace has identical keys in en and zh", () => {
    const enKeys = collectKeys(enAudit).sort();
    const zhKeys = collectKeys(zhAudit).sort();

    const missingInZh = enKeys.filter((k) => !zhKeys.includes(k));
    const extraInZh = zhKeys.filter((k) => !enKeys.includes(k));

    expect(missingInZh, "Keys in en/audit missing from zh/audit").toEqual([]);
    expect(extraInZh, "Extra keys in zh/audit not present in en/audit").toEqual([]);
  });
});
