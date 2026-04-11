import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sparkline } from "@/components/ui/sparkline";

describe("Sparkline", () => {
  it("renders em-dash placeholder for empty series", () => {
    render(<Sparkline series={[]} />);
    const el = screen.getByTestId("sparkline");
    expect(el.textContent).toBe("—");
    expect(el.tagName.toLowerCase()).toBe("span");
  });

  it("renders em-dash placeholder for single-point series", () => {
    render(<Sparkline series={[100]} />);
    expect(screen.getByTestId("sparkline").textContent).toBe("—");
  });

  it("renders SVG polyline for valid series", () => {
    render(<Sparkline series={[100, 105, 110, 108, 115, 120]} />);
    const el = screen.getByTestId("sparkline");
    expect(el.tagName.toLowerCase()).toBe("svg");
    // Polyline child with `points` attribute
    const polyline = el.querySelector("polyline");
    expect(polyline).not.toBeNull();
    expect(polyline?.getAttribute("points")).toBeTruthy();
  });

  it("marks direction=up for ascending series", () => {
    render(<Sparkline series={[100, 110, 120]} />);
    expect(screen.getByTestId("sparkline")).toHaveAttribute("data-direction", "up");
  });

  it("marks direction=down for descending series", () => {
    render(<Sparkline series={[120, 110, 100]} />);
    expect(screen.getByTestId("sparkline")).toHaveAttribute("data-direction", "down");
  });

  it("marks direction=up for flat series ending ≥ starting", () => {
    render(<Sparkline series={[100, 100, 100]} />);
    expect(screen.getByTestId("sparkline")).toHaveAttribute("data-direction", "up");
  });

  it("handles flat series without divide-by-zero", () => {
    render(<Sparkline series={[100, 100, 100, 100]} />);
    const el = screen.getByTestId("sparkline");
    const polyline = el.querySelector("polyline");
    expect(polyline).not.toBeNull();
    // All y coordinates should be the mid-height (no NaN)
    const points = polyline!.getAttribute("points") || "";
    expect(points).not.toContain("NaN");
  });

  it("uses custom width and height when provided", () => {
    render(<Sparkline series={[1, 2, 3]} width={120} height={30} />);
    const el = screen.getByTestId("sparkline");
    expect(el).toHaveAttribute("width", "120");
    expect(el).toHaveAttribute("height", "30");
  });

  it("has accessible role + aria-label", () => {
    render(<Sparkline series={[1, 2, 3]} />);
    const el = screen.getByTestId("sparkline");
    expect(el).toHaveAttribute("role", "img");
    expect(el.getAttribute("aria-label")).toMatch(/30일 추세/);
  });

  it("polyline has the correct number of points", () => {
    render(<Sparkline series={[1, 2, 3, 4, 5]} />);
    const polyline = screen.getByTestId("sparkline").querySelector("polyline");
    const points = (polyline!.getAttribute("points") || "").trim().split(/\s+/);
    expect(points).toHaveLength(5);
  });
});
