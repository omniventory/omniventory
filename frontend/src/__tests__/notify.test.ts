/**
 * Unit tests for the notify.ts helper (Step 9 — toast success feedback).
 *
 * Verifies that notifySuccess and notifyError call notifications.show() with
 * the expected config (color, autoClose).  We mock @mantine/notifications so
 * these tests run in jsdom without needing the <Notifications> container.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// ── Mock @mantine/notifications ───────────────────────────────────────────────
// vi.mock is hoisted to the top of the file by Vitest, so variables declared
// outside the factory are not yet initialized.  Use vi.hoisted() to create
// the spy in the hoisted scope.

const { mockShow } = vi.hoisted(() => ({ mockShow: vi.fn() }));

vi.mock("@mantine/notifications", () => ({
  notifications: {
    show: mockShow,
  },
}));

// Import AFTER mock is set up
import { notifySuccess, notifyError } from "../components/notify";

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("notifySuccess", () => {
  beforeEach(() => {
    mockShow.mockClear();
  });

  it("calls notifications.show with the provided message", () => {
    notifySuccess("Item created.");
    expect(mockShow).toHaveBeenCalledTimes(1);
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["message"]).toBe("Item created.");
  });

  it("uses teal color for success", () => {
    notifySuccess("Item created.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["color"]).toBe("teal");
  });

  it("sets a positive autoClose (ms)", () => {
    notifySuccess("Item created.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(typeof args["autoClose"]).toBe("number");
    expect(args["autoClose"] as number).toBeGreaterThan(0);
  });

  it("includes an icon", () => {
    notifySuccess("Item created.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["icon"]).toBeDefined();
  });
});

describe("notifyError", () => {
  beforeEach(() => {
    mockShow.mockClear();
  });

  it("calls notifications.show with the provided message", () => {
    notifyError("Something went wrong.");
    expect(mockShow).toHaveBeenCalledTimes(1);
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["message"]).toBe("Something went wrong.");
  });

  it("uses red color for error", () => {
    notifyError("Something went wrong.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["color"]).toBe("red");
  });

  it("sets a positive autoClose (ms)", () => {
    notifyError("Something went wrong.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(typeof args["autoClose"]).toBe("number");
    expect(args["autoClose"] as number).toBeGreaterThan(0);
  });

  it("includes an icon", () => {
    notifyError("Something went wrong.");
    const args = mockShow.mock.calls[0][0] as Record<string, unknown>;
    expect(args["icon"]).toBeDefined();
  });
});

describe("notifySuccess vs notifyError — config differs", () => {
  beforeEach(() => {
    mockShow.mockClear();
  });

  it("success and error use different colors", () => {
    notifySuccess("ok");
    notifyError("fail");
    const successArgs = mockShow.mock.calls[0][0] as Record<string, unknown>;
    const errorArgs = mockShow.mock.calls[1][0] as Record<string, unknown>;
    expect(successArgs["color"]).not.toBe(errorArgs["color"]);
  });
});
