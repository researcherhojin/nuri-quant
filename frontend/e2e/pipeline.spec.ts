import { test, expect } from "@playwright/test";
import { PIPELINE } from "../src/lib/strings";

test.describe("Pipeline page", () => {
  test("renders the title, legend and both panels", async ({ page }) => {
    await page.goto("/pipeline", { timeout: 15000 });
    const main = page.locator("main");
    // body 길이만 보던 시절엔 에러 화면도 통과했다 (#1791)
    await expect(main.getByRole("heading", { level: 1, name: PIPELINE.TITLE })).toBeVisible();

    for (const legend of [PIPELINE.LEGEND_OK, PIPELINE.LEGEND_WARN, PIPELINE.LEGEND_ERROR, PIPELINE.LEGEND_RUNNING]) {
      await expect(main.getByText(legend, { exact: true }).first()).toBeVisible();
    }

    await expect(main.getByText(PIPELINE.EVENT_TIMELINE, { exact: true })).toBeVisible();
    await expect(main.getByText(PIPELINE.GATE_CONDITIONS, { exact: true })).toBeVisible();
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

  test("polls the status endpoint every 10 seconds", async ({ page }) => {
    // 3초 대기 뒤 body 길이를 보던 시절엔 폴링이 죽어도 통과했다 (#1791) — 요청을 직접 센다
    let statusCalls = 0;
    page.on("request", (r) => {
      if (r.url().includes("/api/pipeline/status")) statusCalls += 1;
    });
    await page.goto("/pipeline", { timeout: 15000 });
    // 첫 로드의 요청이 끝난 뒤를 기준으로 센다 — dev 의 StrictMode 는 effect 를 두 번 돌려 첫 로드에서
    // 이미 2회가 나간다. 그 위로 하나 더 늘어야 10초 폴링이 실제로 돈 것이다.
    await expect(page.locator("main .react-flow__node")).toHaveCount(5);
    await page.waitForLoadState("networkidle");
    const afterLoad = statusCalls;
    await expect.poll(() => statusCalls, { timeout: 15000 }).toBeGreaterThan(afterLoad);
  });
});
