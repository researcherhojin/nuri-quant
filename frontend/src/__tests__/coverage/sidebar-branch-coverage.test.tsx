/**
 * Sidebar — collapsed state + page highlight branches.
 * Split from coverage-push-4.test.tsx (lines 537-650).
 * 테마 토글/라이트 분기는 #1195 U1a 에서 제거 — dark-only 잠금만 남음.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";
import { NAV } from "@/lib/strings";

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
    expect(screen.getByText("오늘")).toBeInTheDocument();
    expect(screen.getByText("의사결정")).toBeInTheDocument();
    expect(screen.getByText("리서치")).toBeInTheDocument();
    expect(screen.getByText("시스템")).toBeInTheDocument();

    // Current page "/" — Dashboard link should exist
    const dashLink = screen.getByText(NAV.ROUTE_DASHBOARD);
    expect(dashLink).toBeInTheDocument();
  });
});
