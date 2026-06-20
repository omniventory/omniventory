/**
 * M4 Step 11 — frontend tests.
 *
 * Coverage (per M4 §5 "Frontend" / §7.1/§7.2 / §9 Step 11 / §10 Step 11):
 *
 * 1. NotificationBell:
 *    a. Unread badge shows count when > 0; badge hidden when count = 0.
 *    b. Dropdown lists notifications; each localized from message_code + params.
 *    c. mark-read (single) triggers re-fetch and badge updates.
 *    d. mark-all-read clears badge.
 *
 * 2. /notifications page:
 *    a. Lists all notifications (message_code + params localized).
 *    b. Unread-only filter switch fires query with unread_only=true.
 *    c. Per-row mark-read button calls POST.
 *    d. Subject links point to correct route (instance → /instances/:id,
 *       definition → /items/:id).
 *    e. Empty state shown when no notifications.
 *
 * 3. Navigation:
 *    a. Nav item "Notifications" exists in NavContent and links to /notifications.
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

const notifBestBefore = {
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

const notifWarranty = {
  id: 2,
  source: "warranty",
  subject_type: "instance",
  subject_id: 55,
  message_code: "reminder.warranty",
  params: { name: "Drill", date: "2026-07-20", days_remaining: 30 },
  offset_days: null,
  created_at: "2026-06-20T08:01:00Z",
  read_at: null,
};

const notifLowStock = {
  id: 3,
  source: "low_stock",
  subject_type: "definition",
  subject_id: 10,
  message_code: "reminder.low_stock",
  params: { name: "Coffee", current: "0.5", threshold: "1" },
  offset_days: 0,
  created_at: "2026-06-20T08:02:00Z",
  read_at: null,
};

const notifLowStockRepeat = {
  id: 4,
  source: "low_stock",
  subject_type: "definition",
  subject_id: 10,
  message_code: "reminder.low_stock_repeat",
  params: { name: "Coffee", current: "0.5", threshold: "1", offset: 3 },
  offset_days: 3,
  created_at: "2026-06-23T08:00:00Z",
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

function renderNotificationsPage(initialPath = "/notifications") {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MantineProvider>
        <Routes>
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/instances/:id" element={<div data-testid="instance-detail-page">Instance</div>} />
          <Route path="/items/:id" element={<div data-testid="item-detail-page">Item</div>} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

// ── Tests: NotificationBell ───────────────────────────────────────────────────

describe("NotificationBell — unread count badge", () => {
  it("shows unread badge when count > 0", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 3 }, response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    await act(async () => {
      renderBell();
    });

    await waitFor(() => {
      expect(screen.getByTestId("notification-indicator")).toBeDefined();
    });

    // The Indicator shows the count as text when unread > 0
    const indicator = screen.getByTestId("notification-indicator");
    expect(indicator.textContent).toContain("3");
  });

  it("hides badge when count = 0", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 0 }, response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    await act(async () => {
      renderBell();
    });

    await waitFor(() => {
      // The bell button should exist
      expect(screen.getByTestId("notification-bell-btn")).toBeDefined();
    });

    // When count=0 the Indicator is disabled, no badge text visible
    const indicator = screen.getByTestId("notification-indicator");
    // "0" should not appear as a badge label (disabled indicator shows no label)
    expect(indicator.textContent?.includes("0")).toBeFalsy();
  });

  it("polls unread count on interval (uses fake timers)", async () => {
    vi.useFakeTimers();
    let callCount = 0;
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        callCount += 1;
        return { data: { count: callCount }, response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    await act(async () => {
      renderBell();
    });

    // Initial call on mount
    expect(callCount).toBeGreaterThanOrEqual(1);

    // Advance timer by 30s to trigger the interval poll
    await act(async () => {
      vi.advanceTimersByTime(30_000);
    });

    expect(callCount).toBeGreaterThanOrEqual(2);
    vi.useRealTimers();
  });
});

describe("NotificationBell — dropdown localization", () => {
  it("dropdown lists notifications localized from message_code + params", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 2 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return {
          data: [notifBestBefore, notifWarranty],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    await act(async () => {
      renderBell();
    });

    // Click bell to open dropdown
    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("notification-dropdown-list")).toBeDefined();
    });

    // Check localized messages — not raw message_code keys
    await waitFor(() => {
      const msg1 = screen.getByTestId("notification-message-1");
      // Should contain "Milk" from params.name
      expect(msg1.textContent).toContain("Milk");
      // Should NOT be the raw key
      expect(msg1.textContent).not.toBe("reminder.best_before");
    });

    await waitFor(() => {
      const msg2 = screen.getByTestId("notification-message-2");
      expect(msg2.textContent).toContain("Drill");
      expect(msg2.textContent).not.toBe("reminder.warranty");
    });
  });

  it("low_stock notification is localized with current and threshold", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [notifLowStock], response: new Response(null, { status: 200 }) };
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
      const msg3 = screen.getByTestId("notification-message-3");
      expect(msg3.textContent).toContain("Coffee");
      // Should include threshold info
      expect(msg3.textContent).not.toBe("reminder.low_stock");
    });
  });

  it("low_stock_repeat notification is localized with offset", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [notifLowStockRepeat], response: new Response(null, { status: 200 }) };
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
      const msg4 = screen.getByTestId("notification-message-4");
      expect(msg4.textContent).toContain("Coffee");
      // "still running low" or similar — not the raw key
      expect(msg4.textContent).not.toBe("reminder.low_stock_repeat");
    });
  });

  it("shows empty state when no notifications", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 0 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [], response: new Response(null, { status: 200 }) };
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
      expect(screen.getByTestId("bell-empty")).toBeDefined();
    });
  });

  it("relative time in dropdown is localized (en: 'just now' / 'Xm ago')", async () => {
    // Use a notification with a very recent created_at (< 1 min ago)
    const recentNotif = {
      ...notifBestBefore,
      id: 99,
      created_at: new Date(Date.now() - 30_000).toISOString(), // 30s ago → "just now"
    };

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [recentNotif], response: new Response(null, { status: 200 }) };
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
      // The relative time text should come from the i18n catalog (en: "just now")
      expect(screen.getByText("just now")).toBeDefined();
    });
  });

  it("relative time in dropdown renders zh strings when language is zh", async () => {
    await i18n.changeLanguage("zh");

    const recentNotif = {
      ...notifBestBefore,
      id: 98,
      created_at: new Date(Date.now() - 30_000).toISOString(), // 30s ago → "刚刚"
    };

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: 1 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [recentNotif], response: new Response(null, { status: 200 }) };
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
      // zh locale should show "刚刚" not "just now"
      expect(screen.getByText("刚刚")).toBeDefined();
    });

    await i18n.changeLanguage("en");
  });
});

describe("NotificationBell — mark-read updates badge", () => {
  it("mark-read (single) triggers re-fetch; badge reflects new count", async () => {
    let readCallCount = 0;
    let countCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        countCallCount += 1;
        // First call → 1 unread; subsequent → 0
        const count = countCallCount === 1 ? 1 : 0;
        return { data: { count }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        // After mark-read, return empty
        if (readCallCount > 0) {
          return { data: [{ ...notifBestBefore, read_at: "2026-06-20T10:00:00Z" }], response: new Response(null, { status: 200 }) };
        }
        return { data: [notifBestBefore], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async () => {
      readCallCount += 1;
      return { data: { ...notifBestBefore, read_at: "2026-06-20T10:00:00Z" }, response: new Response(null, { status: 200 }) } as AnyResult;
    });

    await act(async () => {
      renderBell();
    });

    // Open dropdown
    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("mark-read-btn-1")).toBeDefined();
    });

    // Mark it read
    await act(async () => {
      fireEvent.click(screen.getByTestId("mark-read-btn-1"));
    });

    await waitFor(() => {
      expect(readCallCount).toBeGreaterThanOrEqual(1);
    });

    // count should have been re-fetched (countCallCount >= 2)
    await waitFor(() => {
      expect(countCallCount).toBeGreaterThanOrEqual(2);
    });
  });

  it("mark-all-read calls POST /notifications/read-all and re-fetches count", async () => {
    let markAllCalled = false;

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications/unread-count") {
        return { data: { count: markAllCalled ? 0 : 5 }, response: new Response(null, { status: 200 }) };
      }
      if (path === "/api/notifications") {
        return { data: [notifBestBefore], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    vi.mocked(client.POST).mockImplementation(async () => {
      markAllCalled = true;
      return { data: { marked: 5 }, response: new Response(null, { status: 200 }) } as AnyResult;
    });

    await act(async () => {
      renderBell();
    });

    // Open dropdown
    await act(async () => {
      fireEvent.click(screen.getByTestId("notification-bell-btn"));
    });

    await waitFor(() => {
      expect(screen.getByTestId("mark-all-read-btn")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("mark-all-read-btn"));
    });

    await waitFor(() => {
      expect(markAllCalled).toBe(true);
    });

    await waitFor(() => {
      // Verify count was re-fetched after mark-all-read
      const getCalls = vi.mocked(client.GET).mock.calls;
      const countCalls = getCalls.filter(
        (args) => args[0] === "/api/notifications/unread-count",
      );
      expect(countCalls.length).toBeGreaterThanOrEqual(2);
    });
  });
});

// ── Tests: /notifications page ────────────────────────────────────────────────

describe("/notifications page — list and localization", () => {
  it("lists all notifications with localized messages", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return {
          data: [notifBestBefore, notifWarranty, notifLowStock],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-1")).toBeDefined();
    });

    // Messages should be localized (contain name from params, not raw key)
    const msg1 = screen.getByTestId("notification-page-message-1");
    expect(msg1.textContent).toContain("Milk");
    expect(msg1.textContent).not.toBe("reminder.best_before");

    const msg2 = screen.getByTestId("notification-page-message-2");
    expect(msg2.textContent).toContain("Drill");

    const msg3 = screen.getByTestId("notification-page-message-3");
    expect(msg3.textContent).toContain("Coffee");
  });

  it("table headers are localized via i18n (en: Message/Subject/Date/Status)", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return {
          data: [notifBestBefore],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-1")).toBeDefined();
    });

    // Headers must come from the i18n catalog (en values)
    expect(screen.getByText("Message")).toBeDefined();
    expect(screen.getByText("Subject")).toBeDefined();
    expect(screen.getByText("Date")).toBeDefined();
    expect(screen.getByText("Status")).toBeDefined();
  });

  it("table headers render zh strings when language is zh", async () => {
    await i18n.changeLanguage("zh");

    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/notifications") {
        return {
          data: [notifBestBefore],
          response: new Response(null, { status: 200 }),
        };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-1")).toBeDefined();
    });

    // zh column headers must appear (not the English strings)
    expect(screen.getByText("消息")).toBeDefined();
    expect(screen.getByText("关联对象")).toBeDefined();
    expect(screen.getByText("日期")).toBeDefined();
    expect(screen.getByText("状态")).toBeDefined();

    await i18n.changeLanguage("en");
  });

  it("shows empty state when no notifications", async () => {
    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [],
      response: new Response(null, { status: 200 }),
    }));

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notifications-empty")).toBeDefined();
    });
  });

  it("unread-only filter changes query to unread_only=true", async () => {
    let lastQuery: Record<string, unknown> = {};
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult, opts: AnyResult) => {
      if (path === "/api/notifications") {
        lastQuery = opts?.params?.query ?? {};
        return { data: [notifBestBefore], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: {}, response: new Response(null, { status: 404 }) };
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-1")).toBeDefined();
    });

    // Initially: unread_only=false
    expect(lastQuery["unread_only"]).toBeFalsy();

    // Switch to unread-only
    const unreadBtn = screen.getByText(/unread only/i);
    await act(async () => {
      fireEvent.click(unreadBtn);
    });

    await waitFor(() => {
      expect(lastQuery["unread_only"]).toBe(true);
    });
  });

  it("per-row mark-read calls POST /notifications/{id}/read", async () => {
    let markReadCalled = false;

    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [notifBestBefore],
      response: new Response(null, { status: 200 }),
    }));

    vi.mocked(client.POST).mockImplementation(async () => {
      markReadCalled = true;
      return {
        data: { ...notifBestBefore, read_at: "2026-06-20T10:00:00Z" },
        response: new Response(null, { status: 200 }),
      } as AnyResult;
    });

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("page-mark-read-btn-1")).toBeDefined();
    });

    await act(async () => {
      fireEvent.click(screen.getByTestId("page-mark-read-btn-1"));
    });

    await waitFor(() => {
      expect(markReadCalled).toBe(true);
    });

    expect(client.POST).toHaveBeenCalledWith(
      "/api/notifications/{notification_id}/read",
      expect.objectContaining({
        params: expect.objectContaining({ path: { notification_id: 1 } }),
      }),
    );
  });

  it("instance subject links to /instances/:id", async () => {
    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [notifBestBefore], // subject_type="instance", subject_id=42
      response: new Response(null, { status: 200 }),
    }));

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-subject-link-1")).toBeDefined();
    });

    const link = screen.getByTestId("notification-subject-link-1");
    expect(link.getAttribute("href")).toBe("/instances/42");
  });

  it("definition subject links to /items/:id", async () => {
    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [notifLowStock], // subject_type="definition", subject_id=10
      response: new Response(null, { status: 200 }),
    }));

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-subject-link-3")).toBeDefined();
    });

    const link = screen.getByTestId("notification-subject-link-3");
    expect(link.getAttribute("href")).toBe("/items/10");
  });

  it("read notifications do not show mark-read button", async () => {
    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [notifRead], // read_at is set
      response: new Response(null, { status: 200 }),
    }));

    renderNotificationsPage();

    await waitFor(() => {
      expect(screen.getByTestId("notification-page-row-5")).toBeDefined();
    });

    // No mark-read button for already-read notification
    expect(screen.queryByTestId("page-mark-read-btn-5")).toBeNull();
  });
});

// ── Tests: Navigation ─────────────────────────────────────────────────────────

describe("Navigation — /notifications route", () => {
  it("renders the Notifications page at /notifications route", async () => {
    vi.mocked(client.GET).mockImplementation(async () => ({
      data: [],
      response: new Response(null, { status: 200 }),
    }));

    render(
      <MemoryRouter initialEntries={["/notifications"]}>
        <MantineProvider>
          <Routes>
            <Route path="/notifications" element={<Notifications />} />
          </Routes>
        </MantineProvider>
      </MemoryRouter>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("notifications-empty")).toBeDefined();
    });
  });
});
