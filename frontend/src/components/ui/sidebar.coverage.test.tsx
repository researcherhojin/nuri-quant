import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { Sidebar } from "./sidebar";
import { NAV } from "@/lib/strings";

// next/navigation: usePathname is the only nav hook the component uses.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

describe("Sidebar — dark-only footer (#1195 U1a)", () => {
  it("renders the expanded sidebar by default", () => {
    render(<Sidebar />);
    // Expanded shows the full brand label.
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    expect(screen.getByText(NAV.SYSTEM_ONLINE)).toBeInTheDocument();
  });

  // 잠금 (codex P2): 제품은 dark-only (frontend/CLAUDE.md). 테마 토글이 되살아나면
  // zinc 램프 재매핑(@theme 전역)과 시맨틱 토큰이 라이트 전환 시 혼합 테마를 만든다 —
  // 토글을 복원하려면 램프를 테마별 var 로 스코프하는 작업이 선행되어야 한다.
  it("does not render a theme toggle in either sidebar state", () => {
    render(<Sidebar />);
    expect(screen.queryByText("Light Mode")).not.toBeInTheDocument();
    expect(screen.queryByText("Dark Mode")).not.toBeInTheDocument();

    // 접힌 상태에서도 토글 없음 (첫 버튼 = collapse 토글).
    const buttons = screen.getAllByRole("button");
    buttons[0].click();
    expect(screen.queryByTitle("Light mode")).not.toBeInTheDocument();
    expect(screen.queryByTitle("Dark mode")).not.toBeInTheDocument();
  });
});
