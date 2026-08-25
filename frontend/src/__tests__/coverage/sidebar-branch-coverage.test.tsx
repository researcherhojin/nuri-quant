/**
 * Sidebar — collapsed state + page highlight branches.
 * Split from coverage-push-4.test.tsx (lines 537-650).
 * 테마 토글/라이트 분기는 #1195 U1a 에서 제거 — dark-only 잠금만 남음.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));


describe("Sidebar — collapsed state and branch coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/certify")) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ certified: false, score: 60 }),
        });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("toggles sidebar collapse state", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Find collapse toggle (ChevronLeft icon button)
    const buttons = document.querySelectorAll("button");
    let collapseBtn: HTMLElement | null = null;
    buttons.forEach((btn) => {
      if (btn.querySelector("svg") && !btn.textContent?.includes("Mode")) {
        collapseBtn = btn;
      }
    });

    if (collapseBtn) {
      await act(async () => { fireEvent.click(collapseBtn!); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      expect(screen.queryByText("Nuri-Quant")).toBeNull();
      expect(screen.getByText("N")).toBeInTheDocument();

      await act(async () => { fireEvent.click(collapseBtn!); });
      await act(async () => { await new Promise(r => setTimeout(r, 100)); });

      expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    }
  });

  // 테마 토글 제거 (#1195 U1a codex P2) — dark-only 잠금은 sidebar.coverage.test.tsx.
  it("renders no theme toggle after dark-only lockdown", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    expect(document.body.textContent || "").not.toContain("Dark Mode");
    expect(screen.queryByTitle("Dark mode")).toBeNull();
  });

  it("shows nav group labels and active page highlighting", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });

    // Nav group labels should be visible (not collapsed)
    expect(screen.getByText("OVERVIEW")).toBeInTheDocument();
    expect(screen.getByText("ANALYSIS")).toBeInTheDocument();
    expect(screen.getByText("TRADING")).toBeInTheDocument();
    expect(screen.getByText("INTELLIGENCE")).toBeInTheDocument();

    // Current page "/" — Dashboard link should exist
    const dashLink = screen.getByText("Dashboard");
    expect(dashLink).toBeInTheDocument();
  });

  it("sidebar no longer renders SIEGE badge (moved to dashboard)", async () => {
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    const text = document.body.textContent || "";
    expect(text).not.toContain("CERTIFIED");
    expect(text).not.toContain("REJECTED");
  });

  it("handles certify API returning non-ok response (lines 79-81)", async () => {
    global.fetch = vi.fn().mockImplementation((url: string) => {
      if (url.includes("/api/certify")) {
        // Return { ok: false } to hit the null branch in .then(r => r.ok ? r.json() : null)
        return Promise.resolve({ ok: false, status: 500 });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
    }) as unknown as typeof fetch;

    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 300)); });

    // Neither CERTIFIED nor REJECTED should appear since siegeStatus is null
    expect(screen.queryByText("CERTIFIED")).toBeNull();
    expect(screen.queryByText("REJECTED")).toBeNull();
    // Sidebar should still render normally
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
  });
});
