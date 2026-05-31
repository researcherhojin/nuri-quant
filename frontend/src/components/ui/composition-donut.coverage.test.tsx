import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { CompositionDonut, type DonutSlice } from "./composition-donut";

// recharts mock — keep in this dedicated file (hoist gotcha: vi.mock("recharts")
// affects every dynamic import in the same vitest worker). The Tooltip mock
// captures the `formatter` prop so we can invoke it directly and execute the
// formatter body (composition-donut.tsx lines 87-88).
let capturedFormatter:
  | ((value: unknown, name: unknown) => [string, string])
  | null = null;

vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  PieChart: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="pie-chart">{children}</div>
  ),
  Pie: ({ children }: { children: React.ReactNode }) => (
    <div data-testid="pie">{children}</div>
  ),
  Cell: () => <div data-testid="cell" />,
  Tooltip: (props: {
    formatter?: (value: unknown, name: unknown) => [string, string];
  }) => {
    capturedFormatter = props.formatter ?? null;
    return <div data-testid="tooltip" />;
  },
}));

const SLICES: DonutSlice[] = [
  { label: "AAPL", value: 60, color: "#10b981" },
  { label: "MSFT", value: 40, color: "#3b82f6" },
];

describe("CompositionDonut", () => {
  beforeEach(() => {
    capturedFormatter = null;
    vi.clearAllMocks();
  });

  it("renders the empty placeholder when there are no slices", () => {
    render(<CompositionDonut slices={[]} />);
    expect(screen.getByTestId("composition-donut-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("composition-donut")).not.toBeInTheDocument();
  });

  it("renders the donut and a Cell per slice when slices are present", () => {
    render(<CompositionDonut slices={SLICES} />);
    expect(screen.getByTestId("composition-donut")).toBeInTheDocument();
    expect(screen.getByTestId("pie-chart")).toBeInTheDocument();
    expect(screen.getAllByTestId("cell")).toHaveLength(SLICES.length);
  });

  it("renders the center labels when provided", () => {
    render(
      <CompositionDonut
        slices={SLICES}
        centerLabel="$10,000"
        centerSubLabel="Total"
      />,
    );
    expect(screen.getByTestId("composition-donut-center")).toBeInTheDocument();
    expect(screen.getByText("$10,000")).toBeInTheDocument();
    expect(screen.getByText("Total")).toBeInTheDocument();
  });

  it("omits the center overlay when no center labels are provided", () => {
    render(<CompositionDonut slices={SLICES} />);
    expect(
      screen.queryByTestId("composition-donut-center"),
    ).not.toBeInTheDocument();
  });

  it("formats a numeric tooltip value as a percentage (lines 87-88)", () => {
    render(<CompositionDonut slices={SLICES} />);
    expect(capturedFormatter).toBeTruthy();
    // numeric branch: typeof value === "number" → kept as-is, Number.isFinite true
    expect(capturedFormatter!(42.345, "AAPL")).toEqual(["42.3%", "AAPL"]);
  });

  it("coerces a numeric string tooltip value via Number() then formats it", () => {
    render(<CompositionDonut slices={SLICES} />);
    expect(capturedFormatter).toBeTruthy();
    // non-number branch: Number("12.5") → 12.5, finite → "12.5%"
    expect(capturedFormatter!("12.5", "MSFT")).toEqual(["12.5%", "MSFT"]);
  });

  it("renders an em dash when the tooltip value is not finite", () => {
    render(<CompositionDonut slices={SLICES} />);
    expect(capturedFormatter).toBeTruthy();
    // non-finite branch: Number("abc") → NaN → "—"
    expect(capturedFormatter!("abc", "AAPL")).toEqual(["—", "AAPL"]);
  });
});
