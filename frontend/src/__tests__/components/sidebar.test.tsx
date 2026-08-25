import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Sidebar } from "@/components/ui/sidebar";

// Mock @/lib/api
vi.mock("@/lib/api", () => ({
  API_BASE: "http://localhost:8001",
  fetchAPI: vi.fn().mockResolvedValue({}),
}));

// Mock next/navigation
const mockPathname = vi.fn().mockReturnValue("/");
vi.mock("next/navigation", () => ({
  usePathname: () => mockPathname(),
}));

// Mock next/link
vi.mock("next/link", () => ({
  default: ({ children, href, ...props }: { children: React.ReactNode; href: string; [key: string]: unknown }) => (
    <a href={href} {...props}>{children}</a>
  ),
}));

// Mock lucide-react icons
vi.mock("lucide-react", () => {
  type IconProps = { size?: number; className?: string; [key: string]: unknown };
  const Icon = ({ className, ...props }: IconProps) => (
    <svg data-testid="icon" className={className} {...props} />
  );
  return {
    LayoutDashboard: Icon,
    Briefcase: Icon,
    BarChart3: Icon,
    Users: Icon,
    Search: Icon,
    Target: Icon,
    ShieldAlert: Icon,
    TrendingUp: Icon,
    Scale: Icon,
    Cog: Icon,
    Workflow: Icon,
    FileBarChart: Icon,
    Bot: Icon,
    BookOpen: Icon,
    Compass: Icon,
    ChevronLeft: (props: IconProps) => <svg data-testid="chevron-left" {...props} />,
    ChevronRight: (props: IconProps) => <svg data-testid="chevron-right" {...props} />,
    ShieldCheck: (props: IconProps) => <svg data-testid="shield-check" {...props} />,
    ShieldX: (props: IconProps) => <svg data-testid="shield-x" {...props} />,
    Sun: (props: IconProps) => <svg data-testid="sun-icon" {...props} />,
    Moon: (props: IconProps) => <svg data-testid="moon-icon" {...props} />,
  };
});

describe("Sidebar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockPathname.mockReturnValue("/");

    // Mock fetch for SIEGE status
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ certified: true, score: 90 }),
    });
  });

  it("renders Nuri-Quant branding", () => {
    render(<Sidebar />);
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    expect(screen.getByText("v0.1")).toBeInTheDocument();
  });

  it("renders all navigation groups", () => {
    render(<Sidebar />);
    expect(screen.getByText("오늘")).toBeInTheDocument();
    expect(screen.getByText("의사결정")).toBeInTheDocument();
    expect(screen.getByText("포트폴리오")).toBeInTheDocument();
    expect(screen.getByText("리서치")).toBeInTheDocument();
    expect(screen.getByText("시스템")).toBeInTheDocument();
  });

  it("renders all navigation items", () => {
    render(<Sidebar />);
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
    expect(screen.getByText("Pipeline")).toBeInTheDocument();
    expect(screen.getByText("Portfolio")).toBeInTheDocument();
    expect(screen.getByText("Signals")).toBeInTheDocument();
    expect(screen.getByText("Agents")).toBeInTheDocument();
    expect(screen.getByText("Scanner")).toBeInTheDocument();
    expect(screen.getByText("Price Targets")).toBeInTheDocument();
    // #1227: Advisor 는 /rebalance 로 통합 — 재추가되면 FAIL (IA 병합 잠금)
    expect(screen.queryByText("Advisor")).not.toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("Rebalance")).toBeInTheDocument();
    expect(screen.getByText("Certification Engine")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("AI Report")).toBeInTheDocument();
  });

  it("highlights active nav item", () => {
    mockPathname.mockReturnValue("/portfolio");
    const { container } = render(<Sidebar />);

    // 액티브 = 인터랙션 액센트(primary) — emerald 브랜드 액센트 폐지 (#1200, 스펙 §1)
    const activeLink = container.querySelector('a[href="/portfolio"]');
    expect(activeLink).not.toBeNull();
    expect(activeLink!.className).toContain("text-primary");
  });

  it("collapses sidebar on chevron click", () => {
    render(<Sidebar />);

    // Before collapse, "Nuri-Quant" is visible
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();

    // Click the collapse button (the button containing the chevron)
    const collapseBtn = screen.getByTestId("chevron-left").closest("button");
    fireEvent.click(collapseBtn!);

    // After collapse, "Nuri-Quant" should be hidden, "N" should be visible
    expect(screen.queryByText("Nuri-Quant")).not.toBeInTheDocument();
    expect(screen.getByText("N")).toBeInTheDocument();
  });

  it("hides nav labels when collapsed", () => {
    render(<Sidebar />);

    const collapseBtn = screen.getByTestId("chevron-left").closest("button");
    fireEvent.click(collapseBtn!);

    // Labels should be hidden
    expect(screen.queryByText("Dashboard")).not.toBeInTheDocument();
    expect(screen.queryByText("오늘")).not.toBeInTheDocument();
  });

  it("shows System Online indicator", () => {
    render(<Sidebar />);
    expect(screen.getByText("System Online")).toBeInTheDocument();
  });

  it("does not render SIEGE badge (moved to dashboard)", async () => {
    render(<Sidebar />);

    await waitFor(() => {
      expect(screen.queryByText("CERTIFIED")).not.toBeInTheDocument();
      expect(screen.queryByText("REJECTED")).not.toBeInTheDocument();
    });
  });

  // dark-only 잠금 (#1195 U1a codex P2): 토글이 되살아나면 zinc 램프 재매핑과
  // 시맨틱 토큰이 라이트 전환 시 혼합 테마를 만든다 — sidebar.coverage.test.tsx 참조.
  it("does not render a theme toggle (dark-only product)", () => {
    render(<Sidebar />);
    expect(screen.queryByText("Light Mode")).not.toBeInTheDocument();
    expect(screen.queryByText("Dark Mode")).not.toBeInTheDocument();
  });
});
