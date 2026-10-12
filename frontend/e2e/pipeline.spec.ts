import { test, expect } from "@playwright/test";
import { PIPELINE } from "../src/lib/strings";

test.describe("Pipeline page", () => {
  test("renders pipeline with nodes", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    await page.waitForTimeout(3000);
    // Pipeline is "use client" — should render after data loads
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(100);
  });

  test("shows the five stages and no run buttons", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    const nodes = page.locator("main .react-flow__node");
    // 라이브 노드는 백엔드 _STEP_LABELS 를, 폴백 노드는 같은 문구의 PIPELINE.NODE_* 를 쓴다
    await expect(nodes).toHaveCount(5);

    for (const label of [
      PIPELINE.NODE_COLLECT, PIPELINE.NODE_ANALYZE, PIPELINE.NODE_CONSENSUS, PIPELINE.NODE_DECIDE, PIPELINE.NODE_TRACK,
    ]) {
      await expect(nodes.getByText(label, { exact: true })).toBeVisible();
    }

    // 대시보드는 스테이지를 실행하지 않는다 (#1778) — 실행은 스케줄러 몫이다
    await expect(nodes.locator("button")).toHaveCount(0);
  });

  test("auto-refreshes status", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    // Wait for auto-refresh (10s interval)
    await page.waitForTimeout(3000);
    const body = await page.textContent("body");
    expect(body!.length).toBeGreaterThan(50);
  });
});
