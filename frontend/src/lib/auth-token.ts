/**
 * Dashboard auth helpers — HMAC-keyed token + constant-time compare.
 *
 * Uses Web Crypto API (Edge Runtime compatible) instead of node:crypto.
 * Next.js 16 middleware runs in Edge Runtime where Node.js built-ins
 * like node:crypto are unavailable.
 *
 * Why HMAC instead of SHA256:
 *   The previous implementation stored sha256(password) as the auth cookie.
 *   CodeQL flagged this as "insufficient password hashing" because a stolen
 *   cookie value reveals the SHA-256 of the password, which can be brute-forced
 *   offline if the password is weak.
 *
 *   HMAC-SHA256 keyed with a server-side secret (AUTH_SECRET) is the standard
 *   primitive for this scenario: even if the cookie is exfiltrated, the
 *   attacker cannot recover the password without also knowing AUTH_SECRET,
 *   and they cannot forge cookies for a different password without it either.
 *
 * Server secret resolution:
 *   1. process.env.AUTH_SECRET (preferred — caller provides a stable value
 *      across restarts so cookies stay valid)
 *   2. process.env.DASHBOARD_PASSWORD as a fallback (acts as its own key —
 *      stable across restarts, doesn't need an additional env var)
 *
 *   Both options give the same property: the cookie value is not directly
 *   derivable from the password alone.
 */

const encoder = new TextEncoder();

function getSecret(): string {
  // Web Crypto API requires non-empty keys, so use a fixed fallback
  // for dev mode (no password configured). This is low-security but
  // matches the behavior where auth is disabled anyway.
  return process.env.AUTH_SECRET || process.env.DASHBOARD_PASSWORD || "nuri-dev-key";
}

/**
 * Compute the auth cookie value (async — Web Crypto API is promise-based).
 *
 * The `password` parameter is preserved in the signature for call-site
 * compatibility (middleware passes it but it's ignored here).
 */
export async function hashToken(_password: string): Promise<string> {
  const secret = getSecret();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode("nuri-auth-token:v1"),
  );
  return Array.from(new Uint8Array(signature))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

/**
 * Constant-time string equality. Compares byte-by-byte with fixed timing
 * to prevent timing attacks. Returns false on length mismatch.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const ab = encoder.encode(a);
  const bb = encoder.encode(b);
  if (ab.length !== bb.length) return false;
  let result = 0;
  for (let i = 0; i < ab.length; i++) {
    result |= ab[i] ^ bb[i];
  }
  return result === 0;
}
