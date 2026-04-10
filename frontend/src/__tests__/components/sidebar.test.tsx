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

// Mock next-themes
const mockSetTheme = vi.fn();
const mockTheme = vi.fn().mockReturnValue("dark");
vi.mock("next-themes", () => ({
  useTheme: () => ({
    theme: mockTheme(),
    setTheme: mockSetTheme,
  }),
}));

// Mock lucide-react icons
vi.mock("lucide-react", () => {
  const Icon = ({ size, className, ...props }: { size?: number; className?: string }) => (
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
    ChevronLeft: (props: any) => <svg data-testid="chevron-left" {...props} />,
    ChevronRight: (props: any) => <svg data-testid="chevron-right" {...props} />,
    ShieldCheck: (props: any) => <svg data-testid="shield-check" {...props} />,
    ShieldX: (props: any) => <svg data-testid="shield-x" {...props} />,
    Sun: (props: any) => <svg data-testid="sun-icon" {...props} />,
    Moon: (props: any) => <svg data-testid="moon-icon" {...props} />,
  };
});

describe("Sidebar", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    mockPathname.mockReturnValue("/");
    mockTheme.mockReturnValue("dark");

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
    expect(screen.getByText("OVERVIEW")).toBeInTheDocument();
    expect(screen.getByText("ANALYSIS")).toBeInTheDocument();
    expect(screen.getByText("TRADING")).toBeInTheDocument();
    expect(screen.getByText("INTELLIGENCE")).toBeInTheDocument();
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
    expect(screen.getByText("Advisor")).toBeInTheDocument();
    expect(screen.getByText("Strategy")).toBeInTheDocument();
    expect(screen.getByText("Rebalance")).toBeInTheDocument();
    expect(screen.getByText("SIEGE Engine")).toBeInTheDocument();
    expect(screen.getByText("Evidence")).toBeInTheDocument();
    expect(screen.getByText("AI Report")).toBeInTheDocument();
  });

  it("highlights active nav item", () => {
    mockPathname.mockReturnValue("/portfolio");
    const { container } = render(<Sidebar />);

    // The active link should have emerald text class
    const activeLink = container.querySelector('a[href="/portfolio"]');
    expect(activeLink).not.toBeNull();
    expect(activeLink!.className).toContain("text-emerald-400");
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
    expect(screen.queryByText("OVERVIEW")).not.toBeInTheDocument();
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

  it("toggles theme from dark to light", async () => {
    render(<Sidebar />);

    // Wait for mounted state
    await waitFor(() => {
      expect(screen.getByText("Light Mode")).toBeInTheDocument();
    });

    const themeBtn = screen.getByText("Light Mode").closest("button");
    fireEvent.click(themeBtn!);

    expect(mockSetTheme).toHaveBeenCalledWith("light");
  });

  it("shows Dark Mode label when theme is light", async () => {
    mockTheme.mockReturnValue("light");

    render(<Sidebar />);

    await waitFor(() => {
      expect(screen.getByText("Dark Mode")).toBeInTheDocument();
    });
  });
});
