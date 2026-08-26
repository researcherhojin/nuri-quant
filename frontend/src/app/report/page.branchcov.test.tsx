import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ERRORS } from "@/lib/strings";

import ReportPage from "./page";

let mockFetch: ReturnType<typeof vi.fn>;

beforeEach(() => {
  mockFetch = vi.fn();
  global.fetch = mockFetch as unknown as typeof fetch;
});

function jsonResponse(body: unknown) {
  return { json: async () => body } as unknown as Response;
}

describe("ReportPage (branch coverage)", () => {
  // page.tsx line 38: `{loading ? "Generating..." : "Generate Report"}` 의 TRUE 분기.
  // 초기 렌더는 loading=false (FALSE 분기, 이미 커버됨).
  // 첫 fetch 를 영원히 pending 상태로 두면 loading=true 가 유지되어 "Generating..." 렌더.
  it("shows 'Generating...' label while loading (loading === true arm)", async () => {
    mockFetch.mockReturnValue(new Promise(() => {}));

    render(<ReportPage />);
    const button = screen.getByRole("button", { name: "Generate Report" });
    expect(button).not.toBeDisabled();

    fireEvent.click(button);

    await waitFor(() => {
      expect(
        screen.getByRole("button", { name: "Generating..." }),
      ).toBeDisabled();
    });
  });

  // 성공 플로우: 두 fetch 모두 resolve.
  // → line 42 `context && (...)` TRUE arm (Data Context 카드 렌더)
  // → line 53 `report && (...)` TRUE arm (AI Generated Report 카드 렌더)
  it("renders context + report cards on success (both && truthy arms)", async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ context: "CTX-DATA" })) // /api/report/context
      .mockResolvedValueOnce(jsonResponse({ report: "REPORT-BODY" })); // /api/report

    render(<ReportPage />);
    fireEvent.click(screen.getByRole("button", { name: "Generate Report" }));

    await waitFor(() => {
      expect(screen.getByText("Data Context (LLM Input)")).toBeInTheDocument();
      expect(screen.getByText("CTX-DATA")).toBeInTheDocument();
      expect(
        screen.getByText("AI Generated Report (Ollama)"),
      ).toBeInTheDocument();
      expect(screen.getByText("REPORT-BODY")).toBeInTheDocument();
    });
  });

  // catch 분기 — F-002 이후 instanceof 분기는 없다: 원문은 console.error 로,
  // 본문에는 ERRORS.REPORT_FAILED 사용자 카피만 렌더된다.
  it("renders user-facing copy on Error rejection (raw error to console only)", async () => {
    mockFetch.mockRejectedValue(new Error("boom-message"));

    render(<ReportPage />);
    fireEvent.click(screen.getByRole("button", { name: "Generate Report" }));

    await waitFor(() => {
      expect(screen.getByText(ERRORS.REPORT_FAILED)).toBeInTheDocument();
    });
    expect(screen.queryByText(/boom-message/)).not.toBeInTheDocument();
  });

  it("renders user-facing copy on non-Error rejection", async () => {
    mockFetch.mockRejectedValue("string-rejection"); // Error 가 아님

    render(<ReportPage />);
    fireEvent.click(screen.getByRole("button", { name: "Generate Report" }));

    await waitFor(() => {
      expect(screen.getByText(ERRORS.REPORT_FAILED)).toBeInTheDocument();
    });
    expect(screen.queryByText(/string-rejection/)).not.toBeInTheDocument();
  });
});
