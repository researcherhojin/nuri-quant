import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { FreshnessBar } from "@/components/ui/freshness-bar";
import type { FreshnessItem } from "@/components/ui/freshness-bar";

function makeItem(overrides: Partial<FreshnessItem> = {}): FreshnessItem {
  return {
    key: "prices",
    label: "Prices",
    status: "PASS",
    age_hours: 2,
    message: "Updated 2h ago",
    ...overrides,
  };
}

describe("FreshnessBar", () => {
  // ─── Null/empty handling ─────────────────────────────
  it("returns null for empty items array", () => {
    const { container } = render(<FreshnessBar items={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("returns null for null items", () => {
    // @ts-expect-error Testing null input
    const { container } = render(<FreshnessBar items={null} />);
    expect(container.innerHTML).toBe("");
  });

  it("returns null for undefined items", () => {
    // @ts-expect-error Testing undefined input
    const { container } = render(<FreshnessBar items={undefined} />);
    expect(container.innerHTML).toBe("");
  });

  // ─── Status styles ──────────────────────────────────
  it("renders PASS status with emerald style", () => {
    render(<FreshnessBar items={[makeItem({ status: "PASS" })]} />);
    expect(screen.getByText("Prices")).toBeInTheDocument();
    const label = screen.getByText("Prices");
    expect(label.className).toContain("text-emerald-400");
  });

  it("renders WARN status with amber style", () => {
    render(
      <FreshnessBar items={[makeItem({ key: "vix", label: "VIX", status: "WARN", age_hours: 30 })]} />
    );
    const label = screen.getByText("VIX");
    expect(label.className).toContain("text-amber-400");
  });

  it("renders FAIL status with red style", () => {
    render(
      <FreshnessBar
        items={[makeItem({ key: "consensus", label: "Consensus", status: "FAIL", age_hours: 72 })]}
      />
    );
    const label = screen.getByText("Consensus");
    expect(label.className).toContain("text-red-400");
  });

  // ─── Status icons ───────────────────────────────────
  it("shows checkmark icon for PASS", () => {
    render(<FreshnessBar items={[makeItem({ status: "PASS" })]} />);
    expect(screen.getByText("\u2713")).toBeInTheDocument(); // FINDING-002: 이모지→글리프
  });

  it("shows warning icon for WARN", () => {
    render(<FreshnessBar items={[makeItem({ status: "WARN" })]} />);
    expect(screen.getByText("\u25B3")).toBeInTheDocument();
  });

  it("shows cross icon for FAIL", () => {
    render(<FreshnessBar items={[makeItem({ status: "FAIL" })]} />);
    expect(screen.getByText("\u2715")).toBeInTheDocument();
  });

  // ─── Age formatting ─────────────────────────────────
  it("formats age < 1 hour as '<1h'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 0.5 })]} />);
    expect(screen.getByText("<1h")).toBeInTheDocument();
  });

  it("formats age 0 as '<1h'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 0 })]} />);
    expect(screen.getByText("<1h")).toBeInTheDocument();
  });

  it("formats age in hours (< 24)", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 5 })]} />);
    expect(screen.getByText("5h")).toBeInTheDocument();
  });

  it("rounds fractional hours", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 2.7 })]} />);
    expect(screen.getByText("3h")).toBeInTheDocument();
  });

  it("formats age in days (>= 24)", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 48 })]} />);
    expect(screen.getByText("2d")).toBeInTheDocument();
  });

  it("formats partial days (floors to days)", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 36 })]} />);
    expect(screen.getByText("1d")).toBeInTheDocument();
  });

  it("formats age >= 9000 as 'N/A'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 9000 })]} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("formats age exactly 9000 as 'N/A'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 9000 })]} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("formats age > 9000 as 'N/A'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 99999 })]} />);
    expect(screen.getByText("N/A")).toBeInTheDocument();
  });

  it("formats exactly 24 hours as '1d'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 24 })]} />);
    expect(screen.getByText("1d")).toBeInTheDocument();
  });

  it("formats exactly 1 hour as '1h'", () => {
    render(<FreshnessBar items={[makeItem({ age_hours: 1 })]} />);
    expect(screen.getByText("1h")).toBeInTheDocument();
  });

  // ─── Multiple items ─────────────────────────────────
  it("renders multiple freshness items", () => {
    const items: FreshnessItem[] = [
      makeItem({ key: "prices", label: "Prices", status: "PASS", age_hours: 2 }),
      makeItem({ key: "vix", label: "VIX", status: "WARN", age_hours: 30 }),
      makeItem({ key: "fg", label: "F&G", status: "FAIL", age_hours: 72 }),
    ];
    render(<FreshnessBar items={items} />);
    expect(screen.getByText("Prices")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("F&G")).toBeInTheDocument();
  });

  // ─── Title attribute (tooltip) ──────────────────────
  it("sets title attribute from message for tooltip", () => {
    render(
      <FreshnessBar
        items={[makeItem({ message: "Last updated 2 hours ago" })]}
      />
    );
    const wrapper = screen.getByTitle("Last updated 2 hours ago");
    expect(wrapper).toBeInTheDocument();
  });

  // ─── Unknown status fallback ────────────────────────
  it("falls back to FAIL style for unknown status", () => {
    render(
      <FreshnessBar
        // @ts-expect-error Testing unknown status
        items={[makeItem({ status: "UNKNOWN" })]}
      />
    );
    const label = screen.getByText("Prices");
    // Falls back to statusStyles.FAIL
    expect(label.className).toContain("text-red-400");
  });
});
