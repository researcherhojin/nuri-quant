import { describe, it, expect, vi, beforeEach } from "vitest";

interface CookieEntry {
  value: string;
  httpOnly?: boolean;
  secure?: boolean;
  sameSite?: string;
  path?: string;
  maxAge?: number;
  [key: string]: unknown;
}

interface MockCookies {
  _store: Record<string, CookieEntry>;
  set(name: string, value: string, opts: Record<string, unknown>): void;
}

interface MockResponse {
  body: unknown;
  status: number;
  cookies: MockCookies;
}

// next/server 모킹 — NextResponse.json 만 사용. default 도 노출해
// 현재 vitest 의 mock 해석 동작에 견고하게 대응한다.
vi.mock("next/server", () => {
  const NextResponse = {
    json: (body: unknown, init?: { status?: number }): MockResponse => ({
      body,
      status: init?.status || 200,
      cookies: {
        _store: {},
        set(name: string, value: string, opts: Record<string, unknown>) {
          this._store[name] = { value, ...opts };
        },
      },
    }),
  };
  return { __esModule: true, NextResponse, default: { NextResponse } };
});

describe("POST /api/auth — branch coverage", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  // password 필드 자체가 없는 요청 → `password ?? ""` 의 null-arm 을 trigger.
  // 빈 비밀번호이므로 expected 와 불일치 → 401.
  it("returns 401 when password field is absent (nullish-coalescing null-arm)", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "correct");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({}), // password 누락
    });
    const resp = await POST(req);
    expect(resp.status).toBe(401);
    expect(resp.body).toEqual({ error: "Invalid password" });
  });

  // expected 미설정 → 첫 guard (line 8) truthy-arm.
  it("returns 401 when DASHBOARD_PASSWORD is unset", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "anything" }),
    });
    const resp = await POST(req);
    expect(resp.status).toBe(401);
    expect(resp.body).toEqual({ error: "Auth not configured" });
  });

  // 잘못된 비밀번호 → timingSafeEqual false → line 13 truthy-arm.
  it("returns 401 with a wrong password", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "correct");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "wrong" }),
    });
    const resp = await POST(req);
    expect(resp.status).toBe(401);
    expect(resp.body).toEqual({ error: "Invalid password" });
  });

  // 올바른 비밀번호 + NODE_ENV !== production → line 22 binary false-arm,
  // line 8 / line 13 falsy-arm, `?? ""` non-null arm.
  it("returns ok and sets non-secure cookie when NODE_ENV is not production", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    vi.stubEnv("NODE_ENV", "test");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "secret123" }),
    });
    const resp = await POST(req);
    expect(resp.status).toBe(200);
    expect(resp.body).toEqual({ ok: true });
    const cookie = (resp.cookies as unknown as MockCookies)._store["nuri-auth"];
    expect(cookie).toBeDefined();
    expect(cookie.httpOnly).toBe(true);
    expect(cookie.secure).toBe(false);
  });

  // 올바른 비밀번호 + NODE_ENV === production → line 22 binary true-arm.
  it("sets secure cookie when NODE_ENV is production", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    vi.stubEnv("NODE_ENV", "production");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "secret123" }),
    });
    const resp = await POST(req);
    expect(resp.status).toBe(200);
    const cookie = (resp.cookies as unknown as MockCookies)._store["nuri-auth"];
    expect(cookie.secure).toBe(true);
  });
});
