/**
 * Notification hygiene — Step 2 frontend tests.
 *
 * Covers (per review-notes/notif-hygiene-design.md §4):
 *
 * 1. NotificationBell:
 *    a. "Clear all" calls POST /api/notifications/dismiss-all then refetches
 *       count + list.
 *    b. Per-row dismiss calls POST /api/notifications/{id}/dismiss with the
 *       right id, then refetches count + list.
 *    c. The dismiss control renders for read rows too (not gated on unread).
 *
 * 2. /notifications page:
 *    a. "Clear all" calls dismiss-all then reloads the list.
 *    b. Per-row dismiss calls the dismiss endpoint with the right id, then
 *       reloads the list.
 *    c. The dismiss control renders for read rows too.
 *
 * Conventions: vitest + Testing Library, mock typed client, pinned to "en".
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { NotificationBell } from "../components/NotificationBell.js";
import { Notifications } from "../pages/Notifications.js";
import i18n from "../i18n/index.js";

// ── Mock client ───────────────────────────────────────────────────────────────

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

const notifUnread = {
  id: 1,
  source: "best_before",
  subject_type: "instance",
  subject_id: 42,
  message_code: "reminder.best_before",
  params: { name: "Milk", date: "2026-06-25", days_remaining: 5 },
  offset_days: null,
  created_at: "2026-06-20T08:00:00Z",
  read_at: null,
};

const notifRead = {
  id: 5,
  source: "best_before",
  subject_type: "instance",
  subject_id: 99,
  message_code: "reminder.best_before",
  params: { name: "Yogurt", date: "2026-06-22", days_remaining: 2 },
  offset_days: null,
  created_at: "2026-06-20T07:00:00Z",
  read_at: "2026-06-20T09:00:00Z",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

function renderBell() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <MantineProvider>
        <NotificationBell />
      </MantineProvider>
    </MemoryRouter>,
  );
}

function renderNotificationsPage() {
  return render(
    <MemoryRouter initialEntries={["/notifications"]}>
      <MantineProvider>
        <Routes>
          <Route path="/notifications" element={<Notifications />} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

// ── Tests: NotificationBell ───────────────────────────────────────────────────

describe("NotificationBell — clear all", () => {
  it("clicking 'Clear all' calls dismiss-all then refetches count + list", async () => {
    let dismissAllCalled = false;
    let countCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        countCallCount += 1;
        return { data: { count: dismissAllCalled ? 0 : 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return {
          data: dismissAllCalled ? [] : [notifUnread],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/dismiss-all") {
        dismissAllCalled = true;
        return { data: { dismissed: 1 }, response: new Response(null, { status: 200 }) } as AnyResult;
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    await act(async () => {
      renderBell();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("dismiss-all-btn")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("dismiss-all-btn"));
    });

    await waitFor(() => {
      expect(client.POST).toHaveBeenCalledWith("/api/notifications/dismiss-all");
    });

    await waitFor(() => {
      expect(dismissAllCalled).toBe(true);
      expect(countCallCount).toBeGreaterThanOrEqual(2);
    });

    await waitFor(() => {
      expect(screen.getByTestId("bell-empty")).toBeDefined();
    });
  });
});

describe("NotificationBell — per-row dismiss", () => {
  it("clicking a row's dismiss button calls the dismiss endpoint with the right id then refetches", async () => {
    let dismissed = false;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: dismissed ? 0 : 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return {
          data: dismissed ? [] : [notifUnread],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/{notification_id}/dismiss") {
        dismissed = true;
        return {
          data: { ...notifUnread, read_at: null },
          response: new Response(null, { status: 200 }),
        } as AnyResult;
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    await act(async () => {
      renderBell();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("dismiss-btn-1")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("dismiss-btn-1"));
    });

    await waitFor(() => {
      expect(client.POST).toHaveBeenCalledWith(
        "/api/notifications/{notification_id}/dismiss",
        expect.objectContaining({
          params: expect.objectContaining({ path: { notification_id: 1 } }),
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("bell-empty")).toBeDefined();
    });
  });

  it("dismiss control renders for read rows too (not gated on unread)", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 0 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [notifRead], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    await act(async () => {
      renderBell();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      // Read row has no mark-read button, but the dismiss control must exist.
      expect(screen.queryByTestId("mark-read-btn-5")).toBeNull();
      expect(screen.getByTestId("dismiss-btn-5")).toBeDefined();
    });
  });
});

// ── Tests: /notifications page ────────────────────────────────────────────────

describe("/notifications page — clear all", () => {
  it("clicking 'Clear all' calls dismiss-all then reloads the list", async () => {
    let dismissAllCalled = false;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return {
          data: dismissAllCalled ? [] : [notifUnread],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/dismiss-all") {
        dismissAllCalled = true;
        return { data: { dismissed: 1 }, response: new Response(null, { status: 200 }) } as AnyResult;
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-1")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("page-dismiss-all-btn"));
    });

    await waitFor(() => {
      expect(client.POST).toHaveBeenCalledWith("/api/notifications/dismiss-all");
    });

    await waitFor(() => {
      expect(screen.getByTestId("notifications-empty")).toBeDefined();
    });
  });
});

describe("/notifications page — per-row dismiss", () => {
  it("clicking a row's dismiss button calls the dismiss endpoint with the right id then reloads", async () => {
    let dismissed = false;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return {
          data: dismissed ? [] : [notifUnread],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/{notification_id}/dismiss") {
        dismissed = true;
        return {
          data: { ...notifUnread, read_at: null },
          response: new Response(null, { status: 200 }),
        } as AnyResult;
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("page-dismiss-btn-1")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("page-dismiss-btn-1"));
    });

    await waitFor(() => {
      expect(client.POST).toHaveBeenCalledWith(
        "/api/notifications/{notification_id}/dismiss",
        expect.objectContaining({
          params: expect.objectContaining({ path: { notification_id: 1 } }),
        }),
      );
    });

    await waitFor(() => {
      expect(screen.getByTestId("notifications-empty")).toBeDefined();
    });
  });

  it("dismiss control renders for read rows too (not gated on unread)", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return { data: [notifRead], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-5")).toBeDefined();
    });

    // Read row has no mark-read button, but the dismiss control must exist.
    expect(screen.queryByTestId("page-mark-read-btn-5")).toBeNull();
    expect(screen.getByTestId("page-dismiss-btn-5")).toBeDefined();
  });
});
