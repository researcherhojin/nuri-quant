/**
 * Coverage test for interactive-backtest-lazy.tsx (force 100% statements).
 *
 * The file is a thin next/dynamic wrapper. The uncovered lines are the dynamic
 * loader callback (the `() => import(...).then(m => m.InteractiveBacktest)`) and
 * the `loading` fallback JSX (the animate-pulse skeleton). To execute both we
 * mock next/dynamic so the test can CAPTURE and INVOKE the loader + loading
 * callbacks the source passes in.
 *
 * The underlying interactive-backtest module is mocked so the loader resolves
 * without importing recharts (avoids the vi.mock("recharts") hoist gotcha — the
 * mock lives only in this dedicated file).
 *
 * `captured` is created via vi.hoisted so it exists when the hoisted vi.mock
 * factory runs (a plain const would throw "Cannot access before initialization").
 */
import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";

type DynamicLoader = () => Promise<unknown>;
type DynamicOptions = {
  ssr?: boolean;
  loading?: () => React.ReactElement;
};

const captured = vi.hoisted(() => {
  return {} as { loader?: DynamicLoader; options?: DynamicOptions };
});

// Mock the heavy chart module so the dynamic loader resolves cheaply.
vi.mock("@/components/ui/interactive-backtest", () => ({
  InteractiveBacktest: (props: Record<string, unknown>) => (
    <div data-testid="interactive-backtest-loaded" data-props={JSON.stringify(props)} />
  ),
}));

// Capture the loader + options next/dynamic is called with so we can exercise
// the callbacks defined inline in the source module, then render the loading
// fallback on a normal mount.
vi.mock("next/dynamic", () => ({
  default: (loader: DynamicLoader, options: DynamicOptions) => {
    captured.loader = loader;
    captured.options = options;
    const Resolved = () => (options.loading ? options.loading() : null);
    Resolved.displayName = "MockDynamic";
    return Resolved;
  },
}));

import { InteractiveBacktestLazy } from "@/components/ui/interactive-backtest-lazy";

const SAMPLE_DATA = [
  { date: "2024-01-01", strategy: 100, spy: 100, drawdown: 0 },
  { date: "2024-02-01", strategy: 110, spy: 105, drawdown: -2 },
];

describe("InteractiveBacktestLazy", () => {
  it("renders the loading fallback while the chart is lazy-loaded", () => {
    render(<InteractiveBacktestLazy initialData={SAMPLE_DATA} />);
    const loading = screen.getByTestId("interactive-backtest-loading");
    expect(loading).toBeInTheDocument();
    expect(loading).toHaveClass("animate-pulse");
  });

  it("configures next/dynamic with ssr disabled and a loading callback", () => {
    expect(captured.options).toBeDefined();
    expect(captured.options?.ssr).toBe(false);
    expect(typeof captured.options?.loading).toBe("function");
  });

  it("loading callback returns the skeleton element", () => {
    const el = captured.options?.loading?.() as React.ReactElement<{
      "data-testid": string;
    }>;
    expect(el).toBeTruthy();
    expect(el.props["data-testid"]).toBe("interactive-backtest-loading");
  });

  it("dynamic loader resolves the InteractiveBacktest named export", async () => {
    expect(captured.loader).toBeDefined();
    const Comp = (await captured.loader!()) as React.ComponentType<
      Record<string, unknown>
    >;
    render(<Comp data-testid="loader-result" />);
    expect(screen.getByTestId("interactive-backtest-loaded")).toBeInTheDocument();
  });
});
