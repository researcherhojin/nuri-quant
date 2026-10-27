"""대화형 thesis 표시 전용. 모델 원문 없이 허용 목록 상태만 Discord 에 보낸다."""

from nuri.llm.thesis_events import STAGE_LABELS, public_event

BASE = 0x253649
BLUE = 0x5794CB
AMBER = 0xD6A64C
RED = 0xD16B6B
STATUS = {
    "started": "진행 중",
    "ok": "완료",
    "absent": "근거 없음",
    "failed": "실패",
}
RATING_LABELS = {
    "Buy": "긍정 · Buy",
    "Overweight": "다소 긍정 · Overweight",
    "Hold": "중립 또는 근거 부족 · Hold",
    "Underweight": "다소 부정 · Underweight",
    "Sell": "부정 · Sell",
    "REVIEW": "판정 보류 · REVIEW",
}


def progress_embed(ticker: str, states: dict[str, str], *, finished: bool = False) -> dict:
    terminal = sum(states.get(s) in {"ok", "absent", "failed"} for s in STAGE_LABELS)
    lines = []
    for n, (stage, label) in enumerate(STAGE_LABELS.items(), 1):
        status = states.get(stage, "")
        text = STATUS.get(status, "미확인" if finished else "대기")
        if finished and status == "started":
            text = "중단 · 완료 미확인"
        lines.append(f"`{n:02}` {label} — **{text}**")
    return {
        "title": f"Thesis · {ticker} | 분석 상태",
        "description": "\n".join(lines),
        "color": BASE if finished else BLUE,
        "footer": {"text": f"{terminal}/7 단계 종료 · 단계 완료는 근거의 정확성이나 수익성을 뜻하지 않습니다"},
    }


def result_embed(ticker: str, states: dict[str, str], rc: int, value: object) -> dict:
    event = public_event(value)
    valid = rc == 0 and event is not None and event["event"] == "result" and event["outcome"] != "failed"
    complete = all(states.get(s) == "ok" for s in STAGE_LABELS)
    safe = event if valid and event is not None else {}
    verdict = safe.get("outcome") == "verdict"
    fields = [
        {"name": "모델 판정", "value": RATING_LABELS[safe["rating"]] if valid else "판정 확인 불가", "inline": False},
        {
            "name": "이용 범위",
            "value": "탐색용 분석입니다. 보유 비중이나 매매 지시를 뜻하지 않습니다.",
            "inline": False,
        },
    ]
    if valid:
        short = safe["run_hash"][:16]
        fields.append(
            {
                "name": "근거·반대 논거 확인",
                "value": "분석을 실행한 로컬 단말의 저장소에서 다음 명령을 실행하세요.\n"
                f"```\nuv run python -m nuri.agents.discord.thesis_report --ticker {ticker} --run {short} --open\n```"
                "저장된 분석을 엽니다. 모델을 다시 호출하지 않습니다.",
                "inline": False,
            }
        )
        fields.append({"name": "실행 ID", "value": f"`{short}`", "inline": False})
    else:
        fields.append(
            {
                "name": "확인 방법",
                "value": "실행 단말의 로컬 실행 로그를 확인하세요. 오류 원문은 디스코드에 보내지 않습니다.",
                "inline": False,
            }
        )
    if not valid:
        summary = "분석을 완료하지 못했습니다."
    elif not verdict:
        summary = "실행은 끝났지만 유효한 판정을 확정하지 못했습니다."
    elif not complete:
        summary = "판정을 받았지만 일부 단계에 누락·미확인이 있습니다. 상태표와 근거를 확인하세요."
    else:
        summary = "분석을 마쳤습니다. 판단하기 전에 근거와 반대 논거를 확인하세요."
    return {
        "title": f"Thesis · {ticker} | {'분석 결과' if valid else '실행 실패'}",
        "description": summary,
        "color": BASE if verdict and complete else AMBER if valid else RED,
        "fields": fields,
        "footer": {"text": "로컬 분석 · 탐색용 · 자동 주문 없음"},
    }
