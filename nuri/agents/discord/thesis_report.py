"""저장된 실행을 로컬 HTML 로 읽는다. 모델 호출·원장 쓰기·외부 리소스 없음."""

from __future__ import annotations

import argparse
import html
import json
import re
import webbrowser
from pathlib import Path

from nuri.agents.discord.thesis_view import RATING_LABELS, STATUS
from nuri.llm.local_client import load_config
from nuri.llm.thesis_events import STAGE_LABELS

CSS = """
:root{color-scheme:dark;--bg:#101820;--panel:#17232e;--line:#334552;--muted:#b0bfcb;--text:#e8edf1;--accent:#82b7e5}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.65 system-ui,sans-serif}
main{max-width:1160px;margin:auto;padding:36px 24px}header{border-bottom:1px solid var(--line);padding-bottom:24px}
h1{font-size:30px;margin:10px 0}h2{font-size:19px;margin:0 0 16px}h3{font-size:16px;color:var(--accent)}
p{margin:8px 0}.muted,small{color:var(--muted)}.grid{display:grid;grid-template-columns:2fr 1fr;gap:20px;margin-top:24px}
section{background:var(--panel);border:1px solid var(--line);padding:24px;min-width:0;margin-bottom:20px}
ul{padding-left:20px}li{margin:8px 0}.facts{display:grid;grid-template-columns:1fr 1fr;gap:16px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:14px/1.7 ui-monospace,monospace}code{overflow-wrap:anywhere}
details{border-top:1px solid var(--line);padding:16px 0}summary{cursor:pointer;color:var(--accent)}
summary:focus-visible{outline:2px solid var(--accent);outline-offset:5px}.wrap{overflow-wrap:anywhere}
@media(max-width:760px){main{padding:20px 14px}.grid,.facts{grid-template-columns:1fr}section{padding:18px}h1{font-size:25px}}
"""


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def render(saved: dict) -> str:
    run, packets = saved["run"], saved.get("packets", {})
    rendered = str(run.get("rendered", ""))
    # 이미 검증·숫자 마스킹된 표시 원문만 재배치한다. raw verdict 로 다시 판정을 만들지 않는다.
    lines = rendered.splitlines()
    bull = [line[9:] for line in lines if line.startswith("- [bull] ")]
    bear = [line[9:] for line in lines if line.startswith("- [bear] ")]
    rationale = next(
        (line.removeprefix("**Rationale**: ") for line in lines if line.startswith("**Rationale**: ")),
        "판정 근거가 저장되지 않았습니다.",
    )

    def items(values: list[str]) -> str:
        return (
            "<ul>" + "".join(f"<li>{esc(v)}</li>" for v in values) + "</ul>"
            if values
            else "<p class='muted'>저장된 근거 없음</p>"
        )

    stages = run.get("stages", {})
    stage_rows = []
    gaps = []
    for name, label in STAGE_LABELS.items():
        outcome = stages.get(name, {}).get("outcome")
        status = STATUS.get(outcome, "미확인")
        stage_rows.append(f"<li>{esc(label)} <span class='muted'>· {esc(status)}</span></li>")
        if outcome != "ok":
            gaps.append(f"{label}: {status}")
    sources = []
    for key, packet in packets.items():
        if not isinstance(packet, dict):
            continue
        sources.append(f"<h3>{esc(key)} · 입력 기준 {esc(packet.get('cutoff', '미기록'))}</h3>")
        for name, status in packet.get("sources", {}).items():
            sources.append(
                f"<p>{esc(name)} · {esc(status.get('status', '미기록'))} · {esc(status.get('as_of', '기준 시점 미기록'))}</p>"
            )
        sources.append(
            "<details><summary>항목별 관측 시점</summary><ul>"
            + "".join(
                f"<li>{esc(i.get('id', ''))} · {esc(i.get('source', ''))} · {esc(i.get('observed', '미기록'))} · {esc(i.get('age_days', '?'))}일 경과</li>"
                for i in packet.get("items", [])
            )
            + "</ul></details>"
        )
    handoff = run.get("handoff", {})
    reports = "".join(
        f"<details><summary>{label}</summary><pre>{esc(handoff.get(key) or '저장된 내용 없음')}</pre></details>"
        for key, label in (("reports", "단계별 분석 보고서"), ("debate", "강세·약세 논거 검토"))
    )
    state = "판정 수신" if run.get("outcome") == "verdict" else "검토 필요 · 유효한 판정 미확정"
    rating = RATING_LABELS.get(run.get("rating"), "알 수 없음")
    mode = "채점 실행 기록" if run.get("scored") else "대화형 · 탐색용"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
<title>Thesis · {esc(run["ticker"])}</title><style>{CSS}</style></head><body><main>
<header><small>Nuri · 로컬 분석 기록</small><h1>{esc(run["ticker"])} · 분석 검토</h1>
<p>{esc(mode)} · {esc(state)}</p><p class="muted">저장된 분석입니다. 실시간 가격이 아니며, 모델 판정의 정확성이나 수익성이 검증됐다는 뜻은 아닙니다.</p>
<p class="muted wrap">실행 ID <code>{esc(run["run_hash"])}</code></p></header>
<div class="grid"><div><section><h2>판정과 근거</h2><h3>{esc(rating)}</h3><p>{esc(rationale)}</p>
<div class="facts"><div><h3>강세 근거</h3>{items(bull)}</div><div><h3>약세·반대 근거</h3>{items(bear)}</div></div></section>
<section><h2>단계별 상세 분석</h2>{reports}<details><summary>검증된 판정 원문</summary><pre>{esc(rendered or "유효한 판정 원문 없음")}</pre></details></section>
<section><h2>데이터 기준과 관측 시점</h2>{"".join(sources) or "<p>기준 시점 미기록</p>"}</section></div>
<aside><section><h2>검토할 사항</h2>{items(gaps) if gaps else "<p>7개 단계가 완료로 기록됐습니다. 근거의 품질은 별도로 확인하세요.</p>"}
<p class="muted">등급은 모델이 생성한 분석 결과입니다. 포트폴리오 비중·주문 수량·자동 매매 지시가 아닙니다.</p></section>
<section><h2>실행 상태</h2><ul>{"".join(stage_rows)}</ul></section>
<section><h2>열람 범위</h2><p>이 파일에는 비공개 분석이 포함될 수 있습니다. 로컬에서 열람하고 공개 채널에 업로드하지 마세요.</p></section></aside></div>
</main></body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="저장된 thesis 분석을 로컬 화면으로 열람 (재분석 없음)")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--run", required=True, dest="run_hash")
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[A-Z]{1,6}", args.ticker) or not re.fullmatch(r"[0-9a-f]{16}|[0-9a-f]{64}", args.run_hash):
        parser.error("ticker/run ID 형식이 올바르지 않습니다")
    directory = Path(load_config()["archive_dir"]) / "runs"
    source = directory / f"{args.ticker}-{args.run_hash[:16]}.json"
    try:
        saved = json.loads(source.read_text())
        run = saved["run"]
        if (
            run["ticker"] != args.ticker
            or not re.fullmatch(r"[0-9a-f]{64}", run["run_hash"])
            or not run["run_hash"].startswith(args.run_hash)
        ):
            raise ValueError("identity mismatch")
        content = render(saved)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        print("해당 실행의 로컬 분석 파일을 읽을 수 없습니다. 분석 실행 단말과 실행 ID를 확인하세요.")
        return 2
    output = source.with_suffix(".html")
    output.write_text(content, encoding="utf-8")
    output.chmod(0o600)
    print(output)
    if args.open_browser:
        webbrowser.open(output.resolve().as_uri())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
