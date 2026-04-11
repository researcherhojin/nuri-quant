import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import LoginPage from "@/app/login/page";

// Mock @base-ui/react/button to render a simple <button> for testing
vi.mock("@base-ui/react/button", () => ({
  Button: ({
    children,
    className,
    disabled,
    ...props
  }: {
    children: React.ReactNode;
    className?: string;
    disabled?: boolean;
    [key: string]: unknown;
  }) => (
    <button className={className} disabled={disabled} {...props}>
      {children}
    </button>
  ),
}));

describe("LoginPage", () => {
  let mockLocation: { href: string };

  beforeEach(() => {
    vi.restoreAllMocks();

    // Mock window.location
    mockLocation = { href: "" };
    Object.defineProperty(window, "location", {
      value: mockLocation,
      writable: true,
      configurable: true,
    });
  });

  it("renders login form", () => {
    render(<LoginPage />);
    expect(screen.getByText("Nuri-Quant")).toBeInTheDocument();
    expect(screen.getByText("Dashboard Login")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByText("Login")).toBeInTheDocument();
  });

  it("renders password input with type=password", () => {
    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    expect(input).toHaveAttribute("type", "password");
  });

  it("disables submit button when password is empty", () => {
    render(<LoginPage />);
    const button = screen.getByText("Login");
    expect(button).toBeDisabled();
  });

  it("enables submit button when password is entered", () => {
    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "secretpass" } });
    const button = screen.getByText("Login");
    expect(button).not.toBeDisabled();
  });

  it("shows error message on failed login", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "wrongpass" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(screen.getByText("Invalid password")).toBeInTheDocument();
    });
  });

  it("redirects to / on successful login", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true });

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "correctpass" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(mockLocation.href).toBe("/");
    });
  });

  it("sends POST to /api/auth with password", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true });

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "mypassword" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(fetch).toHaveBeenCalledWith("/api/auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: "mypassword" }),
      });
    });
  });

  it("shows loading state during submission", async () => {
    // Use a never-resolving promise to keep the loading state active
    let resolvePromise: (value: { ok: boolean }) => void;
    const pendingPromise = new Promise<{ ok: boolean }>((resolve) => {
      resolvePromise = resolve;
    });
    global.fetch = vi.fn().mockReturnValue(pendingPromise);

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "pass" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(screen.getByText("...")).toBeInTheDocument();
    });

    // Clean up
    resolvePromise!({ ok: true });
  });

  it("re-enables button after failed login", async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 401 });

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    fireEvent.change(input, { target: { value: "wrongpass" } });
    fireEvent.submit(input.closest("form")!);

    await waitFor(() => {
      expect(screen.getByText("Invalid password")).toBeInTheDocument();
    });

    // Button should show "Login" again (not loading)
    expect(screen.getByText("Login")).toBeInTheDocument();
  });

  it("clears error when resubmitting", async () => {
    let callCount = 0;
    global.fetch = vi.fn().mockImplementation(() => {
      callCount++;
      if (callCount === 1) return Promise.resolve({ ok: false, status: 401 });
      return Promise.resolve({ ok: true });
    });

    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");

    // First attempt: fails
    fireEvent.change(input, { target: { value: "wrong" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => {
      expect(screen.getByText("Invalid password")).toBeInTheDocument();
    });

    // Second attempt: error should clear during submission
    fireEvent.change(input, { target: { value: "correct" } });
    fireEvent.submit(input.closest("form")!);
    await waitFor(() => {
      expect(screen.queryByText("Invalid password")).not.toBeInTheDocument();
    });
  });

  it("password input is focused by default", () => {
    render(<LoginPage />);
    const input = screen.getByPlaceholderText("Password");
    // React autoFocus prop triggers focus in jsdom
    expect(input).toHaveFocus();
  });
});
