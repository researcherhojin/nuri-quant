import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Metric } from "@/components/ui/metric";

describe("Metric", () => {
  it("renders label and value", () => {
    render(<Metric label="VIX" value="15.3" />);
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("15.3")).toBeInTheDocument();
  });

  it("renders numeric value", () => {
    render(<Metric label="Score" value={85} />);
    expect(screen.getByText("85")).toBeInTheDocument();
  });

  it("does not render sub text when not provided", () => {
    const { container } = render(<Metric label="VIX" value="15" />);
    // label p + value p = 2 p tags
    const paragraphs = container.querySelectorAll("p");
    expect(paragraphs).toHaveLength(2);
  });

  it("renders sub text when provided", () => {
    render(<Metric label="Return" value="+12%" sub="Since inception" />);
    expect(screen.getByText("Since inception")).toBeInTheDocument();
    // label p + value p + sub p = 3 p tags
  });

  // ─── Color variants ──────────────────────────────
  it("applies green color class", () => {
    render(<Metric label="PnL" value="+5%" color="green" />);
    const valueEl = screen.getByText("+5%");
    expect(valueEl.className).toContain("text-emerald-400");
  });

  it("applies red color class", () => {
    render(<Metric label="PnL" value="-3%" color="red" />);
    const valueEl = screen.getByText("-3%");
    expect(valueEl.className).toContain("text-red-400");
  });

  it("applies default color class (text-zinc-200)", () => {
    render(<Metric label="Price" value="$168" />);
    const valueEl = screen.getByText("$168");
    expect(valueEl.className).toContain("text-zinc-200");
  });

  it("applies default color explicitly", () => {
    render(<Metric label="Price" value="$168" color="default" />);
    const valueEl = screen.getByText("$168");
    expect(valueEl.className).toContain("text-zinc-200");
  });

  // ─── Size variants ───────────────────────────────
  it("applies sm size by default", () => {
    render(<Metric label="Score" value="75" />);
    const valueEl = screen.getByText("75");
    expect(valueEl.className).toContain("text-sm");
  });

  it("applies lg size", () => {
    render(<Metric label="Total" value="$1.2M" size="lg" />);
    const valueEl = screen.getByText("$1.2M");
    expect(valueEl.className).toContain("text-xl");
  });

  // ─── Label styling ───────────────────────────────
  it("label has uppercase tracking and small text", () => {
    render(<Metric label="VIX" value="15" />);
    const labelEl = screen.getByText("VIX");
    expect(labelEl.className).toContain("text-[10px]");
    expect(labelEl.className).toContain("uppercase");
    expect(labelEl.className).toContain("tracking-wider");
  });

  // ─── Combination tests ────────────────────────────
  it("renders green + lg + sub together", () => {
    render(<Metric label="Gain" value="+25%" color="green" size="lg" sub="YTD" />);
    const valueEl = screen.getByText("+25%");
    expect(valueEl.className).toContain("text-emerald-400");
    expect(valueEl.className).toContain("text-xl");
    expect(screen.getByText("YTD")).toBeInTheDocument();
  });

  it("renders red + sm (default) + no sub", () => {
    render(<Metric label="Loss" value="-7%" color="red" />);
    const valueEl = screen.getByText("-7%");
    expect(valueEl.className).toContain("text-red-400");
    expect(valueEl.className).toContain("text-sm");
  });

  it("value element has font-semibold", () => {
    render(<Metric label="Test" value="100" />);
    const valueEl = screen.getByText("100");
    expect(valueEl.className).toContain("font-semibold");
  });
});
