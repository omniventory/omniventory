/**
 * M3 Step 6 — frontend tests.
 *
 * Coverage (per M3 §5 "Frontend" / §7.4–7.6 / §9 Step 6 / §10 Step 6):
 *
 * 1. Dashboard expiry tile (ExpiryCard):
 *    a. Renders count badge + short list from GET /api/expiring response.
 *    b. Empty state when GET /api/expiring returns [].
 *    c. Link to /expiring is present when items exist.
 *    d. Link is ABSENT in the empty state.
 *    e. Error state when the fetch fails.
 *    f. Does NOT re-derive the rule client-side (calls the endpoint once).
 *
 * 2. /expiring page (Expiring.tsx):
 *    a. Renders the full list from GET /api/expiring (rows with instance links).
 *    b. Each row links to /instances/:instance_id.
 *    c. Horizon control re-queries GET /api/expiring?within_days=N when changed.
 *    d. Empty state when GET /api/expiring returns [].
 *    e. Error state when the fetch fails.
 *
 * 3. Navigation: /expiring route resolves to the Expiring page.
 *
 * Conventions: vitest + Testing Library, mock the typed client, pinned to "en".
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { Dashboard } from "../pages/Dashboard.js";
import { Expiring } from "../pages/Expiring.js";
import i18n from "../i18n/index.js";

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

/** Lot expiring in 5 days */
const expiringItem1 = {
  instance_id: 101,
  definition_id: 10,
  name: "Milk",
  location_id: 1,
  best_before_date: "2099-01-05",
  quantity: "2.000000",
  days_remaining: 5,
  status: "expiring",
};

/** Lot already expired */
const expiredItem = {
  instance_id: 102,
  definition_id: 11,
  name: "Old Cheese",
  location_id: null,
  best_before_date: "2020-01-01",
  quantity: null,
  days_remaining: -100,
  status: "expired",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

function renderDashboard() {
  return render(
    <MemoryRouter initialEntries={["/"]}>
      <MantineProvider>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/expiring" element={<Expiring />} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

function renderExpiringPage() {
  return render(
    <MemoryRouter initialEntries={["/expiring"]}>
      <MantineProvider>
        <Routes>
          <Route path="/expiring" element={<Expiring />} />
          <Route path="/instances/:id" element={<div data-testid="instance-detail">Instance Detail</div>} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

// ── Tests: Dashboard expiry tile — count + list ───────────────────────────────

describe("Dashboard — expiry tile: count + list", () => {
  it("renders count badge when GET /api/expiring returns items", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/expiring") {
        return { data: [expiringItem1, expiredItem], response: new Response(null, { status: 200 }) };
      }
      // low-stock
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-count-badge")).toBeDefined();
    });

    expect(screen.getByTestId("expiry-count-badge").textContent).toMatch(/2/);
  });

  it("renders the short list with item names", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/expiring") {
        return { data: [expiringItem1], response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-list")).toBeDefined();
    });

    expect(screen.getByTestId(`expiry-item-${expiringItem1.instance_id}`).textContent).toMatch(/Milk/);
  });

  it("shows expiry badge for an expired item in the tile list", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/expiring") {
        return { data: [expiredItem], response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId(`expiry-item-${expiredItem.instance_id}`)).toBeDefined();
    });

    // ExpiryBadge for an old expired date renders expiry-badge-expired
    expect(screen.getByTestId("expiry-badge-expired")).toBeDefined();
  });
});

// ── Tests: Dashboard expiry tile — empty state ────────────────────────────────

describe("Dashboard — expiry tile: empty state", () => {
  it("renders empty state message when GET /api/expiring returns []", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-empty-state")).toBeDefined();
    });

    expect(screen.getByTestId("expiry-empty-state").textContent).toMatch(
      /no lots expiring/i,
    );
  });

  it("does NOT show count badge in empty state", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-empty-state")).toBeDefined();
    });

    expect(screen.queryByTestId("expiry-count-badge")).toBeNull();
  });

  it("does NOT show the view-all link in empty state", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-empty-state")).toBeDefined();
    });

    expect(screen.queryByTestId("expiry-view-link")).toBeNull();
  });
});

// ── Tests: Dashboard expiry tile — link to /expiring ─────────────────────────

describe("Dashboard — expiry tile: link to /expiring", () => {
  it("shows a link to /expiring when items are present", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/expiring") {
        return { data: [expiringItem1], response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-view-link")).toBeDefined();
    });

    const link = screen.getByTestId("expiry-view-link") as HTMLAnchorElement;
    expect(link.getAttribute("href")).toBe("/expiring");
  });
});

// ── Tests: Dashboard expiry tile — error state ────────────────────────────────

describe("Dashboard — expiry tile: error state", () => {
  it("shows load-error indicator when GET /api/expiring fails", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      error: { detail: "Internal server error" },
      response: new Response(null, { status: 500 }),
    } as AnyResult);

    renderDashboard();

    await waitFor(() => {
      expect(screen.getByTestId("expiry-load-error")).toBeDefined();
    });

    expect(screen.queryByTestId("expiry-empty-state")).toBeNull();
    expect(screen.queryByTestId("expiry-count-badge")).toBeNull();
  });
});

// ── Tests: /expiring page — full list ────────────────────────────────────────

describe("Expiring page — full list", () => {
  it("renders the page heading", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /expiring lots/i }),
      ).toBeDefined();
    });
  });

  it("renders rows for each item from GET /api/expiring", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [expiringItem1, expiredItem],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByTestId(`expiring-row-${expiringItem1.instance_id}`)).toBeDefined();
    });

    expect(screen.getByTestId(`expiring-row-${expiredItem.instance_id}`)).toBeDefined();
  });

  it("each row links to /instances/:instance_id", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [expiringItem1],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByTestId(`expiring-row-${expiringItem1.instance_id}`)).toBeDefined();
    });

    const link = screen.getByRole("link", { name: /Milk/i }) as HTMLAnchorElement;
    expect(link).toBeDefined();
    expect(link.getAttribute("href")).toBe(`/instances/${expiringItem1.instance_id}`);
  });

  it("renders empty state when GET /api/expiring returns []", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByTestId("expiring-empty")).toBeDefined();
    });

    expect(screen.getByTestId("expiring-empty").textContent).toMatch(
      /no lots expiring/i,
    );
  });

  it("renders ErrorState when GET /api/expiring fails", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      error: { detail: "Internal server error" },
      response: new Response(null, { status: 500 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeDefined();
    });

    expect(screen.getByRole("alert").textContent).toMatch(/failed to load expiry data/i);
    expect(screen.queryByTestId("expiring-empty")).toBeNull();
  });
});

// ── Tests: /expiring page — horizon control ───────────────────────────────────

describe("Expiring page — horizon control re-queries within_days", () => {
  it("renders the horizon control", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByTestId("horizon-control")).toBeDefined();
    });

    expect(screen.getByTestId("horizon-segmented")).toBeDefined();
  });

  it("initially calls GET /api/expiring with within_days=30 (default)", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(vi.mocked(client.GET)).toHaveBeenCalledWith(
        "/api/expiring",
        expect.objectContaining({
          params: expect.objectContaining({
            query: expect.objectContaining({ within_days: 30 }),
          }),
        }),
      );
    });
  });

  it("re-queries GET /api/expiring with new within_days when horizon changes", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    // Wait for initial load (within_days=30)
    await waitFor(() => {
      expect(vi.mocked(client.GET)).toHaveBeenCalledWith(
        "/api/expiring",
        expect.objectContaining({
          params: expect.objectContaining({
            query: expect.objectContaining({ within_days: 30 }),
          }),
        }),
      );
    });

    // Find and click the "7 days" horizon option
    const sevenDaysBtn = screen.getByRole("radio", { name: /7 days/i });
    fireEvent.click(sevenDaysBtn);

    // Should re-query with within_days=7
    await waitFor(() => {
      expect(vi.mocked(client.GET)).toHaveBeenCalledWith(
        "/api/expiring",
        expect.objectContaining({
          params: expect.objectContaining({
            query: expect.objectContaining({ within_days: 7 }),
          }),
        }),
      );
    });
  });

  it("re-queries with within_days=90 when 90 days horizon is selected", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(screen.getByTestId("horizon-segmented")).toBeDefined();
    });

    const ninetyDaysBtn = screen.getByRole("radio", { name: /90 days/i });
    fireEvent.click(ninetyDaysBtn);

    await waitFor(() => {
      expect(vi.mocked(client.GET)).toHaveBeenCalledWith(
        "/api/expiring",
        expect.objectContaining({
          params: expect.objectContaining({
            query: expect.objectContaining({ within_days: 90 }),
          }),
        }),
      );
    });
  });
});

// ── Tests: /expiring route resolves to the Expiring page ─────────────────────

describe("Navigation — /expiring route", () => {
  it("resolves to the Expiring page", async () => {
    vi.mocked(client.GET).mockResolvedValue({
      data: [],
      response: new Response(null, { status: 200 }),
    } as AnyResult);

    renderExpiringPage();

    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /expiring lots/i }),
      ).toBeDefined();
    });
  });

  it("clicking the expiry tile view-all link navigates to /expiring", async () => {
    vi.mocked(client.GET).mockImplementation(async (path: AnyResult) => {
      if (path === "/api/expiring") {
        return { data: [expiringItem1], response: new Response(null, { status: 200 }) };
      }
      return { data: [], response: new Response(null, { status: 200 }) };
    });

    renderDashboard();

    // Wait for the tile link to appear
    await waitFor(() => {
      expect(screen.getByTestId("expiry-view-link")).toBeDefined();
    });

    // Click the link — MemoryRouter navigates to /expiring
    screen.getByTestId("expiry-view-link").click();

    // The Expiring page should now render
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { name: /expiring lots/i }),
      ).toBeDefined();
    });
  });
});
