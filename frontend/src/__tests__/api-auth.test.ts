import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock next/server
vi.mock("next/server", () => {
  return {
    NextResponse: {
      json: (body: any, init?: any) => {
        const resp = {
          body,
          status: init?.status || 200,
          cookies: {
            _store: {} as Record<string, any>,
            set(name: string, value: string, opts: any) {
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
    expect(resp.cookies._store["nuri-auth"]).toBeDefined();
    expect(resp.cookies._store["nuri-auth"].httpOnly).toBe(true);
  });

  it("cookie value is SHA256 hash, not plaintext", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "mypass");
    const { POST } = await import("@/app/api/auth/route");
    const req = new Request("http://localhost:3000/api/auth", {
      method: "POST",
      body: JSON.stringify({ password: "mypass" }),
    });
    const resp = await POST(req);
    const cookie = resp.cookies._store["nuri-auth"];
    expect(cookie.value).not.toBe("mypass");
    expect(cookie.value.length).toBe(64); // SHA256 hex = 64 chars
  });
});
