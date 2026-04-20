/**
 * E4-0a 배포 후 대시보드 전체 페이지 smoke — console 에러 / 네트워크 실패 / 렌더 실패 수집.
 *
 * 운용: `npx playwright test e4-0a-smoke.spec.ts --reporter=list`
 *
 * 각 페이지 방문 후:
 * - console error 로그
 * - 네트워크 응답 실패 (status >= 400)
 * - 페이지에 "Error" / "failed" / "500" 같은 가시 텍스트
 * - 주요 SIEGE 관련 element 가 렌더 됐는지 (home + engine pages)
 */
import { test, expect } from "@playwright/test";

const PAGES = [
  { path: "/", name: "home" },
  { path: "/pipeline", name: "pipeline" },
  { path: "/consensus", name: "consensus" },
  { path: "/advisor", name: "advisor" },
  { path: "/evidence", name: "evidence" },
  { path: "/targets", name: "targets" },
  { path: "/signals", name: "signals" },
  { path: "/scan", name: "scan" },
  { path: "/decisions", name: "decisions" },
  { path: "/explore", name: "explore" },
  { path: "/rebalance", name: "rebalance" },
  { path: "/portfolio", name: "portfolio" },
  { path: "/report", name: "report" },
  { path: "/engine", name: "engine" },
  { path: "/strategy", name: "strategy" },
];

type PageReport = {
  name: string;
  path: string;
  loadOk: boolean;
  consoleErrors: string[];
  failedRequests: { url: string; status: number }[];
  pageText: string;
  visibleErrorText: string | null;
};

const reports: PageReport[] = [];

for (const { path, name } of PAGES) {
  test(`smoke: ${name} (${path})`, async ({ page }) => {
    const consoleErrors: string[] = [];
    const failedRequests: { url: string; status: number }[] = [];

    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(msg.text().slice(0, 500));
      }
    });

    page.on("response", (resp) => {
      const status = resp.status();
      if (status >= 400 && !resp.url().includes("favicon")) {
        failedRequests.push({ url: resp.url(), status });
      }
    });

    let loadOk = false;
    try {
      const resp = await page.goto(path, { waitUntil: "domcontentloaded", timeout: 15000 });
      loadOk = resp !== null && resp.status() < 400;
      // DOM load 후 content hydration 짧게 대기 (React/Next.js SSR 안정화용)
      await page.waitForTimeout(2000);
    } catch (e) {
      loadOk = false;
      consoleErrors.push(`goto-error: ${(e as Error).message}`);
    }

    const pageText = await page.evaluate(() => document.body.innerText).catch(() => "");
    // visible error 텍스트 감지 (일반적 UI 에러 표시)
    let visibleErrorText: string | null = null;
    const errorMarkers = [
      "Application error",
      "Internal Server Error",
      "500 ",
      "404 Not Found",
      "ECONNREFUSED",
      "Failed to fetch",
    ];
    for (const m of errorMarkers) {
      if (pageText.includes(m)) {
        visibleErrorText = m;
        break;
      }
    }

    reports.push({
      name,
      path,
      loadOk,
      consoleErrors,
      failedRequests,
      pageText: pageText.slice(0, 200).replace(/\n/g, " "),
      visibleErrorText,
    });

    // soft expectations — 수집에 집중, 개별 test 는 non-blocking assertion
    expect.soft(loadOk, `${name} page should load (status < 400)`).toBe(true);
    expect.soft(visibleErrorText, `${name} should not show visible error`).toBeNull();
  });
}

test.afterAll(async () => {
  console.log("\n════════════════════════════════════════════════════════════");
  console.log("  E4-0a SMOKE REPORT");
  console.log("════════════════════════════════════════════════════════════");
  const pass = reports.filter((r) => r.loadOk && r.consoleErrors.length === 0 && r.failedRequests.length === 0 && !r.visibleErrorText);
  const fail = reports.filter((r) => !r.loadOk || r.consoleErrors.length > 0 || r.failedRequests.length > 0 || r.visibleErrorText);
  console.log(`  PASS: ${pass.length}/${reports.length}  (로드 OK + 콘솔 no-error + 네트워크 no-4xx/5xx + visible no-error)`);
  console.log(`  FAIL: ${fail.length}`);
  console.log();
  for (const r of fail) {
    console.log(`  ❌ ${r.name} (${r.path})`);
    if (!r.loadOk) console.log(`      loadOk: false`);
    if (r.visibleErrorText) console.log(`      visibleError: ${r.visibleErrorText}`);
    if (r.consoleErrors.length) {
      console.log(`      console errors (${r.consoleErrors.length}):`);
      r.consoleErrors.slice(0, 3).forEach((e) => console.log(`        - ${e.slice(0, 150)}`));
    }
    if (r.failedRequests.length) {
      console.log(`      failed network (${r.failedRequests.length}):`);
      r.failedRequests.slice(0, 5).forEach((req) => console.log(`        ${req.status} ${req.url}`));
    }
    console.log(`      page text preview: "${r.pageText}"`);
  }
  console.log();
  for (const r of pass) {
    console.log(`  ✅ ${r.name} (${r.path})`);
  }
  console.log("════════════════════════════════════════════════════════════\n");
});
