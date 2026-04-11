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
    expect(el.getAttribute("aria-label")).toMatch(/추세/);
  });

  it("renders baseline reference line when baseline is within series range", () => {
    render(<Sparkline series={[100, 110, 120, 130]} baseline={115} />);
    const baseline = screen.getByTestId("sparkline-baseline");
    expect(baseline).toBeInTheDocument();
    expect(baseline.tagName.toLowerCase()).toBe("line");
  });

  it("omits baseline when outside series range", () => {
    render(<Sparkline series={[100, 110, 120]} baseline={50} />);
    expect(screen.queryByTestId("sparkline-baseline")).not.toBeInTheDocument();
  });

  it("omits baseline when null or undefined", () => {
    render(<Sparkline series={[100, 110, 120]} />);
    expect(screen.queryByTestId("sparkline-baseline")).not.toBeInTheDocument();
  });

  it("omits baseline for flat series (range === 0)", () => {
    render(<Sparkline series={[100, 100, 100]} baseline={100} />);
    // Flat series → range is 0 → baseline can't be positioned meaningfully → omitted
    expect(screen.queryByTestId("sparkline-baseline")).not.toBeInTheDocument();
  });

  it("polyline has the correct number of points", () => {
    render(<Sparkline series={[1, 2, 3, 4, 5]} />);
    const polyline = screen.getByTestId("sparkline").querySelector("polyline");
    const points = (polyline!.getAttribute("points") || "").trim().split(/\s+/);
    expect(points).toHaveLength(5);
  });
});
