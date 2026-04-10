import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusBadge } from "@/components/ui/status-badge";

describe("StatusBadge", () => {
  // ─── Known statuses ─────────────────────────────────
  const greenStatuses = ["BUY", "LONG", "READY", "AGGRESSIVE", "bounce", "gap_up"];
  const redStatuses = ["SELL", "SHORT", "BLOCKED", "DEFENSIVE", "gap_down"];
  const amberStatuses = ["REDUCE", "CAUTIOUS", "volume_spike"];
  const blueStatuses = ["WATCH", "momentum"];
  const zincStatuses = ["HOLD", "NEUTRAL"];
  const purpleStatuses = ["breakout"];

  it.each(greenStatuses)("renders %s with emerald style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-emerald-400");
  });

  it.each(redStatuses)("renders %s with red style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-red-400");
  });

  it.each(amberStatuses)("renders %s with amber style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-amber-400");
  });

  it.each(blueStatuses)("renders %s with blue style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-blue-400");
  });

  it.each(zincStatuses)("renders %s with muted style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-muted-foreground");
  });

  it.each(purpleStatuses)("renders %s with purple style", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByText(status);
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-purple-400");
  });

  // ─── Unknown / fallback ──────────────────────────────
  it("renders unknown status with fallback muted style", () => {
    render(<StatusBadge status="UNKNOWN_STATUS" />);
    const badge = screen.getByText("UNKNOWN_STATUS");
    expect(badge).toBeInTheDocument();
    expect(badge.className).toContain("text-muted-foreground");
    expect(badge.className).toContain("bg-muted/50");
  });

  it("renders empty string status with fallback style", () => {
    render(<StatusBadge status="" />);
    const { container } = render(<StatusBadge status="" />);
    const span = container.querySelector("span");
    expect(span).not.toBeNull();
    expect(span!.className).toContain("bg-muted/50");
  });

  // ─── Size variants ───────────────────────────────────
  it("defaults to sm size", () => {
    render(<StatusBadge status="BUY" />);
    const badge = screen.getByText("BUY");
    expect(badge.className).toContain("text-[10px]");
    expect(badge.className).toContain("px-1.5");
  });

  it("applies md size", () => {
    render(<StatusBadge status="SELL" size="md" />);
    const badge = screen.getByText("SELL");
    expect(badge.className).toContain("text-xs");
    expect(badge.className).toContain("px-2");
  });

  it("applies lg size", () => {
    render(<StatusBadge status="AGGRESSIVE" size="lg" />);
    const badge = screen.getByText("AGGRESSIVE");
    expect(badge.className).toContain("text-sm");
    expect(badge.className).toContain("px-3");
    expect(badge.className).toContain("py-1");
  });

  // ─── Common styles ───────────────────────────────────
  it("always includes rounded-md and border", () => {
    render(<StatusBadge status="BUY" />);
    const badge = screen.getByText("BUY");
    expect(badge.className).toContain("rounded-md");
    expect(badge.className).toContain("border");
  });

  it("always includes font-medium", () => {
    render(<StatusBadge status="HOLD" />);
    const badge = screen.getByText("HOLD");
    expect(badge.className).toContain("font-medium");
  });

  it("always uses inline-flex layout", () => {
    render(<StatusBadge status="WATCH" />);
    const badge = screen.getByText("WATCH");
    expect(badge.className).toContain("inline-flex");
  });

  // ─── All 19 known statuses render correctly ──────────
  const allStatuses = [
    "BUY", "SELL", "HOLD", "WATCH", "LONG", "SHORT", "REDUCE",
    "READY", "BLOCKED", "AGGRESSIVE", "NEUTRAL", "CAUTIOUS", "DEFENSIVE",
    "breakout", "momentum", "bounce", "volume_spike", "gap_up", "gap_down",
  ];

  it.each(allStatuses)("renders %s as the badge text content", (status) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(status)).toBeInTheDocument();
  });
});
