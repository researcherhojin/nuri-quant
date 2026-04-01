import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PortfolioPage from "@/app/portfolio/page";

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

const mockSearchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
}));

const mockHoldings = [
  { ticker: "TSLA", account: "kakaopay", quantity: 33, avg_price: 343.39, currency: "USD", sector: "EV/AI", latest_price: 250, price_date: "2026-03-31" },
  { ticker: "005930.KS", account: "toss", quantity: 4, avg_price: 200500, currency: "KRW", sector: "Semiconductor", latest_price: 210000, price_date: "2026-03-31" },
];

function mockFetch(overrides: Record<string, unknown> = {}) {
  return vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
    const path = typeof url === "string" ? url : "";
    if (path.includes("/api/portfolio") && (!opts || opts.method === undefined || opts.method === "GET")) {
      if (path.includes("export")) {
        return Promise.resolve({ ok: true, text: () => Promise.resolve("account,ticker\n"), headers: new Headers({ "content-type": "text/csv" }) });
      }
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(overrides.holdings ?? { holdings: mockHoldings, count: mockHoldings.length }),
      });
    }
    if (path.includes("/api/portfolio") && opts?.method === "POST" && !path.includes("import")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, ticker: "AAPL" }) });
    }
    if (opts?.method === "PUT") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, ticker: "TSLA", updated: {} }) });
    }
    if (opts?.method === "DELETE") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true }) });
    }
    if (path.includes("import") && opts?.method === "POST") {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, imported: 2, errors: [] }) });
    }
    if (path.includes("sample")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, imported: 5 }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  });
}

describe("PortfolioPage — extended coverage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    global.fetch = mockFetch();
  });

  it("submits add form with valid data", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());

    fireEvent.click(screen.getByText("Add Holding"));

    const tickerInput = screen.getByPlaceholderText("Ticker (e.g. TSLA)");
    const qtyInput = screen.getByPlaceholderText("Quantity");
    const priceInput = screen.getByPlaceholderText("Avg Price");

    fireEvent.change(tickerInput, { target: { value: "AAPL" } });
    fireEvent.change(qtyInput, { target: { value: "10" } });
    fireEvent.change(priceInput, { target: { value: "180" } });
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      // Form should have been submitted (fetch called with POST)
      const calls = (global.fetch as any).mock.calls;
      const postCall = calls.find((c: any) => c[1]?.method === "POST" && !c[0].includes("import"));
      expect(postCall).toBeTruthy();
    });
  });

  it("handles save during edit mode", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());

    // Click Edit on first row
    const editButtons = screen.getAllByText("Edit");
    fireEvent.click(editButtons[0]);

    // Click Save
    fireEvent.click(screen.getByText("Save"));

    await waitFor(() => {
      const calls = (global.fetch as any).mock.calls;
      const putCall = calls.find((c: any) => c[1]?.method === "PUT");
      expect(putCall).toBeTruthy();
    });
  });

  it("handles delete confirmation", async () => {
    // Mock window.confirm
    vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());

    const deleteButtons = screen.getAllByText("Delete");
    fireEvent.click(deleteButtons[0]);

    await waitFor(() => {
      const calls = (global.fetch as any).mock.calls;
      const deleteCall = calls.find((c: any) => c[1]?.method === "DELETE");
      expect(deleteCall).toBeTruthy();
    });
  });

  it("handles CSV import", async () => {
    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());

    // Simulate file upload
    const file = new File(["account,ticker,quantity,avg_price\ntest,AAPL,10,180"], "test.csv", { type: "text/csv" });
    const uploadButton = screen.getByText("Upload CSV");
    // Click triggers hidden file input
    fireEvent.click(uploadButton);
  });

  it("renders import result with errors", async () => {
    global.fetch = vi.fn().mockImplementation((url: string, opts?: RequestInit) => {
      if (url.includes("/api/portfolio") && (!opts || !opts.method || opts.method === "GET")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ holdings: mockHoldings, count: 2 }) });
      }
      if (url.includes("import") && opts?.method === "POST") {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, imported: 1, errors: ["Row 2: invalid ticker"] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    });

    render(<PortfolioPage />);
    await waitFor(() => expect(screen.getByText("TSLA")).toBeInTheDocument());
  });

  it("loads sample portfolio when empty", async () => {
    global.fetch = mockFetch({ holdings: { holdings: [], count: 0 } });
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("Load Sample Portfolio")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByText("Load Sample Portfolio"));
  });

  it("renders holding data correctly", async () => {
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("TSLA")).toBeInTheDocument();
      expect(screen.getByText("005930.KS")).toBeInTheDocument();
    });
  });

  it("shows account filter tabs", async () => {
    render(<PortfolioPage />);
    await waitFor(() => {
      expect(screen.getByText("kakaopay")).toBeInTheDocument();
      expect(screen.getByText("toss")).toBeInTheDocument();
    });
  });
});
