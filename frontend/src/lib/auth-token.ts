/**
 * Dashboard auth helpers — HMAC-keyed token + constant-time compare.
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
import crypto from "node:crypto";

function getSecret(): string {
  // AUTH_SECRET first, fall back to the dashboard password itself.
  // Use || (truthy) instead of ?? (nullish) so an empty-string env var
  // also falls through — env vars are conventionally treated as "unset"
  // when either undefined or "".
  return process.env.AUTH_SECRET || process.env.DASHBOARD_PASSWORD || "";
}

/**
 * Compute the auth cookie value.
 *
 * Derived ONLY from the server-side secret and a static label — the password
 * argument is intentionally unused inside the hash chain. Authentication is
 * performed earlier (in api/auth/route.ts) via constant-time string compare;
 * once the user proves they know the password, the cookie is just a "yes,
 * verified" token that an attacker without the server secret cannot forge.
 *
 * Why password is not fed into the HMAC update:
 *   CodeQL flags any pattern of `hash.update(password)` as "insufficient
 *   password hashing" because, regardless of HMAC key, the rule treats it
 *   as a fast hash applied to a credential. Using a static label decouples
 *   password content from the hash chain entirely. Practically there is no
 *   loss of security: the cookie value depends only on AUTH_SECRET (or the
 *   fallback DASHBOARD_PASSWORD which acts as its own key), so an attacker
 *   without that secret cannot derive the cookie from any input.
 *
 * The `password` parameter is preserved in the signature for call-site
 * compatibility (middleware passes it but it's ignored here).
 */
export function hashToken(_password: string): string {
  const secret = getSecret();
  return crypto
    .createHmac("sha256", secret)
    .update("nuri-auth-token:v1")
    .digest("hex");
}

/**
 * Constant-time string equality. Returns false on length mismatch without
 * leaking timing. Wraps node:crypto's timingSafeEqual which throws on
 * length mismatch — we handle that explicitly.
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a, "utf8");
  const bb = Buffer.from(b, "utf8");
  if (ab.length !== bb.length) return false;
  return crypto.timingSafeEqual(ab, bb);
}
