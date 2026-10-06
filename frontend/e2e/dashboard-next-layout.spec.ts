import { test, expect } from "@playwright/test";

// 공통 컨테이너 상한과 고정 높이가 큰 화면의 여백을 만들던 회귀를 검증한다.
for (const [width, height] of [[1440, 900], [1920, 1080], [2560, 1440], [3440, 1440], [1280, 800], [390, 844]]) {
  test(`overview fills available space and keeps content reachable at ${width}x${height}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await page.goto("/dashboard-next");
    const dashboard = page.getByRole("main").getByTestId("overview-dashboard");
    await expect(dashboard).toBeVisible();
    const bounds = await dashboard.evaluate(el => {
      const rect = el.getBoundingClientRect();
      const main = el.closest("main")!;
      const style = getComputedStyle(main);
      const available = main.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
      return { width: rect.width, bottom: rect.bottom, available, horizontal: document.documentElement.scrollWidth > innerWidth, vertical: document.documentElement.scrollHeight > innerHeight };
    });
    expect(bounds.horizontal).toBe(false);
    expect(Math.abs(bounds.width - bounds.available)).toBeLessThan(2);
    if (width > 1050 && height > 850) {
      expect(bounds.vertical).toBe(false);
      expect(bounds.bottom).toBeGreaterThan(height - 40);
      const hiddenRows = await dashboard.evaluate(el => [...el.querySelectorAll('[class*="pipelineRow"], [class*="evidenceLink"], tbody tr')].filter(row => {
        const footer = row.closest("section")?.querySelector('[class*="panelFooter"]');
        return footer && row.getBoundingClientRect().bottom > footer.getBoundingClientRect().top + 1;
      }).length);
      expect(hiddenRows).toBe(0);
    }
    if (width >= 1920) {
      const fontSize = await dashboard.locator('[class*="compositionRow"]').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize));
      expect(fontSize).toBeGreaterThanOrEqual(12);
    }
  });
}
