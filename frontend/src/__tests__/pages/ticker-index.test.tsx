import { beforeEach, afterEach, it, expect, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
