import { describe, it, expect, vi, beforeEach } from "vitest";
import { API_BASE, fetchAPI } from "@/lib/api";

describe("API utilities", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("API_BASE defaults to localhost:8001", () => {
    expect(API_BASE).toBe("http://localhost:8001");
  });

  it("fetchAPI calls correct URL", async () => {
    const mockData = { status: "ok" };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockData),
    });

    const result = await fetchAPI("/api/health");
    expect(fetch).toHaveBeenCalledWith(
      `${API_BASE}/api/health`,
      expect.objectContaining({ next: { revalidate: 60 } })
    );
    expect(result).toEqual(mockData);
  });

  it("fetchAPI throws on non-ok response", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    });

    await expect(fetchAPI("/api/broken")).rejects.toThrow("API /api/broken: 500");
  });
});
