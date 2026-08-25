import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.spec.ts",
  timeout: 30000,
  retries: 0,
  // 기본값(코어/2 = M5 Max 에서 8)은 spec 파일 8개를 단일 Next 프로세스와 단일
  // uvicorn 에 동시 투입한다. 모든 페이지가 force-dynamic Server Component 라
  // 페이지 하나가 여러 API 호출을 낸다.
  // ⚠️ 이 캡은 완화지 해결이 아니다. 실측(2026-08-20): workers=2 로 줄이고
  //    expect 예산을 15s 로 올려도 explore 검색 2건은 여전히 깨진다. 진짜 병목은
  //    Playwright 가 아니라 API 다 — 무거운 sync 핸들러(/api/scan 은 요청마다
  //    yfinance 85종목, /api/report/context 161s)가 AnyIO 40-스레드 풀을 채우고,
  //    클라이언트가 끊어도 계속 돌아 백로그가 남는다. 포화 시 /api/health 조차
  //    46.7s 대기(50×/api/scan 부하 실측). 그 이슈가 닫히기 전에는 이 스위트가
  //    전부 초록이 되지 않는다. 여기 숫자를 더 키워 초록으로 만들지 말 것.
  workers: 2,
  expect: { timeout: 15000 },
  // CI 기본 reporter 는 dot 이라 playwright-report/ 가 아예 안 생긴다 — HTML 을
  // 명시해야 frontend-e2e job 의 실패 아티팩트가 실제로 존재한다 (codex #1243).
  // 로컬은 기본값(list) 유지.
  reporter: process.env.CI ? [["dot"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { browserName: "chromium" } },
  ],
  // Start both backend API and frontend server
  webServer: [
    {
      command: "cd .. && .venv/bin/python -m uvicorn nuri.api.main:app --host 0.0.0.0 --port 8001",
      port: 8001,
      timeout: 15000,
      reuseExistingServer: true,
    },
    {
      // ⚠️ `npm run build && npm run start` 로 바꾸지 말 것 — 실측으로 더 나빠진다
      //    (2026-08-20: dev 3 fail → prod 16 fail, workers=1 에서도 6 fail).
      //    프로덕션 빌드는 페이지를 즉시 서빙해 API 를 더 세게 때리는데, 병목은
      //    Next 가 아니라 API 쪽이다(사이드 이슈: 무거운 sync 핸들러가 40-스레드
      //    풀을 점유하고 클라이언트가 끊어도 계속 돈다). 게다가 `next start` 의
      //    서버사이드 fetch 는 undici 30s headers timeout 이라 "느림" 이 500 으로
      //    바뀐다(UND_ERR_HEADERS_TIMEOUT). API 동시성이 해결된 뒤 재시도할 것.
      command: "npm run dev",
      port: 3000,
      timeout: 30000,
      reuseExistingServer: true,
    },
  ],
});
