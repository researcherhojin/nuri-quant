import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import "@testing-library/jest-dom";
import { BacktestSliders } from "./backtest-sliders";

// backtest-sliders.tsx 는 recharts 의존이 없어 recharts-mock hoist gotcha 비해당.
// 별도 coverage 파일로 두어 hoist 격리 규칙은 안전하게 준수한다.

describe("BacktestSliders coverage", () => {
  beforeEach(() => {
    cleanup();
  });

  // 두 Slider 모두 range input 으로 렌더되므로 label span 으로 매칭한 뒤
  // 형제 input 을 찾아 change 를 발생시킨다 (line 79 Stop + line 80 Take onChange 커버).
  function rangeFor(label: string): HTMLInputElement {
    const labelSpan = screen.getByText(label);
    const input = labelSpan.parentElement?.querySelector<HTMLInputElement>(
      'input[type="range"]'
    );
    if (!input) throw new Error(`range input for ${label} not found`);
    return input;
  }

  it("Take 슬라이더 onChange 가 takeProfit 을 갱신한다 (line 80)", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);

    // 기본 takeProfit=20 표시 확인
    expect(screen.getByText("20%")).toBeInTheDocument();

    const takeInput = rangeFor("Take");
    fireEvent.change(takeInput, { target: { value: "35" } });

    // update("takeProfit", v) 가 실행되어 상태가 35% 로 반영됨
    expect(screen.getByText("35%")).toBeInTheDocument();

    // 갱신된 값이 onRun 으로 전달되는지 확인
    fireEvent.click(screen.getByText("Run Backtest"));
    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ takeProfit: 35 })
    );
  });

  it("Stop 슬라이더 onChange 가 stopLoss 를 갱신한다 (line 79)", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);

    expect(screen.getByText("-7%")).toBeInTheDocument();

    const stopInput = rangeFor("Stop");
    fireEvent.change(stopInput, { target: { value: "-12" } });

    expect(screen.getByText("-12%")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Run Backtest"));
    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ stopLoss: -12 })
    );
  });

  it("SMA period 버튼이 smaPeriod 를 갱신한다", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);

    fireEvent.click(screen.getByText("SMA 200"));
    fireEvent.click(screen.getByText("Run Backtest"));

    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ smaPeriod: 200 })
    );
  });

  it("lookback 버튼이 lookback 을 갱신한다", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);

    fireEvent.click(screen.getByText("5Y"));
    fireEvent.click(screen.getByText("Run Backtest"));

    expect(onRun).toHaveBeenCalledWith(
      expect.objectContaining({ lookback: "5Y" })
    );
  });

  it("비-기본값일 때 Reset defaults 가 노출되고 기본값으로 되돌린다", () => {
    const onRun = vi.fn();
    render(
      <BacktestSliders
        onRun={onRun}
        initialParams={{
          smaPeriod: 100,
          lookback: "1Y",
          stopLoss: -10,
          takeProfit: 40,
        }}
      />
    );

    // 비-기본값이므로 isDefault=false → Reset 버튼 노출
    const reset = screen.getByText("Reset defaults");
    expect(reset).toBeInTheDocument();

    fireEvent.click(reset);

    // DEFAULT_PARAMS 로 되돌아가면 Reset 버튼이 사라진다 (isDefault=true)
    expect(screen.queryByText("Reset defaults")).not.toBeInTheDocument();
    // 기본 stop -7% / take 20% 표시 확인
    expect(screen.getByText("-7%")).toBeInTheDocument();
    expect(screen.getByText("20%")).toBeInTheDocument();
  });

  it("기본값일 때는 Reset defaults 버튼이 보이지 않는다", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} />);
    expect(screen.queryByText("Reset defaults")).not.toBeInTheDocument();
  });

  it("loading=true 면 버튼이 비활성화되고 라벨이 Running... 이다", () => {
    const onRun = vi.fn();
    render(<BacktestSliders onRun={onRun} loading />);

    const runBtn = screen.getByText("Running...");
    expect(runBtn).toBeDisabled();
  });
});
