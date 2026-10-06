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

      // 행이 하나도 없으면 "잘림 0" 은 공허하다 (Codex #1658 P1 r1·r2) — 범주별로 후보 수를 먼저 잠근다.
      // 파이프라인은 항상 5단계를 그리므로 그것만으로는 표 행·원장 링크의 부재를 못 잡는다. 시드 DB 는
      // 기회 탐색 3종(volume_spike)과 same-date 판정(decision_id) 을 보장한다 (scripts/dev/seed_e2e_db.py).
      const rows = await dashboard.evaluate(el => {
        const count = (selector: string) => {
          const all = [...el.querySelectorAll(selector)];

          const hidden = all.filter(row => {
            const footer = row.closest("section")?.querySelector('[class*="panelFooter"]');

            return footer && row.getBoundingClientRect().bottom > footer.getBoundingClientRect().top + 1;
          });

          return { total: all.length, hidden: hidden.length };
        };

        return {
          pipeline: count('[class*="pipelineRow"]'),
          // 후보 표만 센다 — 지표 카드 모달의 출처 표(#1682)도 닫힌 채 DOM 에 있어 그냥 "tbody tr" 이면 항상 참이 된다
          table: count('[class*="candidates"] tbody tr'),
          ledger: count('[class*="evidenceLink"]'),
          queue: el.querySelectorAll('[class*="queue"] button').length,
          emptyBucket: /목록에 현재 표시할 항목이 없습니다/.test(el.textContent ?? ""),
        };
      });

      expect(rows.pipeline.total).toBeGreaterThanOrEqual(5);
      expect(rows.table.total).toBeGreaterThanOrEqual(1);

      // 점검 목록은 환경에 따라 비어 있을 수 있다 — `config/portfolio.yaml` 의 실계좌 필터(actions.py)가 시드의
      // placeholder 계좌를 걸러내면 로컬 시드 실행에서 네 버킷이 모두 빈다 (Codex #1658 r3 P2). CI 는 그 파일이
      // 없어 BBB SELL 이 urgent 에 들어온다. 항목이 있으면 원장 링크가 보여야 하고, 없으면 빈 상태 문구가 명시돼야 한다.
      if (rows.queue > 0) expect(rows.ledger.total).toBeGreaterThanOrEqual(1);
      else expect(rows.emptyBucket).toBe(true);
      expect([rows.pipeline.hidden, rows.table.hidden, rows.ledger.hidden]).toEqual([0, 0, 0]);
    }

    if (width >= 1920) {
      // 라벨 토큰 11px + 폭 증가분. 2026-10-06 "큰 화면에서 글자가 크다" 피드백으로 증가분을 줄였고,
      // 바닥은 UX plan §1 의 라벨 11px 이다 — 그 아래로 떨어지면 토큰 사다리가 깨진 것.
      const fontSize = await dashboard.locator('[class*="compositionRow"]').first().evaluate(el => parseFloat(getComputedStyle(el).fontSize));
      expect(fontSize).toBeGreaterThanOrEqual(11);
    }
  });
}

// 상세 모달은 표 셀 안에 렌더된다 — 탐색 후보 칸은 `text-align: right`, 파이프라인 decide 칸은 거기에
// `white-space: nowrap` 까지 준다. 상속을 끊지 않으면 본문이 오른쪽 정렬되고 글머리표만 왼쪽 끝에 남거나(#1692)
// 문단이 줄바꿈 없이 가로로 넘친다.
for (const [name, host] of [["radar", '[class*="candidates"] tbody td:last-child'], ["decide", '[class*="pipelineStatus"]']]) {
  test(`${name} detail dialog body is left-aligned and wraps inside its table cell`, async ({ page }) => {
    await page.goto("/dashboard-next");
    const cell = page.locator(host).filter({ has: page.locator("dialog") }).first();
    await cell.getByRole("button").click();
    const dialog = cell.locator("dialog[open]");
    await expect(dialog).toBeVisible();

    const styles = await dialog.evaluate(el => [...el.querySelectorAll("h3, p, li")].map(node => `${getComputedStyle(node).textAlign}/${getComputedStyle(node).whiteSpace}`));
    expect(styles.length).toBeGreaterThan(0);
    expect(new Set(styles)).toEqual(new Set(["left/normal"]));
  });
}
