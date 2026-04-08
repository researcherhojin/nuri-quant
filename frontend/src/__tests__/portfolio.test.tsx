import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import PortfolioPage from "@/app/portfolio/page";

// next/link stub
vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

// next/navigation stub
const mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
}));

const mockHoldings = [
  { ticker: "TSLA", account: "test", quantity: 33, avg_price: 200.0, currency: "USD", sector: "SectorA", latest_price: 250, price_date: "2026-03-31" },
  { ticker: "005930.KS", account: "sample", quantity: 4, avg_price: 200500, currency: "KRW", sector: "Semiconductor", latest_price: 210000, price_date: "2026-03-31" },
];

function mockFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    const path = typeof url === "string" ? url : "";

    // GET /api/portfolio
    if (path.includes("/api/portfolio") && (!opts || opts.method === undefined || opts.method === "GET")) {
      if (path.includes("export")) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve("account,ticker\n"), headers: new Headers({ "content-type": "text/csv" }) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.holdings ?? { holdings: mockHoldings, count: mockHoldings.length }),
      });
    }

    // POST /api/portfolio (add)
    if (path.includes("/api/portfolio") && opts?.method === "POST" && !path.includes("import")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, ticker: "AAPL" }) });
    }

    // PUT /api/portfolio
    if (opts?.method === "PUT") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, ticker: "TSLA", updated: {} }) });
    }

    // DELETE /api/portfolio
    if (opts?.method === "DELETE") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }

    // POST import
    if (path.includes("import") && opts?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, imported: 2, errors: [] }) });
    }

    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe("PortfolioPage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = mockFetch();
  });

  it("renders holdings grouped by account", async () => {
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
      expect(screen.getByText("005930.KS")).toBeInTheDocument();
    });
    // 계좌별 그룹핑 확인
    expect(screen.getByText("test")).toBeInTheDocument();
    expect(screen.getByText("sample")).toBeInTheDocument();
  });

  it("shows onboarding guide when no holdings", async () => {
    global.fetch = mockFetch({ holdings: { holdings: [], count: 0 } });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/Start by adding your portfolio/)).toBeInTheDocument();
    });
  });

  it("shows Add Holding form on button click", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Add Holding"));
    expect(screen.getByPlaceholderText("Ticker (e.g. AAPL)")).toBeInTheDocument();
  });

  it("validates quantity > 0 on add", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Add Holding"));

    const qtyInput = screen.getByPlaceholderText("Quantity");
    fireEvent.change(qtyInput, { target: { value: "0" } });
    const avgInput = screen.getByPlaceholderText("Avg Price");
    fireEvent.change(avgInput, { target: { value: "100" } });
    const tickerInput = screen.getByPlaceholderText("Ticker (e.g. AAPL)");
    fireEvent.change(tickerInput, { target: { value: "AAPL" } });

    fireEvent.click(screen.getByText("Save"));
    await waitFor(() => {
      expect(screen.getByText("수량은 0보다 커야 합니다")).toBeInTheDocument();
    });
  });

  it("shows Edit/Save/Cancel for inline edit", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());

    // Edit 버튼 클릭
    const editButtons = screen.getAllByText("Edit");
    fireEvent.click(editButtons[0]);

    // Save/Cancel 표시 확인
    expect(screen.getByText("Save")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();

    // Cancel 클릭 → Edit로 복귀
    fireEvent.click(screen.getByText("Cancel"));
    await waitFor(() => {
      expect(screen.getAllByText("Edit").length).toBeGreaterThan(0);
    });
  });

  it("shows import/export buttons", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());
    expect(screen.getByText("Upload CSV")).toBeInTheDocument();
    expect(screen.getByText("Download CSV")).toBeInTheDocument();
    expect(screen.getByText("Download YAML")).toBeInTheDocument();
  });

  it("shows currency-aware price symbols", async () => {
    render(<PortfolioPage />);
    await waitFor(() => {
      // USD → $, KRW → ₩
      expect(screen.getByText("$250")).toBeInTheDocument();
      expect(screen.getByText("₩210,000")).toBeInTheDocument();
    });
  });

  it("shows onboarding guide when empty", async () => {
    global.fetch = mockFetch({ holdings: { holdings: [], count: 0 } });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText(/Start by adding your portfolio/)).toBeInTheDocument();
      expect(screen.getByText("Add holdings")).toBeInTheDocument();
      expect(screen.getByText("Collect market data")).toBeInTheDocument();
      expect(screen.getByText("Run analysis")).toBeInTheDocument();
    });
  });

  it("shows Load Sample Portfolio button when empty", async () => {
    global.fetch = mockFetch({ holdings: { holdings: [], count: 0 } });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("Load Sample Portfolio")).toBeInTheDocument();
    });
  });

  it("shows welcome message with onboarding=true", async () => {
    mockSearchParams.set("onboarding", "true");
    global.fetch = mockFetch({ holdings: { holdings: [], count: 0 } });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("Welcome to Nuri-Quant")).toBeInTheDocument();
    });
    mockSearchParams.delete("onboarding");
  });
});
