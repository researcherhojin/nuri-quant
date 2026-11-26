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

// Mock next/server
vi.mock("next/server", () => {
  return {
    NextResponse: {
      json: (body: unknown, init?: { status?: number }): MockResponse => {
        const resp: MockResponse = {
          body,
          status: init?.status || 200,
          cookies: {
            _store: {},
            set(name: string, value: string, opts: Record<string, unknown>) {
              this._store[name] = { value, ...opts };
            },
          },
        };

        return resp;
      },
    },
  };
});

describe("POST /api/auth", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it("returns 401 when no DASHBOARD_PASSWORD set", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "test" }),
    });

    const resp = await POST(req);
    expect(resp.status).toBe(401);
  });

  it("returns 401 with wrong password", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "correct");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "wrong" }),
    });

    const resp = await POST(req);
    expect(resp.status).toBe(401);
  });

  it("returns ok and sets cookie with correct password", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "secret123" }),
    });

    const resp = await POST(req);
    expect(resp.status).toBe(200);
    expect(resp.body).toEqual({ ok: true });
    // Verify cookie was set — mock stores into _store
    expect((resp.cookies as unknown as MockCookies)._store["nuri-auth"]).toBeDefined();
    expect((resp.cookies as unknown as MockCookies)._store["nuri-auth"].httpOnly).toBe(true);
  });

  it("cookie value is SHA256 hash, not plaintext", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "mypass");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "mypass" }),
    });

    const resp = await POST(req);
    const cookie = (resp.cookies as unknown as MockCookies)._store["nuri-auth"];
    expect(cookie.value).not.toBe("mypass");
    expect(cookie.value.length).toBe(64); // SHA256 hex = 64 chars
  });

  it("returns 400 on malformed JSON body", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: "{bad-json",
    });

    const resp = await POST(req);
    expect(resp.status).toBe(400);
  });

  it("returns 400 when password is not a string", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { POST } = await import("@/app/api/auth/route");

    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: 12345 }),
    });

    const resp = await POST(req);
    expect(resp.status).toBe(400);
  });

  it("rate limits after 5 attempts per IP and returns 429", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { POST } = await import("@/app/api/auth/route");

    for (let i = 0; i < 5; i += 1) {
      const req = new Request("http://localhost:3000/api/auth", {
        method: "POST",
        headers: { "x-forwarded-for": "10.0.0.1" },
        body: JSON.stringify({ password: "wrong" }),
      });

      const resp = await POST(req);
      expect(resp.status).toBe(401);
    }

    const blocked = await POST(
      new Request("http://localhost:3000/api/auth", {
        method: "POST",
        headers: { "x-forwarded-for": "10.0.0.1" },
        body: JSON.stringify({ password: "secret123" }),
      }),
    );

    expect(blocked.status).toBe(429);

    // Different IP is unaffected
    const otherIp = await POST(
      new Request("http://localhost:3000/api/auth", {
        method: "POST",
        headers: { "x-forwarded-for": "10.0.0.2" },
        body: JSON.stringify({ password: "secret123" }),
      }),
    );

    expect(otherIp.status).toBe(200);
  });
});
