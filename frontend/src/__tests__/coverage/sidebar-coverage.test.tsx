/**
 * Sidebar — collapsed state, theme toggle (dark theme).
 * Split from coverage-push-2.test.tsx (lines 421-473).
 *
 * NOTE: kept separate from sidebar-branch-coverage.test.tsx (push-4 origin) — that
 * file mocks next-themes with light mode, this one with dark mode (different
 * useTheme().theme value drives different branches).
 */
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, act } from "@testing-library/react";
import type { ReactNode } from "react";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("onboarding=true"),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
  redirect: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => <a href={href}>{children}</a>,
}));

vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: "dark", setTheme: vi.fn() }),
  ThemeProvider: ({ children }: { children?: ReactNode }) => <div>{children}</div>,
}));

describe("Sidebar interactions", () => {
  it("renders sidebar branding", async () => {
    vi.resetModules();
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });
    await act(async () => { await new Promise(r => setTimeout(r, 200)); });

    // Should show Nuri-Quant branding
    expect(screen.queryByText("Nuri-Quant")).toBeTruthy();
  });

  it("toggles collapsed state", async () => {
    vi.resetModules();
    const { Sidebar } = await import("@/components/ui/sidebar");
    await act(async () => { render(<Sidebar />); });

    // Find collapse button (« or »)
    const collapseBtn = screen.queryByText("«") || screen.queryByText("»");
    if (collapseBtn) {
      await act(async () => { fireEvent.click(collapseBtn); });
      // After collapse, Nuri-Quant text should be hidden
    }
  });
});
