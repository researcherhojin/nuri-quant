/**
 * #1252 — 사용자 노출 카피는 `src/lib/strings.ts` 를 거친다.
 *
 * SSoT 밖의 카피는 두 가지를 망가뜨린다: UI 가 반영반한(半英半韓)이 되고, e2e/vitest 의
 * "문자열은 strings.ts 에서 import" 원칙(`frontend/CLAUDE.md`)이 **적용될 수가 없다.**
 * 후자가 실제 사고로 이어진 적이 있다 — `410d385` 가 `CONTEXT.SIEGE` 를 rename 했을 때
 * 리터럴을 박아 둔 e2e 단언 3개가 3.5개월간 조용히 죽어 있었다 (#1118).
 *
 * 잠금은 두 축이다:
 *   - **한글 카피** — 이관 대상 파일에 주석을 뺀 한글이 남아 있지 않은가 (새로 하드코딩하면
 *     여기서 걸린다). 정규식 한 줄이라 신규 카피에도 자동으로 적용된다.
 *   - **영문 라벨** — 한글 스윕이 못 보는 축이다. 라우트 라벨처럼 영문인 카피는 SSoT 에
 *     키가 있고 소비자 파일에는 리터럴이 없어야 한다.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { NAV, PIPELINE, ACTION, CONTEXT, OPPORTUNITY } from "@/lib/strings";

/** 이관 대상 (#1252 이 지목한 파일). */
const MIGRATED = [
  "src/components/ui/sidebar.tsx",
  "src/app/pipeline/page.tsx",
  "src/components/ui/action-items.tsx",
  "src/components/dashboard/system-rail.tsx",
  "src/app/page.tsx",
];

const HANGUL = /[가-힣]/;

/** 주석은 카피가 아니다 — 이 레포는 한국어 주석이 규약이라 안 걷어내면 스윕이 전부 걸린다. */
function stripComments(src: string): string {
  return src
    .replace(/\{\/\*[\s\S]*?\*\/\}/g, "") // JSX 주석
    .replace(/\/\*[\s\S]*?\*\//g, "") // 블록 주석
    .replace(/^\s*\/\/.*$/gm, "") // 줄 주석
    .replace(/\s\/\/[^\n]*$/gm, ""); // 후행 주석
}

const read = (rel: string) => readFileSync(join(process.cwd(), rel), "utf8");

describe("사용자 카피는 strings.ts SSoT 를 거친다 (#1252)", () => {
  it("이관 대상 파일에 주석 밖 한글 카피가 남아 있지 않다", () => {
    const offenders: string[] = [];
    for (const rel of MIGRATED) {
      stripComments(read(rel))
        .split("\n")
        .forEach((line, i) => {
          if (HANGUL.test(line)) offenders.push(`${rel}:${i + 1} ${line.trim().slice(0, 80)}`);
        });
    }
    expect(offenders, `SSoT 밖 한글 카피:\n${offenders.join("\n")}`).toHaveLength(0);
  });

  it("영문 라벨도 리터럴로 남아 있지 않다", () => {
    // 한글 스윕이 **못 보는 축**이다. 사이드바 라우트 라벨이 전부 영문이라 이 검사가
    // 없으면 "이관 완료" 가 절반만 참인 채로 초록이 된다.
    const src = read("src/components/ui/sidebar.tsx");
    const labels = [
      NAV.ROUTE_DASHBOARD, NAV.ROUTE_DECISIONS, NAV.ROUTE_ENGINE, NAV.ROUTE_EVIDENCE,
      NAV.ROUTE_PORTFOLIO, NAV.ROUTE_REBALANCE, NAV.ROUTE_TARGETS, NAV.ROUTE_EXPLORE,
      NAV.ROUTE_SCANNER, NAV.ROUTE_SIGNALS, NAV.ROUTE_STRATEGY, NAV.ROUTE_AGENTS,
      NAV.ROUTE_PIPELINE, NAV.ROUTE_REPORT, NAV.SYSTEM_ONLINE,
    ];
    const offenders = labels.filter((v) => src.includes(`"${v}"`));
    expect(offenders, `사이드바에 리터럴로 남은 라벨: ${offenders.join(", ")}`).toHaveLength(0);

    // 주석을 걷고 본다 — 이 파일 주석이 라우트 이름을 언급하고 있어 그대로 보면 오탐이다.
    const pipe = stripComments(read("src/app/pipeline/page.tsx"));
    const nodeCopy = [
      PIPELINE.TITLE, // codex P3: 타이틀이 빠져 있어 하드코딩 복귀를 못 잡았다
      PIPELINE.NODE_COLLECT, PIPELINE.NODE_VALIDATE, PIPELINE.NODE_CLASSIFY,
      PIPELINE.NODE_DIAGNOSE, PIPELINE.NODE_RECOMMEND, PIPELINE.NODE_TRACK,
      PIPELINE.NODE_COLLECT_SUB, PIPELINE.NODE_VALIDATE_SUB, PIPELINE.NODE_CLASSIFY_SUB,
      PIPELINE.NODE_DIAGNOSE_SUB, PIPELINE.NODE_RECOMMEND_SUB, PIPELINE.NODE_TRACK_SUB,
    ];
    const pipeOffenders = nodeCopy.filter((v) => pipe.includes(`"${v}"`));
    expect(pipeOffenders, `pipeline 에 리터럴로 남은 노드 카피: ${pipeOffenders.join(", ")}`).toHaveLength(0);
  });

  it("이관한 키가 실제로 SSoT 에 있다", () => {
    // 소비자에서 리터럴만 지우고 키를 안 만들면 위 두 검사는 통과한다 — 반대 방향도 본다.
    for (const [group, keys] of [
      [NAV, ["ROUTE_DASHBOARD", "ROUTE_REPORT", "SYSTEM_ONLINE"]],
      [PIPELINE, ["TITLE", "RUN", "RUNNING", "NODE_COLLECT", "NODE_TRACK_SUB"]],
      [ACTION, ["PEEK_CURRENT", "PEEK_STOP", "PEEK_TP1", "PEEK_TP2", "PEEK_AS_OF"]],
      [CONTEXT, ["REGIME_SHIFT", "ATTENTION", "FAIL_SUFFIX"]],
      [OPPORTUNITY, ["ALL_PREFIX", "ALL_SUFFIX"]],
    ] as [Record<string, string>, string[]][]) {
      for (const k of keys) {
        expect(group[k], `${k} 키 부재`).toBeTruthy();
      }
    }
  });

  it("스윕이 실제로 눈이 있다 (canary)", () => {
    // 주석 제거가 과해서 본문까지 지워 버리면 위 스윕은 영원히 초록이다.
    expect(HANGUL.test(stripComments('const x = "손절";'))).toBe(true);
    expect(HANGUL.test(stripComments("{/* 한국어 주석 */}"))).toBe(false);
    expect(HANGUL.test(stripComments("// 한국어 줄 주석"))).toBe(false);
    expect(stripComments('const a = 1; // 주석\nconst b = "현재가";')).toContain("현재가");
  });
});
