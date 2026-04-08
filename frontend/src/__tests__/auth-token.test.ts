/**
 * Unit tests for auth-token helper.
 * Covers all branches of hashToken() and timingSafeEqual() — including the
 * length-mismatch fallback that the route-level tests don't reach.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";

describe("auth-token", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  describe("hashToken", () => {
    it("derives the same value from the same secret regardless of password input", async () => {
      vi.stubEnv("AUTH_SECRET", "shared-secret");
      const { hashToken } = await import("@/lib/auth-token");

      const a = hashToken("password-1");
      const b = hashToken("password-2");
      const c = hashToken("");

      // Password is intentionally NOT mixed into the HMAC chain — all calls
      // produce the same value because they share the same server secret.
      expect(a).toBe(b);
      expect(a).toBe(c);
      // 64 hex chars = SHA-256 output length.
      expect(a).toHaveLength(64);
    });

    it("uses AUTH_SECRET in preference to DASHBOARD_PASSWORD", async () => {
      vi.stubEnv("AUTH_SECRET", "primary-key");
      vi.stubEnv("DASHBOARD_PASSWORD", "fallback-key");
      const { hashToken } = await import("@/lib/auth-token");

      const tokenWithBoth = hashToken("ignored");

      // Compute the expected value with only AUTH_SECRET to confirm the
      // fallback isn't being used.
      const crypto = require("crypto");
      const expected = crypto
        .createHmac("sha256", "primary-key")
        .update("nuri-auth-token:v1")
        .digest("hex");

      expect(tokenWithBoth).toBe(expected);
    });

    it("falls back to DASHBOARD_PASSWORD when AUTH_SECRET is unset", async () => {
      vi.stubEnv("AUTH_SECRET", "");
      vi.stubEnv("DASHBOARD_PASSWORD", "fallback-key");
      const { hashToken } = await import("@/lib/auth-token");

      const token = hashToken("ignored");

      const crypto = require("crypto");
      const expected = crypto
        .createHmac("sha256", "fallback-key")
        .update("nuri-auth-token:v1")
        .digest("hex");

      expect(token).toBe(expected);
    });

    it("falls back to empty string secret when both env vars are unset", async () => {
      vi.stubEnv("AUTH_SECRET", "");
      vi.stubEnv("DASHBOARD_PASSWORD", "");
      const { hashToken } = await import("@/lib/auth-token");

      // Should not throw — HMAC accepts an empty key (low security but
      // matches dev mode where no password is configured).
      const token = hashToken("ignored");
      expect(token).toHaveLength(64);
    });
  });

  describe("timingSafeEqual", () => {
    it("returns true for identical strings", async () => {
      const { timingSafeEqual } = await import("@/lib/auth-token");
      expect(timingSafeEqual("hello", "hello")).toBe(true);
      expect(timingSafeEqual("", "")).toBe(true);
    });

    it("returns false for different strings of equal length", async () => {
      const { timingSafeEqual } = await import("@/lib/auth-token");
      expect(timingSafeEqual("abc", "xyz")).toBe(false);
    });

    it("returns false for length mismatch without throwing", async () => {
      // This is the branch that route-level tests don't reach. node:crypto's
      // timingSafeEqual throws on length mismatch, so the wrapper must
      // short-circuit before calling into it.
      const { timingSafeEqual } = await import("@/lib/auth-token");
      expect(() => timingSafeEqual("short", "longer-string")).not.toThrow();
      expect(timingSafeEqual("short", "longer-string")).toBe(false);
      expect(timingSafeEqual("", "x")).toBe(false);
    });

    it("handles unicode strings correctly", async () => {
      const { timingSafeEqual } = await import("@/lib/auth-token");
      expect(timingSafeEqual("한글", "한글")).toBe(true);
      expect(timingSafeEqual("한글", "韓國")).toBe(false);
    });
  });
});
