import { describe, it, expect, vi, beforeEach } from "vitest";
import { createHmac } from "node:crypto";
import type { NextRequest } from "next/server";

// Mock next/server
vi.mock("next/server", () => {
  const next = vi.fn(() => ({ type: "next" }));
  const redirect = vi.fn((url: URL) => ({ type: "redirect", url: url.toString() }));
  return {
    NextResponse: { next, redirect },
  };
});

describe("middleware", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("passes through when no DASHBOARD_PASSWORD set", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "");
    const { middleware } = await import("@/middleware");

    const request = {
      nextUrl: { pathname: "/" },
      cookies: { get: () => undefined },
      url: "http://localhost:3000/",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result).toEqual({ type: "next" });
  });

  it("passes through for /login path", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { middleware } = await import("@/middleware");

    const request = {
      nextUrl: { pathname: "/login" },
      cookies: { get: () => undefined },
      url: "http://localhost:3000/login",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result).toEqual({ type: "next" });
  });

  it("passes through for /api/auth path", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { middleware } = await import("@/middleware");

    const request = {
      nextUrl: { pathname: "/api/auth" },
      cookies: { get: () => undefined },
      url: "http://localhost:3000/api/auth",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result).toEqual({ type: "next" });
  });

  it("redirects to /login when no auth cookie", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { middleware } = await import("@/middleware");

    const request = {
      nextUrl: { pathname: "/dashboard" },
      cookies: { get: () => undefined },
      url: "http://localhost:3000/dashboard",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result.type).toBe("redirect");
  });

  it("passes through with valid auth cookie", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    // #1136: 앰비언트 환경에 기대지 않는다 — AUTH_SECRET 을 명시 stub 해야
    // 러너 환경에 AUTH_SECRET 이 있어도(래퍼 프로세스 등) 결과가 갈리지 않는다.
    vi.stubEnv("AUTH_SECRET", "test-auth-secret");
    const { middleware } = await import("@/middleware");

    // Generate the expected token using the same HMAC scheme as the
    // production auth-token helper. The body of the hash is the static
    // label "nuri-auth-token:v1" — password content is intentionally NOT
    // mixed in (CodeQL would flag that as an insecure password hash
    // regardless of the HMAC key).
    const expectedToken = createHmac("sha256", "test-auth-secret")
      .update("nuri-auth-token:v1")
      .digest("hex");

    const request = {
      nextUrl: { pathname: "/dashboard" },
      cookies: { get: (name: string) => name === "nuri-auth" ? { value: expectedToken } : undefined },
      url: "http://localhost:3000/dashboard",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result).toEqual({ type: "next" });
  });

  it("falls back to DASHBOARD_PASSWORD as HMAC key when AUTH_SECRET is empty", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    vi.stubEnv("AUTH_SECRET", "");
    const { middleware } = await import("@/middleware");

    const expectedToken = createHmac("sha256", "secret123")
      .update("nuri-auth-token:v1")
      .digest("hex");

    const request = {
      nextUrl: { pathname: "/dashboard" },
      cookies: { get: (name: string) => name === "nuri-auth" ? { value: expectedToken } : undefined },
      url: "http://localhost:3000/dashboard",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result).toEqual({ type: "next" });
  });

  it("redirects with wrong auth cookie", async () => {
    vi.stubEnv("DASHBOARD_PASSWORD", "secret123");
    const { middleware } = await import("@/middleware");

    const request = {
      nextUrl: { pathname: "/dashboard" },
      cookies: { get: (name: string) => name === "nuri-auth" ? { value: "wrong-hash" } : undefined },
      url: "http://localhost:3000/dashboard",
    };

    const result = await middleware(request as unknown as NextRequest);
    expect(result.type).toBe("redirect");
  });

  it("exports correct matcher config", async () => {
    const { config } = await import("@/middleware");
    expect(config.matcher).toBeDefined();
    expect(config.matcher.length).toBeGreaterThan(0);
  });
});
