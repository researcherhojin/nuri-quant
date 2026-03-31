import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Mock the useStream hook at module level
const mockStreamData = vi.fn();
vi.mock("@/lib/use-stream", () => ({
  useStream: () => mockStreamData(),
}));

import { LiveIndicator } from "@/components/ui/live-indicator";

describe("LiveIndicator", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders nothing when no stream data", () => {
    mockStreamData.mockReturnValue(null);
    const { container } = render(<LiveIndicator />);
    expect(container.innerHTML).toBe("");
  });

  it("renders regime and macro score when data available", () => {
    mockStreamData.mockReturnValue({
      regime: "bull_low_vol",
      macro_score: 72,
      vix: 15.5,
    });
    render(<LiveIndicator />);
    expect(screen.getByText("bull_low_vol")).toBeInTheDocument();
    expect(screen.getByText("M72")).toBeInTheDocument();
    expect(screen.getByText("VIX 15.5")).toBeInTheDocument();
  });

  it("renders partial data (regime only)", () => {
    mockStreamData.mockReturnValue({ regime: "bear_high_vol" });
    render(<LiveIndicator />);
    expect(screen.getByText("bear_high_vol")).toBeInTheDocument();
  });

  it("renders with vix only", () => {
    mockStreamData.mockReturnValue({ vix: 25.3 });
    render(<LiveIndicator />);
    expect(screen.getByText("VIX 25.3")).toBeInTheDocument();
  });
});
