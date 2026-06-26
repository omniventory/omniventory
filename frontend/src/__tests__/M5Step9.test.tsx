/**
 * M5 Step 9 — Tags + notes UI.
 *
 * Coverage (per M5 §7.1, §7.6, §9 Step 9):
 *
 * 1. TagPanel:
 *    a. Loads and displays attached tags as Badge chips.
 *    b. Attach existing tag: selecting an option calls PUT /api/tags/links
 *       with the augmented tag_ids set; chip appears after reload.
 *    c. Detach: clicking × on a chip calls PUT /api/tags/links with reduced set.
 *    d. Create-on-the-fly: typing a new name and submitting "__create__" calls
 *       POST /api/tags then PUT /api/tags/links; chip appears.
 *    e. Empty state shown when no tags attached.
 *
 * 2. NotePanel:
 *    a. Loads and displays notes with body text.
 *    b. Add note: fills textarea + clicks Add → POST /api/notes; card appears.
 *    c. Edit note: clicks Edit → textarea appears → Save → PATCH /api/notes/{id}.
 *    d. Delete note: clicks Delete → confirm modal → DELETE /api/notes/{id}; card gone.
 *    e. Empty state shown when no notes.
 *
 * 3. Tag filter on Items list (Items page rendered with mocked client):
 *    a. When tag filter is applied, only definitions carrying that tag are shown.
 *    b. Clearing the filter restores the full unfiltered list.
 *    c. Definitions whose tag-link cache entry is undefined are hidden until loaded.
 *
 * Conventions: vitest + Testing Library, mock typed client, pinned to "en".
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
import { MemoryRouter, Routes, Route } from "react-router-dom";
import { TagPanel } from "../components/TagPanel.js";
import { NotePanel } from "../components/NotePanel.js";
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

// ── Fixtures ──────────────────────────────────────────────────────────────────

const tag1 = {
  id: 10,
  name: "Food",
  color: "orange",
  created_at: "2026-06-27T00:00:00Z",
};

const tag2 = {
  id: 20,
  name: "Fridge",
  color: "cyan",
  created_at: "2026-06-27T00:00:00Z",
};

function makeLink(tag: Any) {
  return {
    id: tag.id * 100,
    tag_id: tag.id,
    tag,
    model_type: "stock_instance",
    model_id: 42,
    created_at: "2026-06-27T00:00:00Z",
  };
}

const note1 = {
  id: 1,
  model_type: "stock_instance",
  model_id: 42,
  body: "Store in a cool place.",
  created_by: 1,
  created_at: "2026-06-27T00:00:00Z",
  updated_at: "2026-06-27T00:00:00Z",
};

const note2 = {
  id: 2,
  model_type: "stock_instance",
  model_id: 42,
  body: "Check before use.",
  created_by: 1,
  created_at: "2026-06-27T00:00:00Z",
  updated_at: "2026-06-27T00:00:00Z",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

beforeEach(async () => {
  await i18n.changeLanguage("en");
});

afterEach(() => {
  vi.restoreAllMocks();
});

function ok200<T>(data: T) {
  return { data, error: undefined, response: new Response(null, { status: 200 }) };
}

function ok201<T>(data: T) {
  return { data, error: undefined, response: new Response(null, { status: 201 }) };
}

function ok204() {
  return { data: undefined, error: undefined, response: new Response(null, { status: 204 }) };
}

function renderTagPanel(modelId = 42) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <TagPanel modelType="stock_instance" modelId={modelId} />
      </MantineProvider>
    </MemoryRouter>,
  );
}

function renderNotePanel(modelId = 42) {
  return render(
    <MemoryRouter>
      <MantineProvider>
        <NotePanel modelType="stock_instance" modelId={modelId} />
      </MantineProvider>
    </MemoryRouter>,
  );
}

// ── TagPanel: chip display ────────────────────────────────────────────────────

describe("TagPanel — display", () => {
  it("shows empty state when no tags attached", async () => {
    vi.mocked(client.GET).mockResolvedValue(ok200([]));

    await act(async () => { renderTagPanel(); });

    await screen.findByTestId("tag-empty");
    expect(screen.getByTestId("tag-empty").textContent).toContain("No tags yet");
  });

  it("renders a chip for each attached tag", async () => {
    vi.mocked(client.GET).mockResolvedValue(ok200([makeLink(tag1), makeLink(tag2)]));

    await act(async () => { renderTagPanel(); });

    await screen.findByTestId("tag-chip-10");
    expect(screen.getByTestId("tag-chip-10").textContent).toContain("Food");
    expect(screen.getByTestId("tag-chip-20").textContent).toContain("Fridge");
  });
});

// ── TagPanel: attach existing tag ─────────────────────────────────────────────

describe("TagPanel — attach existing tag", () => {
  it("selecting an option calls PUT /api/tags/links with augmented tag_ids and chip appears", async () => {
    let getCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async (path: Any) => {
      if (path === "/api/tags/links") {
        getCallCount++;
        // First load: no tags. After PUT reload: tag1 attached.
        return ok200(getCallCount === 1 ? [] : [makeLink(tag1)]);
      }
      if (path === "/api/tags") {
        return ok200([tag1]);
      }
      return ok200([]);
    });

    let putBody: Any = null;
    vi.mocked(client.PUT).mockImplementation(async (_path: Any, opts: Any) => {
      putBody = opts?.body;
      return ok200([tag1]);
    });

    await act(async () => { renderTagPanel(); });

    // Wait for initial empty state
    await screen.findByTestId("tag-empty");

    // Type into the search input to trigger option loading
    const searchWrapper = screen.getByTestId("tag-search-input");
    const searchInput = (searchWrapper.querySelector("input") ?? searchWrapper) as HTMLInputElement;

    await act(async () => {
      fireEvent.change(searchInput, { target: { value: "Food" } });
    });

    // Wait for options to load
    const option = await screen.findByTestId("tag-option-10");

    await act(async () => {
      fireEvent.click(option);
    });

    // PUT must be called with the correct body
    await waitFor(() => {
      expect(putBody).not.toBeNull();
      expect(putBody.model_type).toBe("stock_instance");
      expect(putBody.model_id).toBe(42);
      expect(putBody.tag_ids).toContain(10);
    });

    // After reload, chip should appear
    await screen.findByTestId("tag-chip-10");
  });
});

// ── TagPanel: detach ──────────────────────────────────────────────────────────

describe("TagPanel — detach", () => {
  it("clicking × on a chip calls PUT /api/tags/links with reduced set", async () => {
    let getCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async (path: Any) => {
      if (path === "/api/tags/links") {
        getCallCount++;
        // First load: tag1 + tag2 attached; after detach: only tag2 remains.
        return ok200(getCallCount === 1
          ? [makeLink(tag1), makeLink(tag2)]
          : [makeLink(tag2)]);
      }
      return ok200([]);
    });

    let putBody: Any = null;
    vi.mocked(client.PUT).mockImplementation(async (_path: Any, opts: Any) => {
      putBody = opts?.body;
      return ok200([tag2]);
    });

    await act(async () => { renderTagPanel(); });

    // Wait for chips
    await screen.findByTestId("tag-chip-10");
    await screen.findByTestId("tag-chip-20");

    // Click × on tag1
    await act(async () => {
      fireEvent.click(screen.getByTestId("tag-detach-10"));
    });

    // PUT called with tag2 only
    await waitFor(() => {
      expect(putBody).not.toBeNull();
      expect(putBody.tag_ids).toContain(20);
      expect(putBody.tag_ids).not.toContain(10);
    });

    // tag1 chip gone
    await waitFor(() => {
      expect(screen.queryByTestId("tag-chip-10")).toBeNull();
    });
  });
});

// ── TagPanel: create-on-the-fly ───────────────────────────────────────────────

describe("TagPanel — create-on-the-fly", () => {
  it("typing a new name and choosing Create calls POST /api/tags then PUT /api/tags/links", async () => {
    let getCallCount = 0;
    const newTag = { id: 30, name: "Pantry", color: null, created_at: "2026-06-27T00:00:00Z" };

    vi.mocked(client.GET).mockImplementation(async (path: Any) => {
      if (path === "/api/tags/links") {
        getCallCount++;
        return ok200(getCallCount === 1 ? [] : [makeLink(newTag)]);
      }
      if (path === "/api/tags") {
        // No existing tags match "Pantry"
        return ok200([]);
      }
      return ok200([]);
    });

    let postBody: Any = null;
    vi.mocked(client.POST).mockImplementation(async (_path: Any, opts: Any) => {
      postBody = opts?.body;
      return ok201(newTag);
    });

    let putBody: Any = null;
    vi.mocked(client.PUT).mockImplementation(async (_path: Any, opts: Any) => {
      putBody = opts?.body;
      return ok200([newTag]);
    });

    await act(async () => { renderTagPanel(); });

    await screen.findByTestId("tag-empty");

    // Type a new tag name
    const searchWrapper = screen.getByTestId("tag-search-input");
    const searchInput = (searchWrapper.querySelector("input") ?? searchWrapper) as HTMLInputElement;

    await act(async () => {
      fireEvent.change(searchInput, { target: { value: "Pantry" } });
    });

    // Wait for the Create option
    const createOption = await screen.findByTestId("tag-create-option");
    expect(createOption.textContent).toContain("Pantry");

    await act(async () => {
      fireEvent.click(createOption);
    });

    // POST /api/tags must be called
    await waitFor(() => {
      expect(postBody).not.toBeNull();
      expect(postBody.name).toBe("Pantry");
    });

    // PUT /api/tags/links must be called with the new tag id
    await waitFor(() => {
      expect(putBody).not.toBeNull();
      expect(putBody.tag_ids).toContain(30);
    });

    // Chip appears
    await screen.findByTestId("tag-chip-30");
  });
});

// ── NotePanel: display ────────────────────────────────────────────────────────

describe("NotePanel — display", () => {
  it("shows empty state when no notes", async () => {
    vi.mocked(client.GET).mockResolvedValue(ok200([]));

    await act(async () => { renderNotePanel(); });

    await screen.findByTestId("note-empty");
    expect(screen.getByTestId("note-empty").textContent).toContain("No notes yet");
  });

  it("renders a card for each note with body text", async () => {
    vi.mocked(client.GET).mockResolvedValue(ok200([note1, note2]));

    await act(async () => { renderNotePanel(); });

    await screen.findByTestId("note-card-1");
    expect(screen.getByTestId("note-body-1").textContent).toContain("Store in a cool place.");
    expect(screen.getByTestId("note-body-2").textContent).toContain("Check before use.");
  });
});

// ── NotePanel: add ────────────────────────────────────────────────────────────

describe("NotePanel — add note", () => {
  it("filling textarea and clicking Add calls POST /api/notes; card appears", async () => {
    let getCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async () => {
      getCallCount++;
      return ok200(getCallCount === 1 ? [] : [note1]);
    });

    let postBody: Any = null;
    vi.mocked(client.POST).mockImplementation(async (_path: Any, opts: Any) => {
      postBody = opts?.body;
      return ok201(note1);
    });

    await act(async () => { renderNotePanel(); });

    await screen.findByTestId("note-empty");

    // Fill the add textarea
    const textareaWrapper = screen.getByTestId("note-add-textarea");
    const textarea = (textareaWrapper.querySelector("textarea") ?? textareaWrapper) as HTMLTextAreaElement;

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "Store in a cool place." } });
    });

    // Click Add
    await act(async () => {
      fireEvent.click(screen.getByTestId("note-add-btn"));
    });

    // POST called with correct body
    await waitFor(() => {
      expect(postBody).not.toBeNull();
      expect(postBody.model_type).toBe("stock_instance");
      expect(postBody.model_id).toBe(42);
      expect(postBody.body).toBe("Store in a cool place.");
    });

    // Note card appears
    await screen.findByTestId("note-card-1");
  });
});

// ── NotePanel: edit ───────────────────────────────────────────────────────────

describe("NotePanel — edit note", () => {
  it("clicking Edit shows textarea; saving calls PATCH /api/notes/{id}", async () => {
    let getCallCount = 0;
    const updatedNote = { ...note1, body: "Updated text." };

    vi.mocked(client.GET).mockImplementation(async () => {
      getCallCount++;
      return ok200(getCallCount === 1 ? [note1] : [updatedNote]);
    });

    let patchPath: Any = null;
    let patchOpts: Any = null;
    vi.mocked(client.PATCH).mockImplementation(async (path: Any, opts: Any) => {
      patchPath = path;
      patchOpts = opts;
      return ok200(updatedNote);
    });

    await act(async () => { renderNotePanel(); });

    await screen.findByTestId("note-card-1");

    // Click Edit button
    await act(async () => {
      fireEvent.click(screen.getByTestId("note-edit-btn-1"));
    });

    // Inline textarea appears
    const editTextareaWrapper = await screen.findByTestId("note-edit-textarea-1");
    const editTextarea = (editTextareaWrapper.querySelector("textarea") ?? editTextareaWrapper) as HTMLTextAreaElement;

    // Change the body
    await act(async () => {
      fireEvent.change(editTextarea, { target: { value: "Updated text." } });
    });

    // Save
    await act(async () => {
      fireEvent.click(screen.getByTestId("note-save-btn-1"));
    });

    // PATCH called
    await waitFor(() => {
      expect(patchPath).toBe("/api/notes/{note_id}");
      expect(patchOpts?.params?.path?.note_id).toBe(1);
      expect(patchOpts?.body?.body).toBe("Updated text.");
    });

    // Updated body shown
    await waitFor(() => {
      expect(screen.getByTestId("note-body-1").textContent).toContain("Updated text.");
    });
  });
});

// ── NotePanel: delete ─────────────────────────────────────────────────────────

describe("NotePanel — delete note", () => {
  it("clicking Delete opens modal; confirming calls DELETE /api/notes/{id}; card gone", async () => {
    let getCallCount = 0;

    vi.mocked(client.GET).mockImplementation(async () => {
      getCallCount++;
      return ok200(getCallCount === 1 ? [note1, note2] : [note2]);
    });

    let deletePath: Any = null;
    let deleteOpts: Any = null;
    vi.mocked(client.DELETE).mockImplementation(async (path: Any, opts: Any) => {
      deletePath = path;
      deleteOpts = opts;
      return ok204();
    });

    await act(async () => { renderNotePanel(); });

    await screen.findByTestId("note-card-1");
    await screen.findByTestId("note-card-2");

    // Click delete on note1
    await act(async () => {
      fireEvent.click(screen.getByTestId("note-delete-btn-1"));
    });

    // Confirm modal appears
    const confirmBtn = await screen.findByTestId("confirm-delete-note-btn");
    expect(screen.getByText("Are you sure you want to delete this note?")).toBeDefined();

    // Confirm
    await act(async () => {
      fireEvent.click(confirmBtn);
    });

    // DELETE called with correct path and id
    await waitFor(() => {
      expect(deletePath).toBe("/api/notes/{note_id}");
      expect(deleteOpts?.params?.path?.note_id).toBe(1);
    });

    // note1 card gone; note2 remains
    await waitFor(() => {
      expect(screen.queryByTestId("note-card-1")).toBeNull();
    });
    expect(screen.getByTestId("note-card-2")).toBeDefined();
  });
});

// ── Items — tag filter narrows ────────────────────────────────────────────────

const kindConsumable = {
  id: 1,
  code: "consumable",
  name: "Consumable",
  is_system: true,
  created_at: "2026-06-27T00:00:00Z",
};

// defApple carries tag1 (Food); defCharger carries no tags.
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

function renderItemsPage() {
  return render(
    <MemoryRouter initialEntries={["/items"]}>
      <MantineProvider>
        <Routes>
          <Route path="/items" element={<Items />} />
        </Routes>
      </MantineProvider>
    </MemoryRouter>,
  );
}

describe("Items — tag filter narrows", () => {
  function mockItemsWithTags() {
    vi.mocked(client.GET).mockImplementation(async (path: Any, opts?: Any) => {
      if (path === "/api/definitions") {
        return ok200([defApple, defCharger]);
      }
      if (path === "/api/kinds") {
        return ok200([kindConsumable]);
      }
      if (path === "/api/categories") {
        return ok200([]);
      }
      if (path === "/api/locations") {
        return ok200([]);
      }
      if (path === "/api/tags") {
        // tag1 = { id: 10, name: "Food" } declared in the fixtures section above
        return ok200([tag1]);
      }
      if (path === "/api/tags/links") {
        const modelId = opts?.params?.query?.model_id;
        // defApple (id=101) has tag1 (Food); defCharger (id=102) has none
        if (modelId === 101) {
          return ok200([{
            id: 1001,
            tag_id: tag1.id,
            tag: tag1,
            model_type: "item_definition",
            model_id: 101,
            created_at: "2026-06-27T00:00:00Z",
          }]);
        }
        return ok200([]);
      }
      return ok200([]);
    });
  }

  it("applying tag filter shows only tagged definitions; clearing restores all", async () => {
    mockItemsWithTags();

    await act(async () => {
      renderItemsPage();
    });

    // Wait for both definitions to appear after initial load
    await screen.findByTestId("def-row-101");
    await screen.findByTestId("def-row-102");
    expect(screen.getByTestId("def-row-101")).toBeDefined();
    expect(screen.getByTestId("def-row-102")).toBeDefined();

    // Open the tag-filter Select and choose the "Food" tag
    const selectWrapper = screen.getByTestId("tag-filter-select");
    const selectInput = (selectWrapper.querySelector("input") ?? selectWrapper) as HTMLElement;

    await act(async () => {
      fireEvent.click(selectInput);
    });

    // The "Food" option should appear in the Combobox dropdown
    const foodOption = await screen.findByText("Food");
    await act(async () => {
      fireEvent.click(foodOption);
    });

    // After cache is populated by the tagFilter useEffect:
    // — defApple (101) has Food → stays visible
    // — defCharger (102) has no tags → hidden
    await waitFor(() => {
      expect(screen.getByTestId("def-row-101")).toBeDefined();
      expect(screen.queryByTestId("def-row-102")).toBeNull();
    });

    // Clear the filter.  Mantine v9 ComboboxClearButton has aria-hidden="true" and
    // tabindex="-1".  The testid resolves to the <input> (no children) so we search
    // the whole document — the tag-filter Select is the only clearable one on the page.
    const clearBtn = document.querySelector<HTMLElement>('button[tabindex="-1"]');
    expect(clearBtn).not.toBeNull();
    await act(async () => {
      fireEvent.click(clearBtn!);
    });

    // Both definitions restored in the unfiltered list
    await waitFor(() => {
      expect(screen.getByTestId("def-row-101")).toBeDefined();
      expect(screen.getByTestId("def-row-102")).toBeDefined();
    });
  });

  it("definitions with uncached tag-links are hidden until the cache loads", async () => {
    // Resolve promises manually so we control when the cache populates
    let resolveLinks101: (v: Any) => void = () => { /* noop */ };
    let resolveLinks102: (v: Any) => void = () => { /* noop */ };

    vi.mocked(client.GET).mockImplementation(async (path: Any, opts?: Any) => {
      if (path === "/api/definitions") return ok200([defApple, defCharger]);
      if (path === "/api/kinds") return ok200([kindConsumable]);
      if (path === "/api/categories") return ok200([]);
      if (path === "/api/locations") return ok200([]);
      if (path === "/api/tags") return ok200([tag1]);
      if (path === "/api/tags/links") {
        const modelId = opts?.params?.query?.model_id;
        if (modelId === 101) {
          return new Promise<Any>((res) => { resolveLinks101 = res; });
        }
        if (modelId === 102) {
          return new Promise<Any>((res) => { resolveLinks102 = res; });
        }
      }
      return ok200([]);
    });

    await act(async () => {
      renderItemsPage();
    });

    // Both rows visible before filter
    await screen.findByTestId("def-row-101");
    await screen.findByTestId("def-row-102");

    // Apply tag filter → cache entries are undefined → both rows hidden
    const selectWrapper = screen.getByTestId("tag-filter-select");
    const selectInput = (selectWrapper.querySelector("input") ?? selectWrapper) as HTMLElement;

    await act(async () => {
      fireEvent.click(selectInput);
    });
    const foodOption = await screen.findByText("Food");
    await act(async () => {
      fireEvent.click(foodOption);
    });

    // Before cache resolves: both rows should be hidden (cached === undefined → false)
    await waitFor(() => {
      expect(screen.queryByTestId("def-row-101")).toBeNull();
      expect(screen.queryByTestId("def-row-102")).toBeNull();
    });

    // Resolve cache for both definitions
    await act(async () => {
      resolveLinks101(ok200([{
        id: 1001,
        tag_id: tag1.id,
        tag: tag1,
        model_type: "item_definition",
        model_id: 101,
        created_at: "2026-06-27T00:00:00Z",
      }]));
      resolveLinks102(ok200([]));
    });

    // After cache resolves: only Apple (101) visible; Charger (102) still hidden
    await waitFor(() => {
      expect(screen.getByTestId("def-row-101")).toBeDefined();
      expect(screen.queryByTestId("def-row-102")).toBeNull();
    });
  });
});

// ── i18n catalog: tags + notes ────────────────────────────────────────────────

import enTags from "../i18n/locales/en/tags.json";
import zhTags from "../i18n/locales/zh/tags.json";
import enNotes from "../i18n/locales/en/notes.json";
import zhNotes from "../i18n/locales/zh/notes.json";

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

describe("tags i18n — en+zh catalog parity", () => {
  it("en and zh tags namespace have identical key sets", () => {
    const enKeys = collectKeys(enTags).sort();
    const zhKeys = collectKeys(zhTags).sort();
    expect(enKeys.filter((k) => !zhKeys.includes(k)), "Missing in zh").toEqual([]);
    expect(zhKeys.filter((k) => !enKeys.includes(k)), "Extra in zh").toEqual([]);
  });

  it("tags.sectionTitle is 'Tags' in en", () => {
    expect(i18n.t("sectionTitle", { ns: "tags" })).toBe("Tags");
  });

  it("tags.sectionTitle is translated in zh", async () => {
    await i18n.changeLanguage("zh");
    const v = i18n.t("sectionTitle", { ns: "tags" });
    expect(v).not.toBe("Tags");
    expect(v.trim().length).toBeGreaterThan(0);
    await i18n.changeLanguage("en");
  });
});

describe("notes i18n — en+zh catalog parity", () => {
  it("en and zh notes namespace have identical key sets", () => {
    const enKeys = collectKeys(enNotes).sort();
    const zhKeys = collectKeys(zhNotes).sort();
    expect(enKeys.filter((k) => !zhKeys.includes(k)), "Missing in zh").toEqual([]);
    expect(zhKeys.filter((k) => !enKeys.includes(k)), "Extra in zh").toEqual([]);
  });

  it("notes.sectionTitle is 'Notes' in en", () => {
    expect(i18n.t("sectionTitle", { ns: "notes" })).toBe("Notes");
  });

  it("notes.sectionTitle is translated in zh", async () => {
    await i18n.changeLanguage("zh");
    const v = i18n.t("sectionTitle", { ns: "notes" });
    expect(v).not.toBe("Notes");
    expect(v.trim().length).toBeGreaterThan(0);
    await i18n.changeLanguage("en");
  });
});
