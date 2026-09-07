import { RATE } from "@/lib/strings";

/**
 * Rate — 분모 없이는 생성할 수 없는 비율 지표 (#1429).
 *
 * `Metric` 과 갈라지는 지점은 하나다: `Metric` 은 이미 완성된 문자열을 받지만
 * `Rate` 는 **분자·분모·모집단을 각각** 받는다. 그래서 분모를 화면에서 뺄 방법이
 * 타입 레벨에 없다 — 이 컴포넌트가 존재하는 이유 전부가 그것이다.
 *
 * 이전 구현(`Metric label="Hit Rate" value="69%"` + `>= 50 ? green : red`)은
 * 645건 중 62건으로 계산된 비율을 분모 없이 초록으로 보였다. 옆 카드의
 * `PENDING 568` 은 같은 시각 비중이라 서로를 상쇄하지 못했다.
 *
 * ⚠️ **신뢰구간을 붙이지 않는다.** 43/62 의 Wilson 95% 는 [57.0%, 79.4%] 로 50% 가
 * 구간 밖이라, "동전던지기와 구분 안 됨" 옆에 "유의하게 이긴다" 를 나란히 찍게 된다.
 * 게다가 미판정분은 무작위 검열이 아니다(손절·목표가는 해소되고 애매한 건이 남는다) —
 * i.i.d. 베르누이 구간 자체가 무효다.
 *
 * ⚠️ **표본 충분성 임계값을 발명하지 않는다.** 이 컴포넌트가 판정하는 것은 사실
 * 하나뿐이다: 모집단이 분모보다 크면 표본이 아직 안 닫혔다. §3.11 사전등록 기준
 * (`config/rules.yaml measurement_mode`)은 잠겨 있고 이 카드는 그 판정이 아니다.
 */
interface RateProps {
  label: string;
  /** 비율의 분자 (예: 성공 판정 건수) */
  numerator: number;
  /** 비율의 분모 — 실제로 판정이 끝난 건수만 */
  denominator: number;
  /** 모집단 전체. 커버리지 바는 이 값으로 분모를 잡는다 */
  universe: number;
  /** 분모에서 빠진 것을 이름으로 밝힌다 — 조용한 탈락 금지 */
  excluded?: { label: string; value: number }[];
}

export function Rate({ label, numerator, denominator, universe, excluded = [] }: RateProps) {
  const pct = denominator > 0 ? Math.round((numerator / denominator) * 100) : null;
  const coverage = universe > 0 ? (denominator / universe) * 100 : 0;
  // 임계값이 아니라 사실이다 — 판정이 안 끝난 건이 하나라도 있으면 표본은 열려 있다.
  const open = universe > denominator;

  return (
    // 폭을 묶는다 — 바가 카드 전체로 늘어나면 커버리지 캡션이 비율 값에서 수백 px
    // 떨어져 같은 시각 평면을 잃는다 (분모는 비율 옆에 있어야 분모다).
    <div data-testid="rate" className="max-w-xl">
      <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</p>

      {/* 커버리지 바 — 모집단(universe)으로 분모를 잡아 미판정분이 빈 채로 보이게 한다 */}
      <div className="mt-1.5 flex items-center gap-2">
        <div className="h-1 w-32 shrink-0 bg-muted overflow-hidden" role="presentation">
          <div className="h-full bg-muted-foreground" style={{ width: `${coverage}%` }} />
        </div>
        <span className="text-[10px] font-mono text-muted-foreground whitespace-nowrap">
          {denominator} / {universe} {RATE.ADJUDICATED} ({coverage.toFixed(1)}%)
        </span>
      </div>

      {/* 비율은 본문 크기·무채색 — display 크기를 거부한다 */}
      <p className="mt-1.5 flex items-baseline gap-2 flex-wrap">
        <span className="text-sm font-mono font-semibold text-foreground">
          {pct !== null ? `${pct}%` : "—"}
        </span>
        <span className="text-[10px] font-mono text-muted-foreground">
          {numerator}/{denominator}
          {excluded
            .filter((e) => e.value > 0)
            .map((e) => ` · ${e.label} ${e.value}`)
            .join("")}
        </span>
      </p>

      {open && <p className="mt-0.5 text-[10px] text-muted-foreground/70">{RATE.OPEN_SAMPLE}</p>}
    </div>
  );
}
