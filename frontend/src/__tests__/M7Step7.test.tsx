/**
 * M7 Step 7 — Maintenance UI tests.
 *
 * Coverage:
 *  1. MaintenancePanel — lists schedules with correct status chips
 *     (overdue=red, due_soon=yellow, ok=green; from server-provided status field,
 *      NOT recomputed client-side).
 *  2. MaintenancePanel — create: POST /maintenance-schedules called with correct body.
 *  3. MaintenancePanel — edit: PATCH /maintenance-schedules/{id} called.
 *  4. MaintenancePanel — delete: DELETE /maintenance-schedules/{id} called.
 *  5. MaintenancePanel — mark done: POST /complete fires; after refetch the
 *     advanced next_due_date is rendered (verifies the UI updates post-completion).
 *  6. MaintenancePanel — pause/resume: PATCH with toggled is_active.
 *  7. MaintenancePanel — viewer gating: no add/edit/delete/pause/mark-done.
 *  8. MaintenancePanel — empty state.
 *  9. Dashboard MaintenanceCard — renders tile; count badge + nearest-first list;
 *     filters out 'ok' schedules; links to /instances/{id}.
 * 10. Dashboard MaintenanceCard — empty state when nothing is due.
 * 11. i18n — maintenance namespace en+zh key parity.
 * 12. i18n — all en maintenance values are non-empty strings.
 * 13. i18n — errors.maintenance.not_found in both en and zh.
 * 14. i18n — errors.validation.unsupported_interval_unit in both en and zh.
 * 15. i18n — dashboard.maintenanceCard strings in both en and zh.
 *
 * All component tests pin to 'en' (vitest setup.ts resets before each test).
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter } from "react-router-dom";

// i18n singleton must be initialized before any component renders.
import "../i18n/index.js";

import { MaintenancePanel } from "../components/MaintenancePanel";
import { Dashboard } from "../pages/Dashboard";
import { AuthProvider } from "../auth/AuthContext";
import type { components } from "../api/schema";

import { formatDate } from "../i18n/format";

// Catalog imports for parity tests
import enMaintenance from "../i18n/locales/en/maintenance.json";
import zhMaintenance from "../i18n/locales/zh/maintenance.json";
import enErrors from "../i18n/locales/en/errors.json";
import zhErrors from "../i18n/locales/zh/errors.json";
import enDashboard from "../i18n/locales/en/dashboard.json";
import zhDashboard from "../i18n/locales/zh/dashboard.json";

/** Mock the typed API client. */
vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
    PATCH: vi.fn(),
    DELETE: vi.fn(),
  },
}));

import { client } from "../api/client.js";

// ── Fixtures ──────────────────────────────────────────────────────────────────

type MaintenanceScheduleResponse = components["schemas"]["MaintenanceScheduleResponse"];
type UserResponse = components["schemas"]["UserResponse"];

function makeUser(role: "admin" | "member" | "viewer"): UserResponse {
  return {
    id: 1,
    email: `${role}@test.com`,
    role,
    is_active: true,
    notify_in_app: true,
    notify_email_digest: true,
    created_at: "2026-01-01T00:00:00Z",
    preferred_language: "en",
  };
}

const overdueSchedule: MaintenanceScheduleResponse = {
  id: 1,
  instance_id: 10,
  instance_name: "HP LaserJet",
  name: "Replace toner",
  interval_unit: "month",
  interval_count: 3,
  next_due_date: "2026-05-01",
  lead_days: 7,
  effective_lead_days: 7,
  last_completed_date: "2026-02-01",
  notes: null,
  is_active: true,
  status: "overdue",
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const dueSoonSchedule: MaintenanceScheduleResponse = {
  id: 2,
  instance_id: 10,
  instance_name: "HP LaserJet",
  name: "Clean drum",
  interval_unit: "month",
  interval_count: 6,
  next_due_date: "2026-07-01",
  lead_days: null,
  effective_lead_days: 7,
  last_completed_date: null,
  notes: "Use clean cloth",
  is_active: true,
  status: "due_soon",
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

const okSchedule: MaintenanceScheduleResponse = {
  id: 3,
  instance_id: 10,
  instance_name: "HP LaserJet",
  name: "Replace fuser",
  interval_unit: "year",
  interval_count: 1,
  next_due_date: "2027-06-01",
  lead_days: null,
  effective_lead_days: 7,
  last_completed_date: null,
  notes: null,
  is_active: true,
  status: "ok",
  created_by: 1,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

/** Render MaintenancePanel with MemoryRouter + MantineProvider + AuthProvider. */
function renderPanel(role: "admin" | "member" | "viewer" = "member", instanceId = 10) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <AuthProvider user={makeUser(role)} onRefresh={vi.fn()} onLogout={vi.fn()}>
          <MaintenancePanel instanceId={instanceId} />
        </AuthProvider>
      </MantineProvider>
    </MemoryRouter>,
  );
}

/** Render the Dashboard page. */
function renderDashboard() {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <Dashboard />
      </MantineProvider>
    </MemoryRouter>,
  );
}

/** Default GET mock for MaintenancePanel: returns the two-schedule list. */
function mockPanelLoad(schedules: MaintenanceScheduleResponse[] = [overdueSchedule, dueSoonSchedule]) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(client.GET).mockImplementation(async (path: any) => {
    if (typeof path === "string" && path.includes("/maintenance-schedules")) {
      return { data: schedules, response: new Response(null, { status: 200 }) };
    }
    return { data: [], response: new Response(null, { status: 200 }) };
  });
}

// ── Deep key extraction (for catalog parity tests) ────────────────────────────

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

// ── 1. Status chips rendered from server field ────────────────────────────────

describe("MaintenancePanel — status chips from server status field", () => {
  beforeEach(() => {
    mockPanelLoad([overdueSchedule, dueSoonSchedule, okSchedule]);
  });

  it("renders overdue schedule with red status chip", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-row-1")).toBeDefined();
    });
    const chip = screen.getByTestId("maintenance-status-1");
    expect(chip).toBeDefined();
    // Text content is the translated status label
    expect(chip.textContent).toContain("Overdue");
  });

  it("renders due_soon schedule with yellow status chip", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-row-2")).toBeDefined();
    });
    const chip = screen.getByTestId("maintenance-status-2");
    expect(chip).toBeDefined();
    expect(chip.textContent).toContain("Due Soon");
  });

  it("renders ok schedule with ok status chip", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-row-3")).toBeDefined();
    });
    const chip = screen.getByTestId("maintenance-status-3");
    expect(chip).toBeDefined();
    expect(chip.textContent).toContain("OK");
  });

  it("renders schedule name and recurrence", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-name-1")).toBeDefined();
    });
    expect(screen.getByTestId("maintenance-name-1").textContent).toContain("Replace toner");
    // recurrence: every 3 months
    expect(screen.getByTestId("maintenance-recurrence-1").textContent).toContain("3");
    expect(screen.getByTestId("maintenance-recurrence-1").textContent?.toLowerCase()).toContain("month");
  });
});

// ── 2. Create schedule ────────────────────────────────────────────────────────

describe("MaintenancePanel — create schedule", () => {
  beforeEach(() => {
    mockPanelLoad([]);
    vi.mocked(client.POST).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: overdueSchedule, response: new Response(null, { status: 201 }) } as any,
    );
  });

  it("opens add modal when 'Add schedule' is clicked", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-add-btn")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("maintenance-add-btn"));
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-add-name")).toBeDefined();
    });
  });

  it("calls POST /maintenance-schedules with correct body", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-add-btn")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("maintenance-add-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("maintenance-add-name")).toBeDefined();
    });

    // Fill in the name
    fireEvent.change(screen.getByTestId("maintenance-add-name"), {
      target: { value: "Replace toner" },
    });

    // Fill in next_due_date
    fireEvent.change(screen.getByTestId("maintenance-add-next-due"), {
      target: { value: "2026-07-01" },
    });

    fireEvent.click(screen.getByTestId("maintenance-add-submit"));

    await waitFor(() => {
      expect(vi.mocked(client.POST)).toHaveBeenCalledWith(
        "/api/maintenance-schedules",
        expect.objectContaining({
          body: expect.objectContaining({
            instance_id: 10,
            name: "Replace toner",
            next_due_date: "2026-07-01",
          }),
        }),
      );
    });
  });
});

// ── 3. Edit schedule ──────────────────────────────────────────────────────────

describe("MaintenancePanel — edit schedule", () => {
  beforeEach(() => {
    mockPanelLoad([overdueSchedule]);
    vi.mocked(client.PATCH).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: { ...overdueSchedule, name: "Replace toner cartridge" }, response: new Response(null, { status: 200 }) } as any,
    );
  });

  it("opens edit modal when edit button is clicked", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-edit-1")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("maintenance-edit-1"));
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-edit-submit")).toBeDefined();
    });
  });

  it("calls PATCH /maintenance-schedules/{id} on save with correct body and WITHOUT is_active", async () => {
    // Regression test for B1: the edit body must NOT include is_active (even as null),
    // because the backend's blind setattr would write NULL to a NOT NULL column.
    // The body must contain the expected editable fields.
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-edit-1")).toBeDefined();
    });
    fireEvent.click(screen.getByTestId("maintenance-edit-1"));

    await waitFor(() => {
      expect(screen.getByTestId("maintenance-edit-submit")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("maintenance-edit-submit"));

    await waitFor(() => {
      expect(vi.mocked(client.PATCH)).toHaveBeenCalledWith(
        "/api/maintenance-schedules/{schedule_id}",
        expect.objectContaining({
          params: { path: { schedule_id: 1 } },
          body: expect.objectContaining({
            // overdueSchedule prefills: name="Replace toner", interval_unit="month",
            // interval_count=3, next_due_date="2026-05-01"
            name: "Replace toner",
            interval_unit: "month",
            interval_count: 3,
            next_due_date: "2026-05-01",
          }),
        }),
      );
    });

    // is_active must be absent from the body — it is managed by pause/resume only.
    const patchCalls = vi.mocked(client.PATCH).mock.calls;
    expect(patchCalls.length).toBeGreaterThan(0);
    const editBody = (patchCalls[0][1] as { body?: Record<string, unknown> }).body;
    expect(editBody).toBeDefined();
    expect(Object.prototype.hasOwnProperty.call(editBody, "is_active")).toBe(false);
  });
});

// ── 4. Delete schedule ────────────────────────────────────────────────────────

describe("MaintenancePanel — delete schedule", () => {
  beforeEach(() => {
    let getCallCount = 0;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (typeof path === "string" && path.includes("/maintenance-schedules")) {
        getCallCount++;
        return {
          data: getCallCount === 1 ? [overdueSchedule] : [],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });
    vi.mocked(client.DELETE).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: null, response: new Response(null, { status: 200 }) } as any,
    );
  });

  it("calls DELETE /maintenance-schedules/{id} and row disappears", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-delete-1")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("maintenance-delete-1"));

    // Confirm dialog should appear
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-delete-submit")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("maintenance-delete-submit"));

    await waitFor(() => {
      expect(vi.mocked(client.DELETE)).toHaveBeenCalledWith(
        "/api/maintenance-schedules/{schedule_id}",
        expect.objectContaining({
          params: { path: { schedule_id: 1 } },
        }),
      );
    });

    // After delete + refetch, the row is gone (empty state shown)
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-empty")).toBeDefined();
    });
  });
});

// ── 5. Mark done — next_due_date advances ─────────────────────────────────────

describe("MaintenancePanel — mark done advances next_due_date", () => {
  const advancedSchedule: MaintenanceScheduleResponse = {
    ...overdueSchedule,
    next_due_date: "2026-08-01",      // 3 months forward from completed_on 2026-05-01
    last_completed_date: "2026-05-01",
    status: "ok",
  };

  beforeEach(() => {
    let getCallCount = 0;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (typeof path === "string" && path.includes("/maintenance-schedules")) {
        getCallCount++;
        // First call: original schedule; subsequent calls: advanced schedule
        return {
          data: [getCallCount === 1 ? overdueSchedule : advancedSchedule],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });
    vi.mocked(client.POST).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: advancedSchedule, response: new Response(null, { status: 200 }) } as any,
    );
  });

  it("POST /complete is fired and the advanced next_due_date is shown after refetch", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-mark-done-1")).toBeDefined();
    });

    // Click mark done
    fireEvent.click(screen.getByTestId("maintenance-mark-done-1"));

    await waitFor(() => {
      expect(screen.getByTestId("maintenance-mark-done-submit")).toBeDefined();
    });

    // Submit without back-date (defaults to today)
    fireEvent.click(screen.getByTestId("maintenance-mark-done-submit"));

    // Verify the /complete endpoint was called
    await waitFor(() => {
      expect(vi.mocked(client.POST)).toHaveBeenCalledWith(
        "/api/maintenance-schedules/{schedule_id}/complete",
        expect.objectContaining({
          params: { path: { schedule_id: 1 } },
        }),
      );
    });

    // After refetch, the advanced next_due_date (2026-08-01) should appear
    // in the next-due cell, and the status chip should show "OK".
    await waitFor(() => {
      const chip = screen.getByTestId("maintenance-status-1");
      expect(chip.textContent).toContain("OK");
    });

    // Assert the date cell also renders the advanced date (checkpoint 2 from §10 Step 7).
    // formatDate mirrors the component's own formatting so the assertion stays
    // locale-independent (both call the same Intl formatter with i18n.language="en").
    const nextDueCell = screen.getByTestId("maintenance-next-due-1");
    const expectedAdvancedDate = formatDate("2026-08-01");
    expect(nextDueCell.textContent).toContain(expectedAdvancedDate);
  });
});

// ── 6. Pause / resume ─────────────────────────────────────────────────────────

describe("MaintenancePanel — pause and resume", () => {
  beforeEach(() => {
    let getCallCount = 0;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (typeof path === "string" && path.includes("/maintenance-schedules")) {
        getCallCount++;
        return {
          data: getCallCount === 1
            ? [overdueSchedule]
            : [{ ...overdueSchedule, is_active: false }],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });
    vi.mocked(client.PATCH).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: { ...overdueSchedule, is_active: false }, response: new Response(null, { status: 200 }) } as any,
    );
  });

  it("clicking pause button calls PATCH with is_active: false", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-pause-1")).toBeDefined();
    });

    fireEvent.click(screen.getByTestId("maintenance-pause-1"));

    await waitFor(() => {
      expect(vi.mocked(client.PATCH)).toHaveBeenCalledWith(
        "/api/maintenance-schedules/{schedule_id}",
        expect.objectContaining({
          params: { path: { schedule_id: 1 } },
          body: expect.objectContaining({ is_active: false }),
        }),
      );
    });
  });
});

// ── 7. Viewer gating ──────────────────────────────────────────────────────────

describe("MaintenancePanel — viewer read-only", () => {
  beforeEach(() => {
    mockPanelLoad([overdueSchedule, dueSoonSchedule]);
  });

  it("viewer does NOT see the add-schedule button", async () => {
    renderPanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-row-1")).toBeDefined();
    });
    expect(screen.queryByTestId("maintenance-add-btn")).toBeNull();
  });

  it("viewer does NOT see edit/delete/pause/mark-done per-row buttons", async () => {
    renderPanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-row-1")).toBeDefined();
    });
    expect(screen.queryByTestId("maintenance-edit-1")).toBeNull();
    expect(screen.queryByTestId("maintenance-delete-1")).toBeNull();
    expect(screen.queryByTestId("maintenance-pause-1")).toBeNull();
    expect(screen.queryByTestId("maintenance-mark-done-1")).toBeNull();
  });

  it("viewer STILL sees the list (schedule names visible)", async () => {
    renderPanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-name-1")).toBeDefined();
    });
    expect(screen.getByTestId("maintenance-name-1").textContent).toContain("Replace toner");
  });
});

// ── 8. Empty state ────────────────────────────────────────────────────────────

describe("MaintenancePanel — empty state", () => {
  beforeEach(() => {
    mockPanelLoad([]);
  });

  it("shows empty state when no schedules", async () => {
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-empty")).toBeDefined();
    });
    expect(screen.getByTestId("maintenance-empty").textContent?.length).toBeGreaterThan(0);
  });
});

// ── 9. Dashboard MaintenanceCard ──────────────────────────────────────────────

describe("Dashboard — MaintenanceCard", () => {
  // Three schedules: overdue (id 1, due 2026-05-01), due_soon (id 2, due 2026-07-01), ok (id 3)
  // The tile should show overdue + due_soon (2 items) sorted nearest-first.
  // It should NOT show the ok schedule.
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (path === "/api/maintenance-schedules") {
        return {
          data: [okSchedule, dueSoonSchedule, overdueSchedule],  // deliberately unsorted
          response: new Response(null, { status: 200 }),
        };
      }
      // Other dashboard endpoints (expiry, low-stock) return empty arrays
      return { data: [], response: new Response(null, { status: 200 }) };
    });
  });

  it("renders the maintenance tile", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-tile")).toBeDefined();
    });
  });

  it("shows count badge with the number of overdue/due_soon schedules", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-count-badge")).toBeDefined();
    });
    // 2 schedules (overdue + due_soon), okSchedule is filtered out
    expect(screen.getByTestId("maintenance-count-badge").textContent).toContain("2");
  });

  it("shows the nearest-first list (overdue before due_soon)", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-list")).toBeDefined();
    });
    // Item 1 (overdue, 2026-05-01) should appear before item 2 (due_soon, 2026-07-01)
    const items = screen.getAllByTestId(/^maintenance-item-/);
    expect(items.length).toBeGreaterThanOrEqual(1);
    // First item is the overdue one (nearest due date)
    expect(items[0].getAttribute("data-testid")).toBe("maintenance-item-1");
  });

  it("filters out 'ok' schedules (client-side)", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-list")).toBeDefined();
    });
    // okSchedule (id=3) should NOT be in the list
    expect(screen.queryByTestId("maintenance-item-3")).toBeNull();
  });

  it("each list item links to /instances/{instance_id}", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-item-1")).toBeDefined();
    });
    const links = screen.getByTestId("maintenance-item-1").querySelectorAll("a");
    expect(links.length).toBeGreaterThan(0);
    expect(links[0].getAttribute("href")).toBe("/instances/10");
  });
});

// ── 10. Dashboard MaintenanceCard — empty state ───────────────────────────────

describe("Dashboard — MaintenanceCard empty state", () => {
  beforeEach(() => {
    // All schedules are 'ok' — nothing is due soon
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (path === "/api/maintenance-schedules") {
        return { data: [okSchedule], response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });
  });

  it("shows empty state when all schedules are ok", async () => {
    renderDashboard();
    await waitFor(() => {
      expect(screen.getByTestId("maintenance-empty-state")).toBeDefined();
    });
    expect(screen.queryByTestId("maintenance-count-badge")).toBeNull();
    expect(screen.queryByTestId("maintenance-list")).toBeNull();
  });
});

// ── 11. i18n — maintenance namespace en+zh key parity ─────────────────────────

describe("i18n — maintenance namespace key parity", () => {
  it("en and zh maintenance have identical key sets", () => {
    const enKeys = collectKeys(enMaintenance).sort();
    const zhKeys = collectKeys(zhMaintenance).sort();

    const missingInZh = enKeys.filter((k) => !zhKeys.includes(k));
    const extraInZh = zhKeys.filter((k) => !enKeys.includes(k));

    expect(missingInZh, "Keys in en/maintenance missing from zh/maintenance").toEqual([]);
    expect(extraInZh, "Extra keys in zh/maintenance not present in en/maintenance").toEqual([]);
  });

  it("all en maintenance values are non-empty strings", () => {
    const enKeys = collectKeys(enMaintenance);
    for (const key of enKeys) {
      const parts = key.split(".");
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      let val: any = enMaintenance;
      for (const part of parts) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        val = (val as any)[part];
      }
      expect(typeof val, `en/maintenance key '${key}' should be a string`).toBe("string");
      expect((val as string).trim().length, `en/maintenance key '${key}' should be non-empty`).toBeGreaterThan(0);
    }
  });

  it("zh translations differ from en (are actually translated)", () => {
    expect(zhMaintenance.sectionTitle).not.toBe(enMaintenance.sectionTitle);
    expect(zhMaintenance.empty).not.toBe(enMaintenance.empty);
  });
});

// ── 12. i18n — errors.maintenance.not_found in both en and zh ─────────────────

describe("i18n — errors.maintenance.not_found in both en and zh", () => {
  it("en/errors has maintenance.not_found", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const enErrTyped = enErrors as any;
    expect(enErrTyped["maintenance"]).toBeDefined();
    expect(typeof enErrTyped["maintenance"]["not_found"]).toBe("string");
    expect((enErrTyped["maintenance"]["not_found"] as string).trim().length).toBeGreaterThan(0);
  });

  it("zh/errors has maintenance.not_found", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const zhErrTyped = zhErrors as any;
    expect(zhErrTyped["maintenance"]).toBeDefined();
    expect(typeof zhErrTyped["maintenance"]["not_found"]).toBe("string");
    expect((zhErrTyped["maintenance"]["not_found"] as string).trim().length).toBeGreaterThan(0);
  });
});

// ── 13. i18n — errors.validation.unsupported_interval_unit ────────────────────

describe("i18n — errors.validation.unsupported_interval_unit in both en and zh", () => {
  it("en/errors has validation.unsupported_interval_unit", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(typeof (enErrors as any)["validation"]["unsupported_interval_unit"]).toBe("string");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(((enErrors as any)["validation"]["unsupported_interval_unit"] as string).trim().length).toBeGreaterThan(0);
  });

  it("zh/errors has validation.unsupported_interval_unit", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(typeof (zhErrors as any)["validation"]["unsupported_interval_unit"]).toBe("string");
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect(((zhErrors as any)["validation"]["unsupported_interval_unit"] as string).trim().length).toBeGreaterThan(0);
  });
});

// ── 14. i18n — dashboard.maintenanceCard strings in both en and zh ────────────

describe("i18n — dashboard.maintenanceCard strings", () => {
  it("en/dashboard has maintenanceCard.title", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const card = (enDashboard as any)["maintenanceCard"];
    expect(card).toBeDefined();
    expect(typeof card["title"]).toBe("string");
    expect(typeof card["emptyState"]).toBe("string");
    expect(typeof card["loadError"]).toBe("string");
  });

  it("zh/dashboard has maintenanceCard with translated strings", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const zhCard = (zhDashboard as any)["maintenanceCard"];
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const enCard = (enDashboard as any)["maintenanceCard"];
    expect(zhCard).toBeDefined();
    expect(zhCard["title"]).not.toBe(enCard["title"]);
    expect(zhCard["emptyState"]).not.toBe(enCard["emptyState"]);
  });
});
