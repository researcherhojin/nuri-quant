import { beforeEach, afterEach, describe, it, expect, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import Page from "@/app/ticker-next/page";
import { TickerSearch } from "@/app/ticker-next/ticker-search";
import { TICKER_PREVIEW as T } from "@/lib/strings";

const readPanel = vi.hoisted(() => vi.fn());

const push = vi.hoisted(() => vi.fn());

vi.mock("@/app/(overview)/data", () => ({ readPanel, portfolioSchema: {} }));

vi.mock("next/link", () => ({ default: ({ children, href }: { children: React.ReactNode; href: string }) => <a href={href}>{children}</a> }));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

beforeEach(() => { push.mockReset(); readPanel.mockReset(); vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ results: [] }) }))); });

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("offers each held ticker once without account details", async () => {
  readPanel.mockResolvedValue({ holdings: [{ ticker: "DEMO", name: "Demo Company", account: "Brokerage Alpha" }, { ticker: "DEMO", name: "Demo Company", account: "Brokerage Beta" }] });
  render(await Page());
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(T.LANDING_TITLE);
  expect(screen.getAllByRole("link", { name: /DEMO/ })).toHaveLength(1);
  expect(screen.getByRole("link", { name: /DEMO/ })).toHaveAttribute("href", "/ticker-next/DEMO");
  expect(screen.queryByText("Brokerage Alpha")).not.toBeInTheDocument();
});

it("can open a direct ticker while portfolio data is unavailable", async () => {
  readPanel.mockResolvedValue(null);
  render(await Page());
  expect(screen.getByText(T.LANDING_NO_HOLDINGS)).toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox", { name: T.SEARCH_LABEL }), { target: { value: "demo" } });
  fireEvent.click(screen.getByRole("button", { name: T.SEARCH_OPEN }));
  expect(push).toHaveBeenCalledWith("/ticker-next/DEMO");
});

it("validates search results before creating navigation links", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ results: [{ ticker: "DEMO", name: "Demo Company" }] }) } as Response);
  render(<TickerSearch />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "데모" } });
  expect(await screen.findByRole("link", { name: /DEMO/ })).toHaveAttribute("href", "/ticker-next/DEMO");
  expect(fetch).toHaveBeenCalledWith("/api/tickers/search?q=%EB%8D%B0%EB%AA%A8", expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

it("labels a nameless holding with its ticker", async () => {
  readPanel.mockResolvedValue({ holdings: [{ ticker: "DEMO", name: null, account: "Brokerage Alpha" }] });
  render(await Page());
  expect(within(screen.getByRole("link", { name: /DEMO/ })).getAllByText("DEMO")).toHaveLength(2);
});

it("says the search failed on an HTTP error and says nothing matched on an empty result", async () => {
  vi.mocked(fetch).mockResolvedValueOnce({ ok: false, json: async () => ({ results: [{ ticker: "DEMO", name: "Error body" }] }) } as Response);
  render(<TickerSearch />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "데모" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_FAILED));
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "zzz" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_EMPTY));
});

it("labels a nameless search result with its ticker", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ results: [{ ticker: "DEMO", name: null }] }) } as Response);
  render(<TickerSearch />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "dem" } });
  const link = await screen.findByRole("link", { name: /DEMO/ });

  expect(within(link).getAllByText("DEMO")).toHaveLength(2);
});

describe("a search that the user has already replaced", () => {
  interface Pending { resolve?: (value: Response) => void; reject?: (reason: Error) => void }

  // 첫 요청은 붙잡아 두고, 두 번째(바뀐 검색어) 요청은 끝나지 않게 둔다 — 화면에 남는 결과는 늦게 온 첫 응답뿐이다
  async function replaceQuery(settleFirst: (first: Pending) => void) {
    const first: Pending = {};

    vi.mocked(fetch)
      .mockImplementationOnce(() => new Promise<Response>((resolve, reject) => { Object.assign(first, { resolve, reject }); }))
      .mockImplementationOnce(() => new Promise<Response>(() => {}));
    render(<TickerSearch />);
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "de" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "dem" } });
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => { settleFirst(first); });
  }

  it("ignores its results when they arrive late", async () => {
    await replaceQuery(({ resolve }) => resolve?.({ ok: true, json: async () => ({ results: [{ ticker: "STALE", name: "Late result" }] }) } as Response));
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_LOADING);
  });

  it("ignores its failure when the aborted request rejects", async () => {
    await replaceQuery(({ reject }) => reject?.(new DOMException("The operation was aborted.", "AbortError")));
    expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_LOADING);
    expect(screen.getByRole("status")).not.toHaveTextContent(T.SEARCH_FAILED);
  });
});

it("shows search failure and never builds a link from a malformed ticker", async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ results: [{ ticker: "../private", name: "Invalid result" }] }) } as Response);
  render(<TickerSearch />);
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "데모" } });
  await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_FAILED));
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: T.SEARCH_OPEN }));
  expect(push).not.toHaveBeenCalled();
  expect(screen.getByRole("status")).toHaveTextContent(T.SEARCH_INVALID);
});
