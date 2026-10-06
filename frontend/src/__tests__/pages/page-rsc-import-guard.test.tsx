/**
 * RSC boundary import guard — Gotcha-Test Pair (frontend/CLAUDE.md "Server Components Pattern").
 *
 * next 16.2.9+ throws at *request time* when a Server Component calls a function it imported
 * from a `"use client"` module: the import becomes a client reference, not the function. The
 * original trip was `parseCompositionTab` re-exported through a client wrapper (#731), which
 * left with the old dashboard (#1698). `next build` and jsdom render both miss it, so this
 * guard reads the import source text instead.
 *
 * Rule: a server `page.tsx` may take only components (PascalCase) or `type`-only names from a
 * `"use client"` module. Overview already works around it — `buckets` is re-declared in
 * `(overview)/page.tsx` instead of imported from the client `inbox.tsx`.
 */
import { describe, it, expect } from "vitest";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

const SRC = resolve(here, "../..");

const APP = join(SRC, "app");

function pages(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);

    if (statSync(path).isDirectory()) return pages(path);

    return name === "page.tsx" ? [path] : [];
  });
}

function resolveModule(from: string, spec: string): string | null {
  const base = spec.startsWith("@/") ? join(SRC, spec.slice(2)) : spec.startsWith(".") ? resolve(dirname(from), spec) : null;

  if (base === null) return null;

  return [".tsx", ".ts", "/index.tsx", "/index.ts"].map((ext) => base + ext).find((file) => existsSync(file)) ?? null;
}

const isClient = (file: string) => /^\s*["']use client["']/.test(readFileSync(file, "utf8"));

/** `page.tsx` 가 클라이언트 모듈에서 값으로 가져오는 이름 중 컴포넌트가 아닌 것 */
function clientValueImports(page: string, source = readFileSync(page, "utf8")): string[] {
  const out: string[] = [];

  for (const match of source.matchAll(/^import\s+(type\s+)?(?:(\w+)\s*,?\s*)?(?:\{([^}]*)\})?\s*from\s*["']([^"']+)["']/gm)) {
    const [, typeOnly, defaultName, named, spec] = match;
    const file = resolveModule(page, spec);

    if (typeOnly || file === null || !isClient(file)) continue;

    for (const part of [defaultName ?? "", ...(named ?? "").split(",")]) {
      const name = part.trim().split(/\s+as\s+/)[0];

      // 컴포넌트(PascalCase)만 통과 — `NAV_GROUPS` 같은 대문자 상수도 클라이언트 참조라 서버에서 쓰면 터진다
      if (name && !name.startsWith("type ") && !/^[A-Z](?![A-Z0-9_]*$)/.test(name)) out.push(`${spec}:${name}`);
    }
  }

  return out;
}

const isServer = (file: string) => !isClient(file);

describe("server page RSC import boundary", () => {
  const serverPages = pages(APP).filter(isServer);

  it("finds the server pages it guards", () => {
    expect(serverPages.map((file) => file.slice(APP.length))).toContain("/(overview)/page.tsx");
  });

  it.each(serverPages.map((file) => [file.slice(APP.length), file]))("%s takes only components or types from client modules", (_, file) => {
    expect(clientValueImports(file)).toEqual([]);
  });

  it("catches a helper imported from a client module (canary)", () => {
    const page = join(APP, "(overview)/page.tsx");

    expect(clientValueImports(page, 'import { Inbox, buckets, type Bucket } from "./inbox";')).toEqual(["./inbox:buckets"]);
    expect(clientValueImports(page, 'import { Sidebar, NAV_GROUPS } from "@/components/ui/sidebar";')).toEqual(["@/components/ui/sidebar:NAV_GROUPS"]);
  });
});
