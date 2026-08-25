import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import ErrorPage from "@/app/error";
import GlobalError from "@/app/global-error";
import { ERRORS } from "@/lib/strings";

function makeError(message: string): Error & { digest?: string } {
  return Object.assign(new Error(message), { digest: undefined });
}

describe("Error (route-level error boundary)", () => {
  it("shows the API error title for API errors", () => {
    const error = makeError("API /api/dashboard: 500");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.API_TITLE)).toBeInTheDocument();
    expect(screen.getByText(ERRORS.API_BODY)).toBeInTheDocument();
  });

  it("shows the API error title for fetch errors", () => {
    const error = makeError("fetch failed: network error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.API_TITLE)).toBeInTheDocument();
  });

  it("shows the generic title for non-API errors", () => {
    const error = makeError("Cannot read properties of undefined");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.GENERIC_TITLE)).toBeInTheDocument();
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
    // 원문 에러 대신 다음 행동을 담은 카피가 뜬다 (design-review F-002)
    expect(screen.getByText(ERRORS.API_BODY)).toBeInTheDocument();
    expect(screen.queryByText("API /api/broken: 500")).toBeNull();
  });

  it("renders the retry button", () => {
    const error = makeError("Some error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.RETRY)).toBeInTheDocument();
  });

  it("calls reset when the retry button is clicked", () => {
    const error = makeError("Some error");
    const reset = vi.fn();
    render(<ErrorPage error={error} reset={reset} />);
    fireEvent.click(screen.getByText(ERRORS.RETRY));
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

  it("shows the generic title heading", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.GENERIC_TITLE)).toBeInTheDocument();
  });

  it("renders the retry button", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    expect(screen.getByText(ERRORS.RETRY)).toBeInTheDocument();
  });

  it("calls reset when the retry button is clicked", () => {
    const error = makeError("any error");
    const reset = vi.fn();
    render(<GlobalError error={error} reset={reset} />);
    fireEvent.click(screen.getByText(ERRORS.RETRY));
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
