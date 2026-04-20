/**
 * A2 fix lock — `/evidence` 페이지 iframe 이 X-Frame-Options SAMEORIGIN 정책 하에
 * 정상 로드되는지 검증. 이전에는 `/(.*)` → `X-Frame-Options: DENY` + CSP
 * `frame-ancestors 'none'` 이 same-origin iframe 도 차단 → 5 console 위반.
 *
 * 이 spec 은 regression lock — A2 fix 가 revert 되면 fail.
 */
import { test, expect } from "@playwright/test";

test("evidence page loads iframes without X-Frame-Options violations", async ({ page }) => {
  const frameViolations: string[] = [];
  page.on("console", (msg) => {
    const text = msg.text();
    if (msg.type() === "error" && text.includes("X-Frame-Options")) {
      frameViolations.push(text);
    }
  });

  const resp = await page.goto("/evidence", { waitUntil: "domcontentloaded", timeout: 20000 });
  expect(resp?.status()).toBe(200);

  // iframe 내부 컨텐츠 로드 대기
  await page.waitForTimeout(3000);

  // iframe 개수 확인 (evidence 는 Plotly 차트 N개 embed)
  const frameCount = await page.locator("iframe").count();
  expect(frameCount).toBeGreaterThan(0);

  // iframe 각각이 실제로 로드됐는지 (src + content-document)
  const frames = page.frames();
  // main frame + iframe들. main + at least one child.
  expect(frames.length).toBeGreaterThan(1);

  // X-Frame-Options 위반이 없어야
  expect(frameViolations).toEqual([]);
});

test("X-Frame-Options header is SAMEORIGIN on both page and api routes", async ({ request }) => {
  // Page
  const pageResp = await request.get("/login");
  expect(pageResp.headers()["x-frame-options"]).toBe("SAMEORIGIN");

  // API via Next.js proxy (same origin to browser)
  const apiResp = await request.get("/api/health");
  expect(apiResp.headers()["x-frame-options"]).toBe("SAMEORIGIN");
});

test("CSP frame-ancestors is 'self' (not 'none')", async ({ request }) => {
  const resp = await request.get("/login");
  const csp = resp.headers()["content-security-policy"] || "";
  expect(csp).toMatch(/frame-ancestors\s+'self'/);
  expect(csp).not.toMatch(/frame-ancestors\s+'none'/);
});
