import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import App from "../App.js";

describe("App smoke test", () => {
  it("renders without crashing", () => {
    render(<App />);
    expect(screen.getByText("Omniventory")).toBeDefined();
  });
});
