/**
 * RSC boundary import guard for src/app/page.tsx.
 *
 * Gotcha-Test Pair (frontend/CLAUDE.md "Server Components Pattern"):
 * next 16.2.9 blocks a Server Component from calling a function re-exported
 * through a "use client" module. `composition-section-lazy.tsx` is "use client"
 * and re-exports the pure `parseCompositionTab`; importing it there from
 * page.tsx (a Server Component) made next treat it as a client reference and
 * throw at request time — the whole dashboard rendered the error boundary.
 *
 * This regression is invisible to `next build` and vitest render (it only fires
 * during a real server render), so this guard asserts the *import source* in
 * page.tsx source text: parseCompositionTab must come from the server module
 * `composition-section`. (#731)
 *
 * #1210: the "use client" lazy wrapper was deleted (donut → server-pure bar),
 * so the negative assertion now guards against *re-introducing* the pattern —
 * a future -lazy wrapper that re-exports server utils would re-trip the same
 * request-time error.
 */
import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const pageSrc = readFileSync(resolve(here, "../../app/page.tsx"), "utf8");

describe("page.tsx RSC import boundary", () => {
  it("imports parseCompositionTab from the server module, not the client wrapper", () => {
    // parseCompositionTab must be imported from composition-section (server).
    expect(pageSrc).toMatch(
      /import\s*\{[^}]*\bparseCompositionTab\b[^}]*\}\s*from\s*["']@\/components\/ui\/composition-section["']/,
    );
    // ...and never from the "use client" lazy wrapper (would re-trip the next
    // 16.2.9 RSC boundary error).
    expect(pageSrc).not.toMatch(
      /import\s*\{[^}]*\bparseCompositionTab\b[^}]*\}\s*from\s*["']@\/components\/ui\/composition-section-lazy["']/,
    );
  });
});
