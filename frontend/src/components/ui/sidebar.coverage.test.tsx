import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { Sidebar } from "./sidebar";

// next/navigation: usePathname is the only nav hook the component uses.
vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

// next-themes: capture setTheme so we can assert the collapsed-mode toggle fires.
const setThemeMock = vi.fn();
let currentTheme = "dark";
vi.mock("next-themes", () => ({
  useTheme: () => ({ theme: currentTheme, setTheme: setThemeMock }),
}));

describe("Sidebar — collapsed theme toggle (line 147 coverage)", () => {
  beforeEach(() => {
    setThemeMock.mockClear();
    currentTheme = "dark";
  });

  it("renders the expanded sidebar by default", () => {
    render(<Sidebar />);
    // Expanded shows the full brand label.
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    expect(screen.getByText("System Online")).toBeInTheDocument();
  });

  it("fires setTheme from the EXPANDED theme button (covers line 163)", () => {
    render(<Sidebar />);

    // Expanded (default) + mounted: the theme toggle renders the "Light Mode"
    // label (lines 162-169). Clicking it runs line 163's onClick.
    const themeButton = screen.getByText("Light Mode").closest("button");
    fireEvent.click(themeButton!);

    expect(setThemeMock).toHaveBeenCalledWith("light");
  });

  it("fires setTheme from the COLLAPSED theme button (covers line 147)", () => {
    render(<Sidebar />);

    // 1. Collapse the sidebar. The collapse toggle is the first <button>
    //    inside the logo header. After clicking, collapsed === true so the
    //    collapsed branch (lines 143-158) renders.
    const buttons = screen.getAllByRole("button");
    // First button = collapse/expand toggle.
    fireEvent.click(buttons[0]);

    // 2. In collapsed + mounted state the theme toggle (line 146-152) renders
    //    with title "Light mode" (because currentTheme === "dark").
    const themeButton = screen.getByTitle("Light mode");
    fireEvent.click(themeButton);

    // 3. Line 147: setTheme(isDark ? "light" : "dark") -> "light".
    expect(setThemeMock).toHaveBeenCalledWith("light");
  });

  it("collapsed theme button toggles to dark when current theme is light", () => {
    currentTheme = "light";
    render(<Sidebar />);

    const buttons = screen.getAllByRole("button");
    fireEvent.click(buttons[0]); // collapse

    // Light theme -> title "Dark mode".
    const themeButton = screen.getByTitle("Dark mode");
    fireEvent.click(themeButton);

    expect(setThemeMock).toHaveBeenCalledWith("dark");
  });
});
