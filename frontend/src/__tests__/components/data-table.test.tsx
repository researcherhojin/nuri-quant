import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DataTable } from "@/components/ui/data-table";

const basicColumns = [
  { key: "ticker", label: "Ticker" },
  { key: "price", label: "Price", align: "right" as const },
  { key: "change", label: "Change", align: "center" as const },
];

const basicData = [
  { ticker: "AAPL", price: 185.5, change: "+2.3%" },
  { ticker: "TSLA", price: 250.0, change: "-1.5%" },
  { ticker: "NVDA", price: 168.0, change: "+0.8%" },
];

describe("DataTable", () => {
  // ─── Basic rendering ─────────────────────────────────
  it("renders column headers", () => {
    render(<DataTable columns={basicColumns} data={basicData} />);
    expect(screen.getByText("Ticker")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("Change")).toBeInTheDocument();
  });

  it("renders all data rows", () => {
    render(<DataTable columns={basicColumns} data={basicData} />);
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("TSLA")).toBeInTheDocument();
    expect(screen.getByText("NVDA")).toBeInTheDocument();
  });

  it("renders cell values from data", () => {
    render(<DataTable columns={basicColumns} data={basicData} />);
    expect(screen.getByText("185.5")).toBeInTheDocument();
    expect(screen.getByText("+2.3%")).toBeInTheDocument();
  });

  it("renders empty table when data is empty", () => {
    const { container } = render(<DataTable columns={basicColumns} data={[]} />);
    const tbody = container.querySelector("tbody");
    expect(tbody).not.toBeNull();
    expect(tbody!.children).toHaveLength(0);
  });

  // ─── Column alignment ─────────────────────────────────
  it("applies left alignment by default", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const headerCells = container.querySelectorAll("th");
    // First column (Ticker) should be text-left
    expect(headerCells[0].className).toContain("text-left");
  });

  it("applies right alignment", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const headerCells = container.querySelectorAll("th");
    // Second column (Price) is align: right
    expect(headerCells[1].className).toContain("text-right");
  });

  it("applies center alignment", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const headerCells = container.querySelectorAll("th");
    // Third column (Change) is align: center
    expect(headerCells[2].className).toContain("text-center");
  });

  it("applies alignment to body cells too", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const firstRow = container.querySelector("tbody tr");
    const cells = firstRow!.querySelectorAll("td");
    // First cell: text-left (default)
    expect(cells[0].className).toContain("text-left");
    // Second cell: text-right
    expect(cells[1].className).toContain("text-right");
    // Third cell: text-center
    expect(cells[2].className).toContain("text-center");
  });

  // ─── Custom render function ──────────────────────────
  it("uses custom render function when provided", () => {
    const columns = [
      { key: "ticker", label: "Ticker" },
      {
        key: "price",
        label: "Price",
        render: (value: number) => <span data-testid="custom-price">${value.toFixed(2)}</span>,
      },
    ];
    const data = [{ ticker: "AAPL", price: 185.5 }];
    render(<DataTable columns={columns} data={data} />);
    const customEl = screen.getByTestId("custom-price");
    expect(customEl).toBeInTheDocument();
    expect(customEl.textContent).toBe("$185.50");
  });

  it("passes row object to render function", () => {
    const renderFn = vi.fn((_value: string, row: { ticker: string; sector: string }) => (
      <span>{row.ticker} ({row.sector})</span>
    ));
    const columns = [{ key: "ticker", label: "Ticker", render: renderFn }];
    const data = [{ ticker: "AAPL", sector: "Tech" }];
    render(<DataTable columns={columns} data={data} />);
    expect(renderFn).toHaveBeenCalledWith("AAPL", { ticker: "AAPL", sector: "Tech" });
    expect(screen.getByText("AAPL (Tech)")).toBeInTheDocument();
  });

  // ─── Compact mode ────────────────────────────────────
  it("uses terminal-density padding by default (#1200)", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const th = container.querySelector("th");
    expect(th!.className).toContain("py-1.5");
  });

  it("uses compact padding when compact=true", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} compact />);
    const th = container.querySelector("th");
    expect(th!.className).toContain("py-1");
  });

  it("uses text-xs in compact mode", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} compact />);
    const table = container.querySelector("table");
    expect(table!.className).toContain("text-xs");
  });

  it("uses text-xs in normal mode too (#1200 density)", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const table = container.querySelector("table");
    expect(table!.className).toContain("text-xs");
  });

  // ─── onRowClick ──────────────────────────────────────
  it("calls onRowClick with row data when row is clicked", () => {
    const handleClick = vi.fn();
    render(<DataTable columns={basicColumns} data={basicData} onRowClick={handleClick} />);
    fireEvent.click(screen.getByText("AAPL"));
    expect(handleClick).toHaveBeenCalledWith(basicData[0]);
  });

  it("adds cursor-pointer class when onRowClick is set", () => {
    const handleClick = vi.fn();
    const { container } = render(
      <DataTable columns={basicColumns} data={basicData} onRowClick={handleClick} />
    );
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].className).toContain("cursor-pointer");
  });

  it("does not add cursor-pointer when onRowClick is not set", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].className).not.toContain("cursor-pointer");
  });

  it("does not throw when clicking row without onRowClick", () => {
    render(<DataTable columns={basicColumns} data={basicData} />);
    expect(() => fireEvent.click(screen.getByText("TSLA"))).not.toThrow();
  });

  // ─── hideOnMobile ────────────────────────────────────
  it("applies hidden sm:table-cell class for hideOnMobile columns", () => {
    const columns = [
      { key: "ticker", label: "Ticker" },
      { key: "sector", label: "Sector", hideOnMobile: true },
    ];
    const data = [{ ticker: "AAPL", sector: "Tech" }];
    const { container } = render(<DataTable columns={columns} data={data} />);

    // ⚠️ **부분 문자열이 아니라 토큰으로 본다** (#1254 codex P2). `toContain("hidden")` 은
    // `text-lefthidden` 도 통과한다 — 실제로 tailwind autofix 가 앞 조각과 띄우는 필수
    // 공백을 지워 정확히 그 문자열을 만들었고, 이 테스트는 **초록이었다.** 클래스는 공백으로
    // 갈리는 토큰이므로 `classList` 로 확인해야 브라우저와 같은 것을 본다.
    const tokens = (el: Element) => Array.from(el.classList);

    const headerCells = container.querySelectorAll("th");
    expect(tokens(headerCells[1])).toContain("hidden");
    expect(tokens(headerCells[1])).toContain("sm:table-cell");
    // 선행 정렬 클래스가 붙어 있어야 한다 — 이게 없으면 공백이 지워진 상태다.
    expect(tokens(headerCells[1])).toContain("text-left");

    const dataCells = container.querySelectorAll("td");
    expect(tokens(dataCells[1])).toContain("hidden");
    expect(tokens(dataCells[1])).toContain("sm:table-cell");
    expect(tokens(dataCells[1])).toContain("text-left");
  });

  it("does not apply hidden class when hideOnMobile is false", () => {
    const columns = [
      { key: "ticker", label: "Ticker", hideOnMobile: false },
    ];
    const data = [{ ticker: "AAPL" }];
    const { container } = render(<DataTable columns={columns} data={data} />);
    const th = container.querySelector("th");
    expect(th!.className).not.toContain("hidden");
  });

  // ─── Column width ───────────────────────────────────
  it("applies column width style when specified", () => {
    const columns = [{ key: "ticker", label: "Ticker", width: "200px" }];
    const data = [{ ticker: "AAPL" }];
    const { container } = render(<DataTable columns={columns} data={data} />);
    const th = container.querySelector("th");
    expect(th!.style.width).toBe("200px");
  });

  it("does not set width style when not specified", () => {
    const columns = [{ key: "ticker", label: "Ticker" }];
    const data = [{ ticker: "AAPL" }];
    const { container } = render(<DataTable columns={columns} data={data} />);
    const th = container.querySelector("th");
    expect(th!.style.width).toBe("");
  });

  // ─── Table structure ────────────────────────────────
  it("wraps table in overflow-x-auto div", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.className).toContain("overflow-x-auto");
  });

  it("table has w-full class", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const table = container.querySelector("table");
    expect(table!.className).toContain("w-full");
  });

  it("header row has border-b", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const headerRow = container.querySelector("thead tr");
    expect(headerRow!.className).toContain("border-b");
  });

  it("body rows have hover styles", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const bodyRow = container.querySelector("tbody tr");
    expect(bodyRow!.className).toContain("hover:bg-muted/30");
  });

  // ─── rowClassName ──────────────────────────────────────
  it("applies rowClassName function to matching rows", () => {
    const rowClassName = (row: (typeof basicData)[number]) => row.ticker === "TSLA" ? "bg-red-500/10" : "";
    const { container } = render(
      <DataTable columns={basicColumns} data={basicData} rowClassName={rowClassName} />
    );
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].className).not.toContain("bg-red-500/10");
    expect(rows[1].className).toContain("bg-red-500/10");
  });

  it("does not break when rowClassName is not provided", () => {
    const { container } = render(<DataTable columns={basicColumns} data={basicData} />);
    const rows = container.querySelectorAll("tbody tr");
    expect(rows[0].className).toContain("hover:bg-muted/30");
  });
});
