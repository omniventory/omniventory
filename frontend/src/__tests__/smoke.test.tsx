/**
 * App smoke test — ensures the root component renders without crashing.
 *
 * App.tsx calls the API on mount, so we mock the typed client.
 * Using vi.mock rather than stubbing globalThis.fetch because openapi-fetch
 * captures globalThis.fetch at createClient() time.
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { MantineProvider } from "@mantine/core";
import App from "../App.js";

vi.mock("../api/client.js", () => ({
  client: {
    GET: vi.fn().mockResolvedValue({
      error: { detail: "Not authenticated" },
      response: new Response(null, { status: 401 }),
    }),
    POST: vi.fn(),
  },
}));

describe("App smoke test", () => {
  it("renders without crashing and shows Login when unauthenticated", async () => {
    render(
      <MantineProvider>
        <App />
      </MantineProvider>,
    );
    // After the auth check resolves with 401, the Login form should appear
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign in/i })).toBeDefined();
    });
  });
});
