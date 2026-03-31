import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import ReportPage from "@/app/report/page";

// Mock @base-ui/react/button
vi.mock("@base-ui/react/button", () => ({
  Button: ({
    children,
    className,
    disabled,
    ...props
  }: {
    children: React.ReactNode;
    className?: string;
    disabled?: boolean;
    [key: string]: unknown;
  }) => (
    <button className={className} disabled={disabled} {...props}>
      {children}
    </button>
  ),
}));

// Mock API_BASE
vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn(),
}));

describe("ReportPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders page title", () => {
    render(<ReportPage />);
    expect(screen.getByText("AI Investment Report")).toBeInTheDocument();
  });

  it("renders Generate Report button", () => {
    render(<ReportPage />);
    expect(screen.getByText("Generate Report")).toBeInTheDocument();
  });

  it("shows initial placeholder when no report generated", () => {
    render(<ReportPage />);
    expect(screen.getByText(/Generate Report 버튼을 눌러/)).toBeInTheDocument();
    expect(screen.getByText(/Ollama가 실행 중이어야 합니다/)).toBeInTheDocument();
  });

  it("shows loading state while generating", async () => {
    // Create promises that never resolve to keep loading state
    let resolveCtx: (value: any) => void;
    const ctxPromise = new Promise((resolve) => { resolveCtx = resolve; });

    global.fetch = vi.fn().mockReturnValue(ctxPromise);

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText("Generating...")).toBeInTheDocument();
    });

    // The button should be disabled during generation
    const button = screen.getByText("Generating...");
    expect(button).toBeDisabled();

    // Clean up
    resolveCtx!({ ok: true, json: () => Promise.resolve({ context: "test" }) });
  });

  it("displays context after fetch", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ context: "Portfolio: TSLA 33 shares, NVDA 20 shares" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ report: "Buy NVDA, Hold TSLA" }),
      });

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText("Data Context (LLM Input)")).toBeInTheDocument();
      expect(screen.getByText("Portfolio: TSLA 33 shares, NVDA 20 shares")).toBeInTheDocument();
    });
  });

  it("displays generated report", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ context: "context data" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ report: "## Market Analysis\nBullish regime detected." }),
      });

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText("AI Generated Report (Ollama)")).toBeInTheDocument();
      expect(screen.getByText(/Market Analysis/)).toBeInTheDocument();
    });
  });

  it("hides placeholder after report is generated", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ context: "ctx" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ report: "report text" }),
      });

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText("report text")).toBeInTheDocument();
    });

    // Placeholder should be gone
    expect(screen.queryByText(/Generate Report 버튼을 눌러/)).not.toBeInTheDocument();
  });

  it("shows error message on fetch failure", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error"));

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText(/Error: Network error/)).toBeInTheDocument();
    });
  });

  it("re-enables button after generation completes", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ context: "ctx" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ report: "done" }),
      });

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText("done")).toBeInTheDocument();
    });

    const btn = screen.getByText("Generate Report");
    expect(btn).not.toBeDisabled();
  });

  it("re-enables button after error", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("fail"));

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(screen.getByText(/Error: fail/)).toBeInTheDocument();
    });

    const btn = screen.getByText("Generate Report");
    expect(btn).not.toBeDisabled();
  });

  it("calls correct API endpoints", async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ context: "ctx" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ report: "done" }),
      });

    render(<ReportPage />);
    fireEvent.click(screen.getByText("Generate Report"));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8001/api/report/context");
      expect(global.fetch).toHaveBeenCalledWith("http://localhost:8001/api/report");
    });
  });
});
