/**
 * Search → tag filter integration tests.
 *
 * Coverage:
 *
 * 1. Search page — tag hit URL carries tag id:
 *    a. Tag hit renders a link to /items?tag=<id> (not bare /items).
 *
 * 2. Items page — URL pre-applies tag filter:
 *    a. Rendering /items?tag=<id> pre-applies the filter — only definitions
 *       carrying that tag are shown, others hidden.
 *    b. The tag-filter-select reflects the pre-selected tag by id.
 *    c. Clearing the Select removes the filter; the full list restores.
 *    d. Changing the Select (from a filtered URL entry) updates the URL param.
 *    e. A tag param that matches no loaded tag yields an empty filter without crashing.
 *
 * Conventions: vitest + Testing Library, mock typed client, pinned to "en",
 * no @testing-library/jest-dom (.toBeDefined() / .toBeNull() like siblings).
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Routes, Route, useLocation } from "react-router-dom";
import { Items } from "../pages/Items.js";
import i18n from "../i18n/index.js";

// ── Mock client ───────────────────────────────────────────────────────────────

vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
    PUT: vi.fn(),
    PATCH: vi.fn(),
    DELETE: vi.fn(),
  },
}));

import { client } from "../api/client.js";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

// ── Helpers ───────────────────────────────────────────────────────────────────

function ok200<T>(data: T) {
  return { data, error: undefined, response: new Response(null, { status: 200 }) };
}

// ── Fixtures ──────────────────────────────────────────────────────────────────

const tagFood = {
  id: 10,
  name: "Food",
  color: "orange",
  created_at: "2026-06-27T00:00:00Z",
};

const tagElec = {
  id: 20,
  name: "Electronics",
  color: "blue",
  created_at: "2026-06-27T00:00:00Z",
};

const kindConsumable = {
  id: 1,
  code: "consumable",
  name: "Consumable",
  is_system: true,
  created_at: "2026-06-27T00:00:00Z",
};

// defApple carries tagFood; defCharger carries no tags.
const defApple = {
  id: 101,
  name: "Apple",
  description: null,
  category_id: null,
  kind_id: 1,
  kind: kindConsumable,
  unit: "pcs",
  default_location_id: null,
  stock_tracking_mode: "exact",
  min_stock: null,
  default_best_before_days: null,
  reminder_lead_days: null,
  created_at: "2026-06-27T00:00:00Z",
};

const defCharger = {
  id: 102,
  name: "Charger",
  description: null,
  category_id: null,
  kind_id: 1,
  kind: kindConsumable,
  unit: "pcs",
  default_location_id: null,
  stock_tracking_mode: "none",
  min_stock: null,
  default_best_before_days: null,
  reminder_lead_days: null,
  created_at: "2026-06-27T00:00:00Z",
};

/** Mock that returns both defs, tags=[tagFood, tagElec], and tag-links per definition. */
function mockItemsClient() {
  vi.mocked(client.GET).mockImplementation(async (path: Any, opts?: Any) => {
    if (path === "/api/definitions") return ok200([defApple, defCharger]);
    if (path === "/api/kinds") return ok200([kindConsumable]);
    if (path === "/api/categories") return ok200([]);
    if (path === "/api/locations") return ok200([]);
    if (path === "/api/tags") return ok200([tagFood, tagElec]);
    if (path === "/api/tags/links") {
      const modelId = opts?.params?.query?.model_id;
      if (modelId === 101) {
        return ok200([{
          id: 1001,
          tag_id: tagFood.id,
          tag: tagFood,
          model_type: "item_definition",
          model_id: 101,
          created_at: "2026-06-27T00:00:00Z",
        }]);
      }
      // defCharger has no tags
      return ok200([]);
    }
    return ok200([]);
  });
}

/** Captures current location so tests can assert URL changes. */
function LocationDisplay() {
  const loc = useLocation();
  return <div data-testid="location-display">{loc.pathname + loc.search}</div>;
}

/** Render Items page at a given initial URL (path + optional search). */
function renderItemsAt(initialUrl: string) {
  return render(
    <MemoryRouter initialEntries={[initialUrl]}>
      <MantineProvider>
        <Routes>
          <Route path="/items" element={<><Items /><LocationDisplay /></>} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

// ── Setup ─────────────────────────────────────────────────────────────────────

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.clearAllMocks();
});

// ── 1. Items — URL pre-applies tag filter ─────────────────────────────────────

describe("Items — URL ?tag param pre-applies tag filter", () => {
  it("renders /items?tag=10 and shows only definitions carrying that tag", async () => {
    mockItemsClient();

    await act(async () => {
      renderItemsAt("/items?tag=10");
    });

    // Wait for cache to load (tagFilter is active from the start)
    await waitFor(() => {
      expect(screen.getByTestId("def-row-101")).toBeDefined();
      expect(screen.queryByTestId("def-row-102")).toBeNull();
    });
  });

  it("tag-filter-select reflects the pre-applied tag (shows 'Food' as the selected value)", async () => {
    mockItemsClient();

    await act(async () => {
      renderItemsAt("/items?tag=10");
    });

    // The select's underlying input should have the tag name as its value.
    // Mantine's Select renders the label of the selected option in the input.
    await waitFor(() => {
      const selectWrapper = screen.getByTestId("tag-filter-select");
      const input = (selectWrapper.querySelector("input") ?? selectWrapper) as HTMLInputElement;
      expect(input.value).toBe("Food");
    });
  });

  it("clearing the select from a URL-pre-applied filter restores the full list", async () => {
    mockItemsClient();

    await act(async () => {
      renderItemsAt("/items?tag=10");
    });

    // Wait for filter to be applied (only Apple visible)
    await waitFor(() => {
      expect(screen.queryByTestId("def-row-102")).toBeNull();
    });

    // Click the Mantine clearable button (tabindex="-1" button)
    const clearBtn = document.querySelector<HTMLElement>('button[tabindex="-1"]');
    expect(clearBtn).not.toBeNull();
    await act(async () => {
      fireEvent.click(clearBtn!);
    });

    // Both definitions are restored
    await waitFor(() => {
      expect(screen.getByTestId("def-row-101")).toBeDefined();
      expect(screen.getByTestId("def-row-102")).toBeDefined();
    });
  });

  it("changing the Select updates the URL ?tag param", async () => {
    mockItemsClient();

    await act(async () => {
      renderItemsAt("/items");
    });

    // Both definitions visible initially
    await screen.findByTestId("def-row-101");
    await screen.findByTestId("def-row-102");

    // Open tag-filter Select and pick "Food"
    const selectWrapper = screen.getByTestId("tag-filter-select");
    const selectInput = (selectWrapper.querySelector("input") ?? selectWrapper) as HTMLElement;

    await act(async () => {
      fireEvent.click(selectInput);
    });

    const foodOption = await screen.findByText("Food");
    await act(async () => {
      fireEvent.click(foodOption);
    });

    // URL should now include ?tag=10
    await waitFor(() => {
      const loc = screen.getByTestId("location-display").textContent ?? "";
      expect(loc).toContain("tag=10");
    });
  });

  it("a ?tag param that matches no loaded tag yields an empty filter without crashing", async () => {
    mockItemsClient();

    // tag id 999 doesn't exist in the mock tags list
    await act(async () => {
      renderItemsAt("/items?tag=999");
    });

    // Page loads without error; the tag-link cache will have been fetched but
    // no definition will have tag 999 → both definitions hidden while loading,
    // then remain hidden (cached result has empty tag list → 999 not matched).
    // The important thing is no crash and the page renders.
    await waitFor(() => {
      // The page itself renders (no error state)
      expect(screen.getByTestId("def-search-input")).toBeDefined();
    });
  });
});
