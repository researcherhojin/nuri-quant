/**
 * Client-side absolute-URL guard for "use client" modules.
 *
 * Gotcha-Test Pair (frontend/CLAUDE.md "API Access Pattern"):
 * `API_BASE` is `process.env.NEXT_PUBLIC_API_URL`, which Next inlines at BUILD
 * time. That value is a *server-side* address (`http://localhost:8001`, or a
 * private LAN IP). A Server Component resolves it on the Mac mini and it works.
 * A "use client" module resolves it in the visitor's BROWSER, where
 * `localhost:8001` is the visitor's own laptop — so the connection dies.
 *
 * This actually shipped: the production bundle had `http://localhost:8001`
 * baked in, so `useStream` / `useTraceStream` opened an EventSource against the
 * viewer's machine and every live indicator and reasoning trace silently never
 * connected. Neither `next build` nor a jsdom render catches it — jsdom stubs
 * EventSource and the build only sees a valid template string.
 *
 * So this guard asserts the *source text*: no "use client" module may build a
 * request URL from API_BASE. Client code must use a relative path so the
 * next.config `rewrites()` proxy forwards it server-side.
 *
 * If reverted, live indicators and the consensus trace stream go dead for every
 * browser that is not running on the API host itself.
 */
import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve, join, relative } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = resolve(here, "../..");

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "__tests__" || entry === "node_modules") continue;
      walk(full, out);
    } else if (/\.tsx?$/.test(entry) && !/\.(test|coverage|branchcov)\./.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

const clientModules = walk(srcRoot)
  .map((path) => ({ path, src: readFileSync(path, "utf8") }))
  .filter(({ src }) => /^\s*["']use client["']/.test(src));

describe('"use client" modules never build request URLs from API_BASE', () => {
  it("finds client modules to check (guard is not vacuously passing)", () => {
    expect(clientModules.length).toBeGreaterThan(0);
  });

  it.each(clientModules.map(({ path, src }) => [relative(srcRoot, path), src]))(
    "%s does not import API_BASE",
    (_name, src) => {
      expect(src).not.toMatch(/import\s*\{[^}]*\bAPI_BASE\b[^}]*\}\s*from/);
    },
  );

  it.each(clientModules.map(({ path, src }) => [relative(srcRoot, path), src]))(
    "%s does not interpolate API_BASE into a URL",
    (_name, src) => {
      expect(src).not.toMatch(/\$\{\s*API_BASE\s*\}/);
    },
  );

  it("keeps the two SSE hooks on relative paths", () => {
    const stream = readFileSync(resolve(srcRoot, "lib/use-stream.ts"), "utf8");
    const trace = readFileSync(resolve(srcRoot, "lib/use-trace-stream.ts"), "utf8");
    expect(stream).toMatch(/new EventSource\(\s*["']\/api\/stream["']\s*\)/);
    expect(trace).toMatch(/new EventSource\(\s*[\s\S]{0,40}`\/api\/consensus\//);
  });
});
