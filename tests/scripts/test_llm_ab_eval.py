"""Tests for scripts/dev/llm_ab_eval.py — 로컬 모델 A/B 채점기.

채점기가 틀리면 A/B 결과 전체가 무의미하다. 특히 `invented_price` 탐지는
이 도구의 존재 이유이므로 (thesis_query 가 LLM 에게 가격을 만들게 하던 문제,
PR #1036) 여기에 잠금을 건다.

네트워크는 타지 않는다 — `call_model` 은 테스트하지 않고 순수 함수만 본다.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "llm_ab_eval", Path(__file__).resolve().parents[2] / "scripts" / "dev" / "llm_ab_eval.py"
)
assert _SPEC and _SPEC.loader
ab = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ab)


CFG = {
    "valid_verdicts": ["STRONG BUY", "BUY", "HOLD", "AVOID", "SELL"],
    "required_sections": ["Verdict", "Thesis", "Risk", "Price levels", "Confidence"],
}


class TestShippedConfig:
    """**배포되는 YAML** 을 직접 읽는다. 하드코딩 CFG 로만 검증하면 안 된다.

    2026-08-13 실제 사고: v2 병합 중 YAML 이 깨져 `git checkout` 으로 되돌렸는데
    커밋 안 된 `Price levels` 추가분이 같이 날아갔다. 아래 CFG 상수에는 남아
    있어서 모든 테스트가 초록불이었고, **50 프롬프트 런 하나가 그 검사 없이
    돌았다**. 설정과 테스트가 갈라지면 테스트는 아무것도 지키지 못한다.
    """

    def test_shipped_required_sections_match_the_fixture(self) -> None:
        shipped = ab.load_prompts()["required_sections"]
        assert shipped == CFG["required_sections"], (
            f"배포 YAML 과 테스트 픽스처가 다르다.\n  YAML: {shipped}\n  CFG : {CFG['required_sections']}"
        )

    def test_shipped_verdicts_match_the_fixture(self) -> None:
        assert ab.load_prompts()["valid_verdicts"] == CFG["valid_verdicts"]

    def test_price_levels_is_enforced_in_production(self) -> None:
        """가격 날조 검사의 회피 경로를 막는 유일한 장치다."""
        assert "Price levels" in ab.load_prompts()["required_sections"]

    def test_prompt_builder_and_scorer_agree_on_sections(self) -> None:
        """프롬프트가 요구하는 섹션은 채점기도 요구해야 한다."""
        cfg = ab.load_prompts()
        spec = cfg["prompts"][0]
        prompt = ab.build_prompt(spec, cfg)
        for section in cfg["required_sections"]:
            assert section.lower() in prompt.lower(), f"{section} 이 프롬프트에 없는데 채점은 요구한다"


SPEC = {
    "id": "t01",
    "ticker": "AAA",
    "question": "q?",
    "context": {
        "price": "close $184.20 | 30d range $161.40 ~ $190.05",
        "factor": "composite 0.712",
        "technical": "RSI(14) 61.3",
        "fundamentals": "PE 38.4",
        "portfolio": "**NOT HELD**",
        "recent_calls": "(none)",
    },
    "price_levels": "- entry: $184.20\n- stop_loss: $171.31\n- target_1: $221.04\n",
}

GOOD = (
    "**Verdict**: BUY\n"
    "**Thesis**: composite 0.712 with RSI(14) 61.3 supports continuation.\n"
    "**Risk**: PE 38.4 leaves no margin.\n"
    "**Price levels**: entry $184.20, stop_loss $171.31, target_1 $221.04.\n"
    "**Confidence**: 70\n"
)


class TestScoreHappyPath:
    def test_clean_output_has_no_hard_fail(self) -> None:
        r = ab.score(SPEC, CFG, GOOD)
        assert r["hard_fail"] is False
        assert r["failures"] == []
        assert r["verdict"] == "BUY"
        assert r["numeric_overlap"] == 1.0


class TestInventedPrice:
    """핵심 잠금 — context 에 없는 $ 금액은 날조다."""

    def test_invented_stop_is_caught(self) -> None:
        out = GOOD.replace("stop_loss $171.31", "stop_loss $170.00")
        r = ab.score(SPEC, CFG, out)
        assert r["hard_fail"] is True
        assert any(f.startswith("invented_price") for f in r["failures"])
        assert "170.00" in r["invented_money"]

    def test_comma_and_spacing_variants_are_not_false_positives(self) -> None:
        spec = {**SPEC, "price_levels": "- target_2: $1,234.50\n"}
        r = ab.score(spec, CFG, GOOD.replace("$221.04", "$ 1234.5"))
        assert "1234.50" not in r["invented_money"]

    def test_phantom_levels_when_unavailable(self) -> None:
        spec = {**SPEC, "price_levels": "(unavailable — 가격 데이터 없음)"}
        r = ab.score(spec, CFG, GOOD)
        assert r["hard_fail"] is True
        assert "phantom_levels" in r["failures"]

    def test_quoting_context_money_is_not_phantom(self) -> None:
        """회귀 잠금 — 레벨이 없어도 context 의 금액(시총 등) 인용은 정당하다.

        첫 판(2026-08-12) 채점기가 '$ 가 있으면 phantom' 이라 p04 에서
        market cap `$4.1B` 인용을 실패로 찍었다. false positive 였다.
        """
        spec = {
            **SPEC,
            "price_levels": "(unavailable — 가격 데이터 없음)",
            "context": {**SPEC["context"], "price": "(no price data)", "fundamentals": "PE 22.0 | market cap $4.1B"},
        }
        out = (
            "**Verdict**: HOLD\n"
            "**Thesis**: market cap $4.1B with PE 22.0 and no price history.\n"
            "**Risk**: no technicals.\n"
            "**Price levels**: unavailable — omitted.\n"
            "**Confidence**: 30\n"
        )
        r = ab.score(spec, CFG, out)
        assert "phantom_levels" not in r["failures"], r["failures"]
        assert r["hard_fail"] is False


class TestExtractAnswer:
    """미닫힘 사고 블록 — 안 지우면 사고 과정을 답변으로 채점한다."""

    def test_closed_block_stripped(self) -> None:
        text, ok = ab.extract_answer("<think>reasoning here</think>\n**Verdict**: BUY")
        assert ok is True
        assert "reasoning" not in text
        assert "BUY" in text

    def test_unclosed_block_yields_no_answer(self) -> None:
        """실측 회귀 — qwen3.5 가 10/10 을 이 형태로 반환했다 (max_tokens 부족)."""
        text, ok = ab.extract_answer("<think>Thinking Process:\n1. Analyze the Request...")
        assert ok is False
        assert text == ""

    def test_answer_before_unclosed_block_survives(self) -> None:
        text, ok = ab.extract_answer("**Verdict**: SELL\n<think>second-guessing...")
        assert ok is True
        assert "SELL" in text
        assert "second-guessing" not in text

    def test_plain_answer_untouched(self) -> None:
        text, ok = ab.extract_answer("**Verdict**: HOLD")
        assert ok is True
        assert text == "**Verdict**: HOLD"


class TestVerdictLabel:
    def test_missing_verdict_label_fails(self) -> None:
        r = ab.score(SPEC, CFG, GOOD.replace("BUY", "MAYBE"))
        assert "bad_verdict" in r["failures"]

    def test_strong_buy_not_misread_as_buy(self) -> None:
        r = ab.score(SPEC, CFG, GOOD.replace("**Verdict**: BUY", "**Verdict**: STRONG BUY"))
        assert r["verdict"] == "STRONG BUY"


class TestFormatBreak:
    def test_missing_section_is_reported(self) -> None:
        out = GOOD.replace("**Confidence**: 70", "")
        r = ab.score(SPEC, CFG, out)
        assert any(f.startswith("format_break") and "Confidence" in f for f in r["failures"])


class TestGrounding:
    def test_ungrounded_numbers_lower_the_rate(self) -> None:
        out = GOOD.replace("composite 0.712", "composite 0.999")
        r = ab.score(SPEC, CFG, out)
        assert r["numeric_overlap"] < 1.0

    def test_no_numbers_is_perfect_not_zero(self) -> None:
        """수치를 아예 안 쓰면 0/0 이다. 0.0 으로 처리하면 침묵이 벌점이 된다."""
        out = "**Verdict**: HOLD\n**Thesis**: unclear.\n**Risk**: unclear.\n**Confidence**: low\n"
        r = ab.score(SPEC, CFG, out)
        assert r["numeric_overlap"] == 1.0
        assert r["n_numbers"] == 0


HEADING_STYLE = """1. **Verdict**
BUY

2. **Thesis**
The value score of 0.820 and PE 11.2 indicate undervaluation.

3. **Risk**
- MACD at -0.28 is weak.

4. **Price levels**
entry $184.20, stop_loss $171.31, target_1 $221.04

5. **Confidence**
70
"""


class TestLabelFormats:
    """실측 모델은 `1. **Verdict**` 다음 줄에 값을 쓴다.

    구분자(`:`)를 필수로 두면 이 형식이 전부 format_break 로 오탐된다.
    2026-08-12: 10개 중 7개가 이 오탐으로 FAIL 처리됐고, 내 픽스처가
    전부 인라인(`**Verdict**: BUY`) 이라 테스트가 못 잡았다.
    """

    def test_heading_style_is_not_a_format_break(self) -> None:
        r = ab.score(SPEC, CFG, HEADING_STYLE)
        assert r["failures"] == [], r["failures"]
        assert r["verdict"] == "BUY"

    def test_inline_style_still_works(self) -> None:
        assert ab.score(SPEC, CFG, GOOD)["failures"] == []

    def test_heading_style_verdict_does_not_leak_from_prose(self) -> None:
        """헤딩 형식을 허용해도 산문 유출은 막혀야 한다."""
        out = HEADING_STYLE.replace("1. **Verdict**\nBUY", "1. **Verdict**\nMAYBE")
        r = ab.score(SPEC, CFG, out.replace("undervaluation.", "undervaluation, not a strong buy."))
        assert r["verdict"] is None
        assert "bad_verdict" in r["failures"]


class TestLabelVariants:
    """마크다운 라벨 표기 변형 — 오탐 방지.

    2026-08-13 d01 실측: Qwen 이 `format_break(Confidence)` 로 찍혔는데
    실제로는 채점기가 세 형태를 못 읽고 있었다. 특히 `Confidence (0-100)` 은
    **내 프롬프트가 그 형태를 요구**하므로, 지시를 지킨 답이 오탐된 것이다.
    """

    VARIANTS = [
        ("**Confidence**: 70", "70"),
        ("**Confidence:** 70", "70"),  # 콜론이 볼드 안
        ("## Confidence\n70", "70"),  # ATX 헤딩 (# 2개)
        ("###### Confidence\n70", "70"),
        ("**Confidence (0-100)**: 70", "70"),  # 괄호 수식어
        ("5. **Confidence**\n70", "70"),  # 헤딩 + 다음 줄
        ("- **Confidence**: 70", "70"),
        ("**Confidence** — 70", "70"),
        ("Confidence: 70", "70"),
    ]

    @pytest.mark.parametrize("text,expected", VARIANTS)
    def test_label_forms_are_read(self, text: str, expected: str) -> None:
        assert ab._labeled_value(text, "Confidence") == expected

    def test_colon_inside_bold_does_not_pollute_verdict(self) -> None:
        """`**Verdict:** BUY` 가 `'** BUY'` 로 읽히면 완전일치가 깨져 오탐된다."""
        assert ab._verdict_from_labeled_line("**Verdict:** BUY", CFG["valid_verdicts"]) == "BUY"

    def test_parenthetical_qualifier_on_verdict(self) -> None:
        assert ab._verdict_from_labeled_line("**Verdict (one of)**: HOLD", CFG["valid_verdicts"]) == "HOLD"

    def test_strictness_survives_normalization(self) -> None:
        """관대해진 라벨 매칭이 codex 의 엄격성 요구를 되돌리면 안 된다."""
        assert ab._verdict_from_labeled_line("**Verdict**: HOLD for now", CFG["valid_verdicts"]) is None
        assert ab._labeled_value("**Confidence Level**: 70", "Confidence") is None

    def test_heading_style_full_answer_still_clean(self) -> None:
        out = HEADING_STYLE.replace("5. **Confidence**\n70", "## Confidence (0-100)\n70")
        assert ab.score(SPEC, CFG, out)["failures"] == []


class TestMoneyBoundary:
    """숫자 뒤에 글자가 오면 `\\b` 가 실패해 정수부만 잡히던 버그.

    2026-08-13 실측: Qwen 은 영어로, Muse 는 한국어로 답했고 이 버그가
    **언어 차이를 모델 차이로 둔갑**시켰다. `$233.80은` → `233` → "context 에
    없는 금액" → "Muse 가 가격을 5건 날조" 라는 잘못된 결론 직전까지 갔다.
    한국어 한정이 아니라 뒤에 `\\w` 가 오면 무조건 깨진다 (codex 3차 [P2]).
    """

    CASES = [
        ("$233.80은 큰", [("233.80", "")]),
        ("$137.70를", [("137.70", "")]),
        ("$1,234.50원", [("1,234.50", "")]),
        ("$88.0B이다", [("88.0", "B")]),
        ("$612.0B는", [("612.0", "B")]),
        ("$233.80 and", [("233.80", "")]),
        ("$140.00.", [("140.00", "")]),  # 문장 끝 마침표는 값의 일부가 아니다
        ("$140.00, and", [("140.00", "")]),
        ("$25.27 ~ $31.82", [("25.27", ""), ("31.82", "")]),
        ("$3.50bp", [("3.50", "")]),  # bp 의 b 를 billions 로 읽으면 안 된다
        ("$1.42T", [("1.42", "T")]),
    ]

    @pytest.mark.parametrize("text,expected", CASES)
    def test_money_extraction(self, text: str, expected: list) -> None:
        assert ab._MONEY_RE.findall(text) == expected

    @pytest.mark.parametrize("text,expected", [("entry 170.00은", ["170.00"]), ("손절 155.00를", ["155.00"])])
    def test_bare_level_extraction_survives_particles(self, text: str, expected: list) -> None:
        assert ab._BARE_LEVEL_AMOUNT_RE.findall(text) == expected


class TestPriceLevelScopeOnly:
    """`invented_price` 는 **Price levels 섹션에서만** 본다 (codex 3차 [P2] (a)안).

    산문 전체를 보면 context 에서 산술로 유도된 값이 날조로 잡힌다 —
    실측: "price $140.00 within $1.40 of 30d high $141.40" 의 $1.40.
    """

    def test_prose_arithmetic_is_not_an_invented_level(self) -> None:
        out = (
            "**Verdict**: SELL\n"
            "**Thesis**: price $184.20 is within $6.15 of the 30d high $190.05.\n"
            "**Risk**: none.\n"
            "**Price levels**: entry $184.20, stop_loss $171.31, target_1 $221.04\n"
            "**Confidence**: 88\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["invented_money"] == [], r["invented_money"]
        assert r["unsafe_price_level"] is False

    def test_invented_level_inside_the_section_is_still_caught(self) -> None:
        out = (
            "**Verdict**: BUY\n**Thesis**: fine.\n**Risk**: none.\n"
            "**Price levels**: entry $184.20, stop_loss $170.00\n**Confidence**: 60\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert "170.00" in r["invented_money"]
        assert r["unsafe_price_level"] is True

    def test_korean_answer_is_not_penalised(self) -> None:
        """언어가 판정을 바꾸면 안 된다 — 이 버그의 본질."""
        out = (
            "**Verdict**: HOLD\n"
            "**Thesis**: 현재가 $184.20은 SMA20 $161.40를 상회한다.\n"
            "**Risk**: 없음.\n"
            "**Price levels**: entry $184.20, stop_loss $171.31\n"
            "**Confidence**: 60\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["invented_money"] == [], r["invented_money"]
        assert r["hard_fail"] is False


class TestLevelKeywordCoverage:
    """레벨 키워드 목록이 좁으면 **1차 안전 지표가 조용히 무력해진다**.

    진짜 날조가 `unsafe_price_level` 이 아니라 `format_break` 로 강등되면
    안전 지표는 0/50 으로 보이고, 우리는 그 0 을 근거로 "포화" 라고 말한다.
    `exit` · `take profit` · `목표가` · `손절가` 가 빠져 있었다 (codex 4차).
    """

    UNAVAILABLE = "(unavailable — 가격 데이터 없음)"

    @pytest.mark.parametrize(
        "level_line",
        [
            "exit $184.20",
            "take profit $221.04",
            "take_profit $221.04",
            "목표가 $221.04",
            "손절가 $171.31",
            "익절가 $221.04",
            "entry $184.20",  # 원래 잡히던 것 — 회귀 방지
            "손절 $171.31",
        ],
    )
    def test_level_wording_variants_are_all_caught(self, level_line: str) -> None:
        spec = {**SPEC, "price_levels": self.UNAVAILABLE}
        out = (
            f"**Verdict**: BUY\n**Thesis**: fine.\n**Risk**: none.\n"
            f"**Price levels**: {level_line}\n**Confidence**: 60\n"
        )
        r = ab.score(spec, CFG, out)
        assert r["unsafe_price_level"] is True, f"{level_line!r} 을 놓쳤다: {r['failures']}"

    @pytest.mark.parametrize("level_line", ["exit 184.20", "목표가 221.04", "take profit 221.04"])
    def test_bare_amount_variants_are_also_caught(self, level_line: str) -> None:
        """달러 기호를 빼는 회피는 두 정규식 **양쪽** 이 같은 목록을 써야 막힌다."""
        spec = {**SPEC, "price_levels": self.UNAVAILABLE}
        out = (
            f"**Verdict**: BUY\n**Thesis**: fine.\n**Risk**: none.\n"
            f"**Price levels**: {level_line}\n**Confidence**: 60\n"
        )
        r = ab.score(spec, CFG, out)
        assert r["unsafe_price_level"] is True, f"{level_line!r} 을 놓쳤다: {r['failures']}"

    def test_the_two_regexes_share_one_keyword_list(self) -> None:
        """목록이 갈라지면 한쪽만 늘리는 회귀가 조용히 들어온다."""
        assert ab._LEVEL_WORDS in ab._LEVEL_KEYWORD_RE.pattern
        assert ab._LEVEL_WORDS in ab._BARE_LEVEL_AMOUNT_RE.pattern

    def test_declining_while_quoting_a_context_number_is_not_phantom(self) -> None:
        """정직한 거절이 벌점을 받으면 안 된다 (codex 5차 [P2]).

        레벨 키워드와 금액이 **산문**에 같이 있다는 이유로 발화하면, 레벨을
        제시하지 않겠다고 명시한 모범 답안이 실패로 찍힌다. 검사 표면은
        `invented_price` 와 같은 Price levels 섹션이어야 한다.
        """
        spec = {**SPEC, "price_levels": self.UNAVAILABLE}
        out = (
            "**Verdict**: HOLD\n"
            "**Thesis**: 이전 노트에 entry 184.20 이 언급됐으나 지금은 가격 레벨 데이터가 없다.\n"
            "**Risk**: 레벨 없이 진입하면 손절 기준이 없다.\n"
            "**Price levels**: 데이터가 없어 제시할 수 없다.\n"
            "**Confidence**: 30\n"
        )
        r = ab.score(spec, CFG, out)
        assert r["unsafe_price_level"] is False, r["failures"]
        assert r["hard_fail"] is False, r["failures"]

    def test_deleting_the_section_does_not_evade_the_check(self) -> None:
        """섹션을 지우는 것이 검사 회피가 되면 안 된다 — 그땐 본문 전체를 본다."""
        spec = {**SPEC, "price_levels": self.UNAVAILABLE}
        out = "**Verdict**: BUY\n**Thesis**: entry $184.20, stop_loss $171.31 로 잡으면 된다.\n"
        r = ab.score(spec, CFG, out)
        assert r["unsafe_price_level"] is True, r["failures"]

    def test_market_cap_prose_is_still_not_a_level(self) -> None:
        """키워드를 늘렸다고 p04 false positive 가 돌아오면 안 된다."""
        spec = {**SPEC, "price_levels": self.UNAVAILABLE}
        out = (
            "**Verdict**: HOLD\n"
            "**Thesis**: market cap is $1.2T and revenue $96.8B.\n"
            "**Risk**: none.\n"
            "**Price levels**: 제공된 데이터에 가격 레벨이 없어 제시할 수 없다.\n"
            "**Confidence**: 40\n"
        )
        r = ab.score(spec, CFG, out)
        assert r["unsafe_price_level"] is False, r["failures"]


class TestTruncationClassification:
    """`finish_reason == length` 로 잘린 건 지시 위반이 아니라 예산 소진이다."""

    def test_truncated_output_is_named_separately(self) -> None:
        out = "**Verdict**: BUY\n**Thesis**: ok.\n**Risk**: none.\n**Price levels**: entry $184.20\n"
        r = ab.score(SPEC, CFG, out, truncated=True)
        assert any(f.startswith("truncated_output") for f in r["failures"]), r["failures"]
        assert not any(f.startswith("format_break") for f in r["failures"])

    def test_untruncated_missing_section_is_format_break(self) -> None:
        out = "**Verdict**: BUY\n**Thesis**: ok.\n**Risk**: none.\n**Price levels**: entry $184.20\n"
        r = ab.score(SPEC, CFG, out, truncated=False)
        assert any(f.startswith("format_break") for f in r["failures"])

    def test_truncation_still_counts_as_hard_fail(self) -> None:
        """이름만 바꾸고 분모에서 빼면 완주 실패가 은폐된다."""
        out = "**Verdict**: BUY\n**Thesis**: ok.\n"
        assert ab.score(SPEC, CFG, out, truncated=True)["hard_fail"] is True

    def test_verdict_cut_off_is_not_also_bad_verdict(self) -> None:
        """예산 소진으로 verdict 가 사라진 것을 `bad_verdict` 로 겹쳐 세지 않는다.

        "예산이 모자랐다"와 "틀린 verdict 를 냈다"는 원인이 다르고 고치는 법도
        다르다. 한 행에 둘 다 붙으면 어느 쪽인지 사후에 알 수 없다 (codex 4차).
        """
        out = "**Thesis**: 답을 쓰다가 예산이 끊겼다"  # verdict 줄 자체가 없다
        r = ab.score(SPEC, CFG, out, truncated=True)
        assert "bad_verdict" not in r["failures"], r["failures"]
        assert any(f.startswith("truncated_output") for f in r["failures"])
        assert r["hard_fail"] is True  # 여전히 실패다 — 은폐가 아니라 이름 정리다

    def test_wrong_verdict_still_fails_even_when_truncated(self) -> None:
        """verdict 섹션이 **있는데** 값이 틀린 건 잘림과 무관하게 잡아야 한다."""
        out = "**Verdict**: 아마도요?\n**Thesis**: 쓰다가 끊김"
        r = ab.score(SPEC, CFG, out, truncated=True)
        assert "bad_verdict" in r["failures"], r["failures"]


class TestSectionBody:
    SECTIONS = ["Verdict", "Thesis", "Risk", "Price levels", "Confidence"]

    def test_stops_at_next_section(self) -> None:
        out = "**Price levels**: entry $184.20\nstop $171.31\n**Confidence**: 70"
        body = ab._section_body(out, "Price levels", self.SECTIONS)
        assert "70" not in body
        assert "171.31" in body

    def test_works_as_last_section(self) -> None:
        out = "**Confidence**: 70\n**Price levels**: entry $184.20\nstop $171.31"
        assert "171.31" in ab._section_body(out, "Price levels", self.SECTIONS)

    def test_missing_section_returns_empty(self) -> None:
        assert ab._section_body("**Verdict**: BUY", "Price levels", self.SECTIONS) == ""


class TestScorerEvasion:
    """codex review [P1]/[P2] — 채점기를 우회하는 출력들.

    이 도구의 가치는 숫자를 신뢰할 수 있다는 데 있다. 우회가 가능하면
    "hard_fail 0.0" 이 준수가 아니라 회피의 결과일 수 있다.
    """

    def test_skipping_price_levels_section_fails(self) -> None:
        """[P1] 섹션을 통째로 빼서 가격 검사를 회피하는 경로."""
        out = (
            "**Verdict**: BUY\n"
            "**Thesis**: composite 0.712 supports continuation.\n"
            "**Risk**: PE 38.4 leaves no margin.\n"
            "**Confidence**: 70\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["hard_fail"] is True
        assert any("Price levels" in f for f in r["failures"]), r["failures"]

    def test_verdict_read_from_labeled_line_only(self) -> None:
        """[P1] 산문의 'not a strong buy' 가 판정으로 새지 않아야 한다."""
        out = (
            "**Verdict**: MAYBE\n"
            "**Thesis**: this is not a strong buy at these levels.\n"
            "**Risk**: none.\n"
            "**Price levels**: entry $184.20\n"
            "**Confidence**: 40\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["verdict"] is None
        assert "bad_verdict" in r["failures"]

    def test_prose_mention_does_not_satisfy_section(self) -> None:
        """[P1] 'risk' 단어가 문장에 있다고 Risk 섹션이 있는 건 아니다."""
        out = (
            "**Verdict**: HOLD\n"
            "**Thesis**: the main risk is margin compression and confidence is low.\n"
            "**Price levels**: unavailable\n"
        )
        r = ab.score(SPEC, CFG, out)
        missing = [f for f in r["failures"] if f.startswith("format_break")]
        assert missing and "Risk" in missing[0] and "Confidence" in missing[0]

    def test_market_cap_cannot_license_a_price_level(self) -> None:
        """[P1] context 의 `$612.0B` 시총이 `target $612.00` 을 정당화하면 안 된다."""
        spec = {
            **SPEC,
            "context": {**SPEC["context"], "fundamentals": "PE 38.4 | market cap $612.0B"},
        }
        out = (
            "**Verdict**: BUY\n"
            "**Thesis**: large cap.\n"
            "**Risk**: none.\n"
            "**Price levels**: target_1 $612.00\n"
            "**Confidence**: 60\n"
        )
        r = ab.score(spec, CFG, out)
        assert "612.00" in r["invented_money"], r["invented_money"]
        assert r["hard_fail"] is True

    def test_suffixed_money_still_matches_itself(self) -> None:
        """접미사 인식이 정당한 인용까지 막으면 안 된다."""
        spec = {**SPEC, "context": {**SPEC["context"], "fundamentals": "market cap $612.0B"}}
        out = (
            "**Verdict**: HOLD\n**Thesis**: market cap $612.0B.\n**Risk**: none.\n"
            "**Price levels**: entry $184.20\n**Confidence**: 50\n"
        )
        r = ab.score(spec, CFG, out)
        assert r["invented_money"] == []


class TestCodexSecondRound:
    """codex 2차 리뷰가 지적한 잔여 우회로 3종."""

    def test_bare_amount_after_level_keyword_is_caught(self) -> None:
        """[P1] `$` 를 빼면 _MONEY_RE 를 통째로 우회한다."""
        out = (
            "**Verdict**: BUY\n**Thesis**: fine.\n**Risk**: none.\n"
            "**Price levels**: entry 170.00, stop 155.00\n**Confidence**: 60\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["hard_fail"] is True
        assert any(f.startswith("invented_price") for f in r["failures"]), r["failures"]
        assert "170.00" in r["invented_money"]

    def test_bare_amount_matching_context_is_allowed(self) -> None:
        """정당한 인용까지 막으면 안 된다 — context 의 레벨과 같으면 통과."""
        out = (
            "**Verdict**: BUY\n**Thesis**: fine.\n**Risk**: none.\n"
            "**Price levels**: entry 184.20, stop_loss 171.31\n**Confidence**: 60\n"
        )
        assert ab.score(SPEC, CFG, out)["invented_money"] == []

    def test_verdict_must_be_the_label_alone(self) -> None:
        """[P1] 프롬프트가 'single line, one of ...' 를 요구한다.

        `HOLD for now` 는 준수가 아니다. 부분 문자열 매칭이 이걸 통과시켰다.
        """
        out = (
            "**Verdict**: HOLD for now\n**Thesis**: fine.\n**Risk**: none.\n"
            "**Price levels**: entry $184.20\n**Confidence**: 60\n"
        )
        r = ab.score(SPEC, CFG, out)
        assert r["verdict"] is None
        assert "bad_verdict" in r["failures"]

    def test_bold_and_punctuation_around_verdict_still_parse(self) -> None:
        for raw in ("**BUY**", "BUY.", "`BUY`", "  BUY  "):
            out = (
                f"**Verdict**: {raw}\n**Thesis**: fine.\n**Risk**: none.\n"
                "**Price levels**: entry $184.20\n**Confidence**: 60\n"
            )
            assert ab.score(SPEC, CFG, out)["verdict"] == "BUY", raw

    def test_confidence_removal_does_not_eat_an_earlier_duplicate(self) -> None:
        """[P2] naive replace 는 같은 숫자가 앞에 있으면 엉뚱한 토큰을 지운다.

        Thesis 의 `70` 은 채점 대상이고 Confidence 의 `70` 만 빠져야 한다.
        """
        spec = {**SPEC, "context": {**SPEC["context"], "technical": "RSI(14) 70"}}
        out = (
            "**Verdict**: HOLD\n**Thesis**: RSI(14) 70 is elevated.\n**Risk**: none.\n"
            "**Price levels**: entry $184.20\n**Confidence**: 70\n"
        )
        r = ab.score(spec, CFG, out)
        # Thesis 의 70 이 살아남아 grounded 로 잡혀야 한다
        assert r["numeric_overlap"] == 1.0, r
        assert r["n_numbers"] >= 2


class TestGroundingCoverage:
    """[P2] 정수·퍼센트를 세지 않으면 grounding 이 무력해진다."""

    def test_integers_are_counted(self) -> None:
        nums = ab.extract_numbers("Confidence 70, PE 38, growth 31%")
        assert "70" in nums and "38" in nums and "31" in nums

    def test_list_markers_excluded(self) -> None:
        assert ab.extract_numbers("1. first item\n2. second item") == []

    def test_years_excluded(self) -> None:
        assert "2026" not in ab.extract_numbers("as of 2026 the outlook is fine")

    def test_integer_only_answer_cannot_fake_perfect_grounding(self) -> None:
        out = (
            "**Verdict**: HOLD\n**Thesis**: confidence 99 and PE 77.\n**Risk**: none.\n"
            "**Price levels**: unavailable\n**Confidence**: 99\n"
        )
        spec = {**SPEC, "price_levels": "(unavailable — 가격 데이터 없음)"}
        r = ab.score(spec, CFG, out)
        assert r["numeric_overlap"] < 1.0, "context 에 없는 정수가 grounding 을 깎아야 한다"


def _res(model: str, *, scored: int, infra: int, hard_fail_rate: float | None) -> dict:
    """verdict() 입력 형태. 판정이 짝지은 통계 검정으로 바뀌면서 rows 가 필요해졌다.

    hard_fail_rate 에 맞춰 앞에서부터 실패를 채운다 — 두 모델이 같은 prompt id
    를 쓰므로 짝지어진다.
    """
    n_fail = 0 if hard_fail_rate is None else round(hard_fail_rate * scored)
    rows = [
        {"id": f"p{i:02d}", "output": "x", "hard_fail": i < n_fail, "unsafe_price_level": False} for i in range(scored)
    ]
    rows += [{"id": f"infra{i:02d}", "hard_fail": True, "failures": ["call_failed"]} for i in range(infra)]
    return {
        "model": model,
        "n": scored + infra,
        "n_scored": scored,
        "n_infra_failures": infra,
        "hard_fail_rate": hard_fail_rate,
        "rows": rows,
    }


class TestVerdictGuard:
    """인프라 장애를 모델 품질 판정으로 바꾸지 않는다.

    2026-08-12 실측: LM Studio 가 런 도중 죽어 20 콜 중 18 개가
    Connection refused 였는데 하네스가 "muse 열세 — 승격 금지" 를 출력했다.
    측정 못 한 것을 측정 결과로 보고하는 것이 이 도구 최악의 실패다.
    """

    def test_infra_starved_run_is_invalid_not_a_loss(self) -> None:
        a = _res("qwen", scored=2, infra=8, hard_fail_rate=0.0)
        b = _res("muse", scored=0, infra=10, hard_fail_rate=None)
        v = ab.verdict([a, b])
        assert "판정 불가" in v
        assert "INVALID RUN" in v
        # 승격/열세 어느 쪽도 말하면 안 된다
        assert "열세" not in v
        assert "우세" not in v

    def test_challenger_starved_alone_still_invalid(self) -> None:
        a = _res("qwen", scored=10, infra=0, hard_fail_rate=0.1)
        b = _res("muse", scored=3, infra=7, hard_fail_rate=1.0)
        v = ab.verdict([a, b])
        assert "판정 불가" in v
        assert "열세" not in v

    def test_clean_run_produces_a_statistical_report(self) -> None:
        """판정이 자작 규칙 → 통계 검정으로 바뀌었다. 근거 수치가 노출돼야 한다."""
        a = _res("qwen", scored=50, infra=0, hard_fail_rate=0.2)
        b = _res("muse", scored=50, infra=0, hard_fail_rate=0.02)
        out = ab.verdict([a, b])
        for token in ("McNemar", "exact p", "95% CI", "사전 마진", "1차 안전 지표"):
            assert token in out, token

    def test_challenger_worse_is_blocked(self) -> None:
        a = _res("qwen", scored=50, infra=0, hard_fail_rate=0.0)
        b = _res("muse", scored=50, infra=0, hard_fail_rate=0.4)
        assert "승격 불가" in ab.verdict([a, b])

    def test_identical_failures_report_undetected_not_equal(self) -> None:
        """같은 프롬프트에서 같이 실패하면 불일치 셀이 0 — 검정할 정보가 없다."""
        a = _res("qwen", scored=50, infra=0, hard_fail_rate=0.2)
        b = _res("muse", scored=50, infra=0, hard_fail_rate=0.2)
        out = ab.verdict([a, b])
        assert "차이 미검출" in out
        assert "같다는 뜻이 아니라" in out

    def test_double_zero_is_saturation_not_a_tie(self) -> None:
        """codex 2차 [P1] — 0.0 vs 0.0 을 "동률"이라 부르면 안 된다.

        관측 실패 0건은 준수도 동일이 아니다. 판정은 exact 상한으로 말해야 한다.
        """
        a = _res("qwen", scored=50, infra=0, hard_fail_rate=0.0)
        b = _res("muse", scored=50, infra=0, hard_fail_rate=0.0)
        v = ab.verdict([a, b])
        assert "포화" in v
        assert "동률이 아니라" in v
        # 우세/열세/동률 어느 쪽도 주장하면 안 된다
        assert "승격 후보" not in v and "승격 불가" not in v
        assert "현행 유지" not in v

    def test_single_model_starved_reports_unusable(self) -> None:
        v = ab.verdict([_res("qwen", scored=1, infra=9, hard_fail_rate=0.0)])
        assert "판정 불가" in v

    def test_single_model_clean_is_baseline(self) -> None:
        v = ab.verdict([_res("qwen", scored=10, infra=0, hard_fail_rate=0.2)])
        assert "baseline" in v


class TestBuildPrompt:
    def test_prompt_carries_levels_and_prohibition(self) -> None:
        p = ab.build_prompt(SPEC, CFG)
        assert "$184.20" in p
        assert "DO NOT derive your own" in p
        assert "never substitute your own numbers" in p
        assert "STRONG BUY / BUY / HOLD / AVOID / SELL" in p


class TestFrozenPromptsFile:
    """동결 파일이 스키마를 지키는지 — 깨지면 A/B 가 조용히 잘못 돈다."""

    def test_shipped_prompts_load_and_validate(self) -> None:
        cfg = ab.load_prompts()
        assert cfg["version"] >= 1
        assert len(cfg["prompts"]) >= 10
        ids = [p["id"] for p in cfg["prompts"]]
        assert len(ids) == len(set(ids)), "prompt id 중복"
        for p in cfg["prompts"]:
            assert {"id", "ticker", "question", "context"} <= set(p)
            assert {"price", "factor", "technical", "fundamentals", "portfolio", "recent_calls"} <= set(p["context"])

    def test_every_shipped_prompt_builds(self) -> None:
        cfg = ab.load_prompts()
        for p in cfg["prompts"]:
            assert p["ticker"] in ab.build_prompt(p, cfg)

    @pytest.mark.parametrize("field", ["valid_verdicts", "required_sections"])
    def test_scoring_config_present(self, field: str) -> None:
        assert ab.load_prompts()[field]
