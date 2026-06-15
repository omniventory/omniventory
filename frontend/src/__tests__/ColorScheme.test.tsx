/**
 * Color-scheme toggle tests.
 *
 * Verifies that the AppShell header renders a color-scheme toggle button and
 * that clicking it doesn't crash (full OS-level integration test is a manual
 * walkthrough step; here we confirm the control is present + interactive).
 *
 * We mock the typed API client module directly (not fetch) because openapi-fetch
 * captures globalThis.fetch at createClient() time, so stubbing fetch after the
 * module loads has no effect.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import App from "../App.js";

/** Mock the typed client module. */
vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn(),
    POST: vi.fn(),
  },
}));

import { client } from "../api/client.js";

describe("Color-scheme toggle", () => {
  beforeEach(() => {
    // Return 200 so the shell is rendered (the toggle lives in the shell header)
    vi.mocked(client.GET).mockResolvedValue({
      data: {
        user: {
          id: 1,
          email: "admin@example.com",
          role: "admin",
          is_active: true,
          created_at: "2025-01-01T00:00:00Z",
        },
      },
      response: new Response(null, { status: 200 }),
    });
    vi.mocked(client.POST).mockResolvedValue({
      data: { message: "Logged out" },
      response: new Response(null, { status: 200 }),
    });
  });

  it("renders the color-scheme toggle button in the shell header", async () => {
    render(
      <MantineProvider>
        <App />
      </MantineProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /toggle color scheme/i }),
      ).toBeDefined();
    });
  });

  it("toggle button is clickable without throwing", async () => {
    render(
      <MantineProvider>
        <App />
      </MantineProvider>,
    );
    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: /toggle color scheme/i }),
      ).toBeDefined();
    });
    // Click the toggle — should not throw
    fireEvent.click(
      screen.getByRole("button", { name: /toggle color scheme/i }),
    );
  });
});
