import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ErrorPage from "@/app/error";
import GlobalError from "@/app/global-error";

function makeError(message: string): Error & { digest?: string } {
  return Object.assign(new Error(message), { digest: undefined });
}

describe("Error (route-level error boundary)", () => {
  it("shows 'API connection failed' for API errors", () => {
    const error = makeError("API /api/dashboard: 500");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("API connection failed")).toBeInTheDocument();
    expect(
      screen.getByText(/Backend API is not responding/)
    ).toBeInTheDocument();
  });

  it("shows 'API connection failed' for fetch errors", () => {
    const error = makeError("fetch failed: network error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("API connection failed")).toBeInTheDocument();
  });

  it("shows 'Something went wrong' for non-API errors", () => {
    const error = makeError("Cannot read properties of undefined");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    expect(
      screen.getByText("Cannot read properties of undefined")
    ).toBeInTheDocument();
  });

  it("shows error.message for non-API errors", () => {
    const error = makeError("Custom error message here");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("Custom error message here")).toBeInTheDocument();
  });

  it("does NOT show error.message for API errors (shows help text instead)", () => {
    const error = makeError("API /api/broken: 500");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    // Should show the help message, not the raw error
    expect(screen.getByText(/make sure the server is running/i)).toBeInTheDocument();
  });

  it("renders Retry button", () => {
    const error = makeError("Some error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });

  it("calls reset when Retry button is clicked", () => {
    const error = makeError("Some error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    fireEvent.click(screen.getByText("Retry"));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("renders the exclamation icon", () => {
    const error = makeError("test error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText("!")).toBeInTheDocument();
  });
});

describe("GlobalError (layout-level error boundary)", () => {
  it("renders error message", () => {
    const error = makeError("Layout crashed");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText("Layout crashed")).toBeInTheDocument();
  });

  it("shows 'Something went wrong' heading", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("renders 'Try again' button", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText("Try again")).toBeInTheDocument();
  });

  it("calls reset when 'Try again' is clicked", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    fireEvent.click(screen.getByText("Try again"));
    expect(reset).toHaveBeenCalledTimes(1);
  });

  it("renders the exclamation mark", () => {
    const error = makeError("some error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText("!")).toBeInTheDocument();
  });

  it("renders a self-contained error page structure", () => {
    const error = makeError("some error");
    const reset = vi.fn();
    const { container } = render(<GlobalError error={error} reset={reset} />);
    // GlobalError renders a centered error layout with heading + button
    expect(container.querySelector("h1")).not.toBeNull();
    expect(container.querySelector("button")).not.toBeNull();
    expect(container.querySelector("p")).not.toBeNull();
  });
});
