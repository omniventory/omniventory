/**
 * M6 Step 8 — Auth context + role-based UI gating tests.
 *
 * Coverage:
 *  1. Permission matrix unit tests (hasPermission) — each role × each permission.
 *  2. Nav gating: Configuration item present for admin, absent for member/viewer.
 *  3. Route gating: non-admin navigating to /configuration is redirected to /.
 *  4. Write actions hidden for viewer on Items page (create/edit/delete buttons).
 *  5. Write actions hidden for viewer on TreeBrowser (create-root-btn).
 *  6. Write actions visible for member on Items page.
 *  7. i18n roles namespace: both en and zh have admin/member/viewer keys.
 *  8. AttachmentPanel write controls (upload/delete) gated by EDIT; gallery visible to viewer.
 *  9. BarcodePanel write controls (add/remove) gated by EDIT; barcode list visible to viewer.
 * 10. UserButton renders localized role label for the current role.
 *
 * All tests pin to 'en' (M1.5 convention).
 * Components are wrapped with explicit AuthProvider per role.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import { MemoryRouter, Routes, Route } from "react-router-dom";

// i18n must be initialized before any component that calls useTranslation().
import "../i18n/index.js";

import { hasPermission, AuthProvider } from "../auth/AuthContext";
import { RequirePermission } from "../auth/RequirePermission";
import { NavContent_testable } from "../shell/AppShell";
import { Items } from "../pages/Items";
import { TreeBrowser } from "../components/TreeBrowser";
import { AttachmentPanel } from "../components/AttachmentPanel";
import { BarcodePanel } from "../components/BarcodePanel";
import { UserButton } from "../components/UserButton";
import type { components } from "../api/schema";

import enRoles from "../i18n/locales/en/roles.json";
import zhRoles from "../i18n/locales/zh/roles.json";

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

// ── Fixture helpers ────────────────────────────────────────────────────────────

type UserResponse = components["schemas"]["UserResponse"];

function makeUser(role: "admin" | "member" | "viewer"): UserResponse {
  return {
    id: 1,
    email: `${role}@example.com`,
    role,
    is_active: true,
    notify_in_app: true,
    notify_email_digest: true,
    created_at: "2025-01-01T00:00:00Z",
    preferred_language: "en",
  };
}

/** Wrap children with an AuthProvider seeded with the given role. */
function withAuth(role: "admin" | "member" | "viewer", children: React.ReactNode) {
  return (
    <AuthProvider
      user={makeUser(role)}
      onRefresh={vi.fn()}
      onLogout={vi.fn()}
    >
      {children}
    </AuthProvider>
  );
}

// ── 1. Permission matrix unit tests ────────────────────────────────────────────

describe("Permission matrix — hasPermission() matches M6.md §2", () => {
  // viewer → {VIEW}
  it("viewer has VIEW", () => expect(hasPermission("viewer", "VIEW")).toBe(true));
  it("viewer lacks EDIT", () => expect(hasPermission("viewer", "EDIT")).toBe(false));
  it("viewer lacks MANAGE_USERS", () => expect(hasPermission("viewer", "MANAGE_USERS")).toBe(false));
  it("viewer lacks MANAGE_SETTINGS", () => expect(hasPermission("viewer", "MANAGE_SETTINGS")).toBe(false));
  it("viewer lacks VIEW_AUDIT", () => expect(hasPermission("viewer", "VIEW_AUDIT")).toBe(false));

  // member → {VIEW, EDIT}
  it("member has VIEW", () => expect(hasPermission("member", "VIEW")).toBe(true));
  it("member has EDIT", () => expect(hasPermission("member", "EDIT")).toBe(true));
  it("member lacks MANAGE_USERS", () => expect(hasPermission("member", "MANAGE_USERS")).toBe(false));
  it("member lacks MANAGE_SETTINGS", () => expect(hasPermission("member", "MANAGE_SETTINGS")).toBe(false));
  it("member lacks VIEW_AUDIT", () => expect(hasPermission("member", "VIEW_AUDIT")).toBe(false));

  // admin → {VIEW, EDIT, MANAGE_USERS, MANAGE_SETTINGS, VIEW_AUDIT}
  it("admin has VIEW", () => expect(hasPermission("admin", "VIEW")).toBe(true));
  it("admin has EDIT", () => expect(hasPermission("admin", "EDIT")).toBe(true));
  it("admin has MANAGE_USERS", () => expect(hasPermission("admin", "MANAGE_USERS")).toBe(true));
  it("admin has MANAGE_SETTINGS", () => expect(hasPermission("admin", "MANAGE_SETTINGS")).toBe(true));
  it("admin has VIEW_AUDIT", () => expect(hasPermission("admin", "VIEW_AUDIT")).toBe(true));

  // unknown/null role
  it("null role returns false for all permissions", () => {
    expect(hasPermission(null, "VIEW")).toBe(false);
    expect(hasPermission(null, "EDIT")).toBe(false);
    expect(hasPermission(null, "MANAGE_USERS")).toBe(false);
  });
  it("unknown role returns false for all permissions", () => {
    expect(hasPermission("superadmin", "VIEW")).toBe(false);
    expect(hasPermission("superadmin", "EDIT")).toBe(false);
  });
});

// ── 2. Nav gating per role ─────────────────────────────────────────────────────

/**
 * NavContent is an internal component. We export a testable alias from AppShell
 * (see the import above). If that export doesn't exist, the test will fail at
 * import time and tell the reviewer to add the export.
 */
describe("Nav — Configuration item gated by MANAGE_SETTINGS", () => {
  function renderNav(role: "admin" | "member" | "viewer") {
    return render(
      <MemoryRouter initialEntries={["/"]}>
        <MantineProvider>
          {withAuth(role, <NavContent_testable />)}
        </MantineProvider>
      </MemoryRouter>,
    );
  }

  it("admin sees Configuration in the nav", async () => {
    renderNav("admin");
    await waitFor(() => {
      expect(screen.getByText("Configuration")).toBeDefined();
    });
  });

  it("member does NOT see Configuration in the nav", async () => {
    renderNav("member");
    await waitFor(() => {
      // Dashboard is always present, use it as a readiness signal
      expect(screen.getByText("Dashboard")).toBeDefined();
    });
    expect(screen.queryByText("Configuration")).toBeNull();
  });

  it("viewer does NOT see Configuration in the nav", async () => {
    renderNav("viewer");
    await waitFor(() => {
      expect(screen.getByText("Dashboard")).toBeDefined();
    });
    expect(screen.queryByText("Configuration")).toBeNull();
  });
});

// ── 3. Route gating with RequirePermission ─────────────────────────────────────

describe("Route gating — /configuration redirects non-admins to /", () => {
  function renderRoute(role: "admin" | "member" | "viewer") {
    return render(
      <MemoryRouter initialEntries={["/configuration"]}>
        <MantineProvider>
          {withAuth(role, (
            <Routes>
              <Route path="/" element={<div data-testid="dashboard-page">Dashboard</div>} />
              <Route
                path="/configuration"
                element={
                  <RequirePermission permission="MANAGE_SETTINGS">
                    <div data-testid="config-page">Configuration</div>
                  </RequirePermission>
                }
              />
            </Routes>
          ))}
        </MantineProvider>
      </MemoryRouter>,
    );
  }

  it("admin can access /configuration", async () => {
    renderRoute("admin");
    await waitFor(() => {
      expect(screen.getByTestId("config-page")).toBeDefined();
    });
    expect(screen.queryByTestId("dashboard-page")).toBeNull();
  });

  it("member is redirected from /configuration to /", async () => {
    renderRoute("member");
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-page")).toBeDefined();
    });
    expect(screen.queryByTestId("config-page")).toBeNull();
  });

  it("viewer is redirected from /configuration to /", async () => {
    renderRoute("viewer");
    await waitFor(() => {
      expect(screen.getByTestId("dashboard-page")).toBeDefined();
    });
    expect(screen.queryByTestId("config-page")).toBeNull();
  });
});

// ── 4. Write actions hidden for viewer, visible for member — Items page ─────────

const defDrill = {
  id: 42,
  name: "Cordless Drill",
  description: null,
  category_id: null,
  kind_id: 1,
  kind: { id: 1, code: "durable", name: "Durable", is_system: true, created_at: "2025-01-01T00:00:00Z" },
  unit: "pcs",
  default_location_id: null,
  stock_tracking_mode: "exact",
  min_stock: null,
  default_best_before_days: null,
  reminder_lead_days: null,
  custom_fields: null,
  created_at: "2025-01-01T00:00:00Z",
};

function mockItemsListLoad() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(client.GET).mockImplementation(async (path: any) => {
    if (path === "/api/definitions") {
      return { data: [defDrill], response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/kinds") {
      return { data: [defDrill.kind], response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/categories") {
      return { data: [], response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/locations") {
      return { data: [], response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/tags") {
      return { data: [], response: new Response(null, { status: 200 }) };
    }
    return { data: null, error: { code: "http.404", message: "Not found" }, response: new Response(null, { status: 404 }) };
  });
}

describe("Write actions — Items list page", () => {
  beforeEach(() => {
    mockItemsListLoad();
  });

  function renderItems(role: "admin" | "member" | "viewer") {
    return render(
      <MemoryRouter initialEntries={["/items"]}>
        <MantineProvider>
          {withAuth(role, (
            <Routes>
              <Route path="/items" element={<Items />} />
            </Routes>
          ))}
        </MantineProvider>
      </MemoryRouter>,
    );
  }

  it("viewer does NOT see the create definition button", async () => {
    renderItems("viewer");
    await waitFor(() => {
      expect(screen.getByText("Cordless Drill")).toBeDefined();
    });
    expect(screen.queryByTestId("create-def-btn")).toBeNull();
  });

  it("viewer does NOT see the per-row edit button", async () => {
    renderItems("viewer");
    await waitFor(() => {
      expect(screen.getByText("Cordless Drill")).toBeDefined();
    });
    expect(screen.queryByTestId(`edit-def-${defDrill.id}`)).toBeNull();
  });

  it("viewer does NOT see the per-row delete button", async () => {
    renderItems("viewer");
    await waitFor(() => {
      expect(screen.getByText("Cordless Drill")).toBeDefined();
    });
    expect(screen.queryByTestId(`delete-def-${defDrill.id}`)).toBeNull();
  });

  it("member SEES the create definition button", async () => {
    renderItems("member");
    await waitFor(() => {
      expect(screen.getByTestId("create-def-btn")).toBeDefined();
    });
  });

  it("member SEES the per-row edit button", async () => {
    renderItems("member");
    await waitFor(() => {
      expect(screen.getByTestId(`edit-def-${defDrill.id}`)).toBeDefined();
    });
  });

  it("admin SEES the create definition button", async () => {
    renderItems("admin");
    await waitFor(() => {
      expect(screen.getByTestId("create-def-btn")).toBeDefined();
    });
  });
});

// ── 5. Write actions hidden for viewer — TreeBrowser ──────────────────────────

const locationTreeFixture = [
  {
    id: 1,
    name: "Home",
    description: null,
    parent_id: null,
    item_instance_id: null,
    container_asset_label: null,
    created_at: "2025-01-01T00:00:00Z",
    children: [],
  },
];

function mockTreeLoad() {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  vi.mocked(client.GET).mockImplementation(async (path: any) => {
    if (path === "/api/locations/tree") {
      return { data: locationTreeFixture, response: new Response(null, { status: 200 }) };
    }
    if (path === "/api/categories/tree") {
      return { data: [], response: new Response(null, { status: 200 }) };
    }
    return { data: null, error: { code: "http.404", message: "Not found" }, response: new Response(null, { status: 404 }) };
  });
}

describe("Write actions — TreeBrowser (Locations)", () => {
  beforeEach(() => {
    mockTreeLoad();
  });

  function renderTree(role: "admin" | "member" | "viewer") {
    return render(
      <MemoryRouter>
        <MantineProvider>
          {withAuth(role, <TreeBrowser resource="locations" />)}
        </MantineProvider>
      </MemoryRouter>,
    );
  }

  it("viewer does NOT see the create-root-btn", async () => {
    renderTree("viewer");
    await waitFor(() => {
      // Wait for tree to load (node name appears)
      expect(screen.getByText("Home")).toBeDefined();
    });
    expect(screen.queryByTestId("create-root-btn")).toBeNull();
  });

  it("member SEES the create-root-btn", async () => {
    renderTree("member");
    await waitFor(() => {
      expect(screen.getByTestId("create-root-btn")).toBeDefined();
    });
  });

  it("admin SEES the create-root-btn", async () => {
    renderTree("admin");
    await waitFor(() => {
      expect(screen.getByTestId("create-root-btn")).toBeDefined();
    });
  });
});

// ── 6. i18n roles namespace parity ────────────────────────────────────────────

describe("i18n roles namespace — en and zh both have admin/member/viewer", () => {
  const requiredKeys = ["admin", "member", "viewer"] as const;

  for (const key of requiredKeys) {
    it(`en/roles has key '${key}'`, () => {
      expect((enRoles as Record<string, string>)[key]).toBeDefined();
      expect((enRoles as Record<string, string>)[key].length).toBeGreaterThan(0);
    });

    it(`zh/roles has key '${key}'`, () => {
      expect((zhRoles as Record<string, string>)[key]).toBeDefined();
      expect((zhRoles as Record<string, string>)[key].length).toBeGreaterThan(0);
    });

    it(`zh/roles '${key}' differs from en (is translated)`, () => {
      expect((zhRoles as Record<string, string>)[key]).not.toBe(
        (enRoles as Record<string, string>)[key],
      );
    });
  }
});

// ── 7. AttachmentPanel write controls gated by EDIT ───────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const attachmentFixture: any = {
  id: 1,
  model_type: "item_definition",
  model_id: 42,
  title: "Test Photo",
  original_filename: "photo.jpg",
  sort_order: 0,
  uploaded_by: null,
  created_at: "2025-01-01T00:00:00Z",
  media: {
    sha256: "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    url: "/media/ab/abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
    content_type: "image/jpeg",
    byte_size: 1000,
    height: 100,
    width: 100,
  },
};

describe("Write controls — AttachmentPanel gated by EDIT", () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (path === "/api/attachments") {
        return { data: [attachmentFixture], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: { code: "http.404", message: "Not found" }, response: new Response(null, { status: 404 }) };
    });
  });

  function renderAttachmentPanel(role: "admin" | "member" | "viewer") {
    return render(
      <MantineProvider>
        {withAuth(role, <AttachmentPanel modelType="item_definition" modelId={42} />)}
      </MantineProvider>,
    );
  }

  it("viewer does NOT see the upload button", async () => {
    renderAttachmentPanel("viewer");
    // Wait for gallery card to appear (loading complete)
    await waitFor(() => {
      expect(screen.getByTestId(`attachment-card-${attachmentFixture.id}`)).toBeDefined();
    });
    expect(screen.queryByTestId("attachment-upload-btn")).toBeNull();
  });

  it("viewer does NOT see the per-attachment delete button", async () => {
    renderAttachmentPanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId(`attachment-card-${attachmentFixture.id}`)).toBeDefined();
    });
    expect(screen.queryByTestId(`attachment-delete-btn-${attachmentFixture.id}`)).toBeNull();
  });

  it("viewer STILL sees the attachment gallery (read-only display)", async () => {
    renderAttachmentPanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId(`attachment-card-${attachmentFixture.id}`)).toBeDefined();
    });
    // Image is rendered (read-only gallery is intact)
    expect(screen.getByTestId(`attachment-img-${attachmentFixture.id}`)).toBeDefined();
  });

  it("member SEES the upload button", async () => {
    renderAttachmentPanel("member");
    await waitFor(() => {
      expect(screen.getByTestId("attachment-upload-btn")).toBeDefined();
    });
  });

  it("member SEES the per-attachment delete button", async () => {
    renderAttachmentPanel("member");
    await waitFor(() => {
      expect(screen.getByTestId(`attachment-delete-btn-${attachmentFixture.id}`)).toBeDefined();
    });
  });

  it("admin SEES the upload button", async () => {
    renderAttachmentPanel("admin");
    await waitFor(() => {
      expect(screen.getByTestId("attachment-upload-btn")).toBeDefined();
    });
  });
});

// ── 8. BarcodePanel write controls gated by EDIT ──────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const barcodeFixture: any = {
  id: 1,
  code: "1234567890",
  label: null,
  symbology: "unknown",
  definition_id: 42,
  created_at: "2025-01-01T00:00:00Z",
};

describe("Write controls — BarcodePanel gated by EDIT", () => {
  beforeEach(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    vi.mocked(client.GET).mockImplementation(async (path: any) => {
      if (path === "/api/definitions/{definition_id}/barcodes") {
        return { data: [barcodeFixture], response: new Response(null, { status: 200 }) };
      }
      return { data: null, error: { code: "http.404", message: "Not found" }, response: new Response(null, { status: 404 }) };
    });
  });

  function renderBarcodePanel(role: "admin" | "member" | "viewer") {
    return render(
      <MantineProvider>
        {withAuth(role, <BarcodePanel definitionId={42} />)}
      </MantineProvider>,
    );
  }

  it("viewer does NOT see the add-barcode button", async () => {
    renderBarcodePanel("viewer");
    // Wait for barcode row to appear (loading complete)
    await waitFor(() => {
      expect(screen.getByTestId(`barcode-row-${barcodeFixture.id}`)).toBeDefined();
    });
    expect(screen.queryByTestId("add-barcode-btn")).toBeNull();
  });

  it("viewer does NOT see the per-row remove button", async () => {
    renderBarcodePanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId(`barcode-row-${barcodeFixture.id}`)).toBeDefined();
    });
    expect(screen.queryByTestId(`remove-barcode-${barcodeFixture.id}`)).toBeNull();
  });

  it("viewer STILL sees the barcode list (read-only display)", async () => {
    renderBarcodePanel("viewer");
    await waitFor(() => {
      expect(screen.getByTestId(`barcode-row-${barcodeFixture.id}`)).toBeDefined();
    });
    // Barcode code text is rendered
    expect(screen.getByTestId(`barcode-code-${barcodeFixture.id}`)).toBeDefined();
  });

  it("member SEES the add-barcode button", async () => {
    renderBarcodePanel("member");
    await waitFor(() => {
      expect(screen.getByTestId("add-barcode-btn")).toBeDefined();
    });
  });

  it("member SEES the per-row remove button", async () => {
    renderBarcodePanel("member");
    await waitFor(() => {
      expect(screen.getByTestId(`remove-barcode-${barcodeFixture.id}`)).toBeDefined();
    });
  });

  it("admin SEES the add-barcode button", async () => {
    renderBarcodePanel("admin");
    await waitFor(() => {
      expect(screen.getByTestId("add-barcode-btn")).toBeDefined();
    });
  });
});

// ── 9. UserButton role label ──────────────────────────────────────────────────

describe("UserButton — role label (Step 8)", () => {
  beforeEach(() => {
    // LanguageSwitcher calls PATCH on language change; mock it to avoid unhandled calls.
    vi.mocked(client.PATCH).mockResolvedValue(
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      { data: undefined, error: undefined, response: new Response(null, { status: 200 }) } as any,
    );
  });

  it("renders localized role label 'Admin' for admin", async () => {
    render(
      <MantineProvider>
        {withAuth("admin", (
          <UserButton email="admin@example.com" onLogout={vi.fn()} />
        ))}
      </MantineProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("user-role-label")).toBeDefined();
    });
    expect(screen.getByTestId("user-role-label").textContent).toBe("Admin");
  });

  it("renders localized role label 'Viewer' for viewer", async () => {
    render(
      <MantineProvider>
        {withAuth("viewer", (
          <UserButton email="viewer@example.com" onLogout={vi.fn()} />
        ))}
      </MantineProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("user-role-label")).toBeDefined();
    });
    expect(screen.getByTestId("user-role-label").textContent).toBe("Viewer");
  });

  it("renders localized role label 'Member' for member", async () => {
    render(
      <MantineProvider>
        {withAuth("member", (
          <UserButton email="member@example.com" onLogout={vi.fn()} />
        ))}
      </MantineProvider>,
    );
    await waitFor(() => {
      expect(screen.getByTestId("user-role-label")).toBeDefined();
    });
    expect(screen.getByTestId("user-role-label").textContent).toBe("Member");
  });
});
