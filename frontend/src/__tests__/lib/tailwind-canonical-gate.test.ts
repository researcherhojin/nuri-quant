/**
 * #1254 — tailwind canonical-class 게이트가 **실제로 막는지**.
 *
 * 이 레포의 규약: 게이트는 설정을 grep 해서 확인하지 않고 **돌려서 exit/결과로** 잠근다.
 * 이유가 기록으로 있다 — `rc=127` 로 3.5개월 no-op 이던 pre-push 테스트 단계(#910/#911)와
 * `exit 0` 으로 조용했던 PreToolUse 훅 2개(#953/#954). 규칙 이름이 설정 파일에 적혀 있다는
 * 사실은 그것이 발화한다는 증거가 아니다.
 *
 * 그래서 여기서는 프로젝트의 **실제 eslint 설정**으로 합성 위반을 린트해 결과를 본다.
 *
 * ⚠️ 심각도가 `error` 인 것까지 확인한다. CI 의 Frontend Lint 는 `npm run lint` = 맨
 * `eslint` 라 `--max-warnings` 가 없고, 워크플로 주석도 "errors-only gate; warnings
 * tolerated" 라고 적혀 있다. 즉 `warn` 으로 내려가면 게이트가 **초록인 채 아무것도 막지
 * 않는다** — 규칙이 켜져 있는지가 아니라 severity 가 이 게이트의 생사다.
 */
import { describe, expect, it } from "vitest";
import { ESLint } from "eslint";

/** 프로젝트 설정 그대로 — 별도 config 를 만들면 "설정이 맞나" 를 검사하지 못한다. */
const eslint = new ESLint({ cwd: process.cwd() });

const lint = async (code: string) => (await eslint.lintText(code, { filePath: "src/__gate_probe__.tsx" }))[0];

const twMessages = (r: Awaited<ReturnType<typeof lint>>) =>
  r.messages.filter((m) => m.ruleId?.startsWith("better-tailwindcss/"));

// `new ESLint()` + 전체 설정 해석이 무겁다. CI 러너에서 기본 5s 를 넘겨 실패했으므로
// (로컬은 통과 — 러너 속도 차이가 그대로 드러나는 축이다) 파일 전체에 여유를 준다.
describe("tailwind canonical-class 게이트 (#1254)", { timeout: 60_000 }, () => {
  it("#1249 의 legacy important 접두사를 error 로 막는다", async () => {
    const res = await lint(`export const A = () => <div className="flex !bg-muted" />;\n`);
    const hits = twMessages(res);

    expect(hits.length, "위반이 하나도 안 잡혔다 — 게이트가 죽었다").toBeGreaterThan(0);
    expect(hits.some((m) => m.ruleId === "better-tailwindcss/enforce-consistent-important-position")).toBe(true);
    // severity 2 = error. 1(warn) 이면 CI 가 통과시킨다.
    expect(hits.every((m) => m.severity === 2), "severity 가 error 가 아니다 — CI 는 warn 을 통과시킨다").toBe(true);
    expect(res.errorCount).toBeGreaterThan(0);
  });

  it("deprecated 클래스와 축약 가능 조합도 error 로 막는다", async () => {
    // severity 를 **규칙마다** 본다 (codex P2). 한 규칙만 확인하면 나머지가 warn 으로
    // 내려가도 이 파일이 통과한다 — 게이트 절반이 조용히 죽는 형태다.
    const dep = twMessages(await lint(`export const A = () => <div className="rounded" />;\n`));
    const depHit = dep.find((m) => m.ruleId === "better-tailwindcss/no-deprecated-classes");
    expect(depHit, "no-deprecated-classes 가 안 걸렸다").toBeDefined();
    expect(depHit?.severity, "no-deprecated-classes 가 error 가 아니다").toBe(2);

    const canon = twMessages(await lint(`export const A = () => <div className="w-12 h-12" />;\n`));
    const canonHit = canon.find((m) => m.ruleId === "better-tailwindcss/enforce-canonical-classes");
    expect(canonHit, "enforce-canonical-classes 가 안 걸렸다").toBeDefined();
    expect(canonHit?.severity, "enforce-canonical-classes 가 error 가 아니다").toBe(2);
  });

  it("켜 둔 규칙이 하나도 warn 으로 새지 않았다", async () => {
    // 위 두 검사는 발화하는 규칙만 본다. 설정에 켜진 **전체 집합**의 severity 를 직접 읽어
    // 아직 위반 예시가 없는 규칙(no-conflicting/no-duplicate)도 같이 잠근다.
    const cfg = await eslint.calculateConfigForFile("src/__gate_probe__.tsx");
    const tw = Object.entries(cfg.rules ?? {}).filter(([k]) => k.startsWith("better-tailwindcss/"));

    expect(tw.length, "규칙이 하나도 안 켜져 있다").toBeGreaterThanOrEqual(5);
    const notError = tw.filter(([, v]) => (Array.isArray(v) ? v[0] : v) !== 2 && (Array.isArray(v) ? v[0] : v) !== "error");
    expect(notError.map(([k]) => k), "error 가 아닌 규칙이 있다 — CI 는 warn 을 통과시킨다").toHaveLength(0);

    // 이어붙인 className 을 깨뜨리는 규칙은 **꺼져 있어야** 한다 (아래 테스트의 짝).
    expect(tw.map(([k]) => k)).not.toContain("better-tailwindcss/no-unnecessary-whitespace");
  });

  it("정본 클래스는 통과한다 (canary)", async () => {
    // 항상 실패하는 하네스는 위 검사를 무의미하게 만든다 — 반대 방향도 확인한다.
    const res = await lint(`export const A = () => <div className="flex size-12 rounded-sm bg-muted!" />;\n`);
    expect(twMessages(res), `정본 클래스가 걸렸다: ${JSON.stringify(twMessages(res))}`).toHaveLength(0);
  });

  it("이어붙인 className 의 필수 공백을 지우지 않는다", async () => {
    // `no-unnecessary-whitespace` 는 조각을 **홀로** 보고 앞뒤 연결을 모른다. 실측(#1254):
    // `}${cond ? " hidden sm:table-cell" : ""}` 의 선행 조각과 띄우는 필수 공백을 지워
    // `text-lefthidden` 을 만들었다 — autofix 라 조용하고, 클래스 둘이 동시에 죽는다.
    // 그래서 그 규칙은 켜지 않는다. 누가 되살리면 여기서 걸린다.
    const code = 'export const A = ({ c }: { c: boolean }) => <div className={`text-left${c ? " hidden sm:table-cell" : ""}`} />;\n';
    const res = await lint(code);
    expect(twMessages(res), `이어붙인 공백을 위반으로 잡았다: ${JSON.stringify(twMessages(res))}`).toHaveLength(0);
    expect(res.output ?? code, "autofix 가 필수 공백을 지웠다").toContain('" hidden sm:table-cell"');
  });

  it("레포 전체가 이 게이트를 이미 통과한 상태다", async () => {
    // 규칙을 켜 두고 위반이 남아 있으면 다음 사람이 무관한 PR 에서 빨간불을 만난다.
    const results = await eslint.lintFiles(["src/**/*.tsx", "src/**/*.ts"]);
    const offenders = results
      .flatMap((f) => f.messages.filter((m) => m.ruleId?.startsWith("better-tailwindcss/")).map((m) => `${f.filePath}:${m.line} ${m.ruleId}`));
    expect(offenders, `잔여 위반:\n${offenders.join("\n")}`).toHaveLength(0);
  });
});
