"""kis_realtime.py branch coverage — Issue #616 Phase 3-C5.

| line | branch / stmt | trigger |
|---|---|---|
| 173→184 | `if creds.is_valid():` False (YAML loaded but blank fields) | YAML 존재 + 모든 키 빈 문자열 |

Note: 310→exit / 359→355 dead-by-design (retry-loop 자연 종료 불가) — publisher.py
follow-up 과 묶어 별도 refactor PR + Codex review 처리.
"""

from __future__ import annotations

from unittest.mock import patch

import yaml


class TestYamlLoadedButCredsInvalid:
    def test_yaml_present_but_blank_fields_returns_none(self, monkeypatch, tmp_path):
        """173→184: YAML 파일 존재 + 파싱 성공 → 빈 키 → is_valid()=False → fall-through return None."""
        # env 우선순위 차단
        monkeypatch.delenv("KIS_PROD_APP_KEY", raising=False)
        monkeypatch.delenv("KIS_PROD_APP_SECRET", raising=False)
        monkeypatch.delenv("KIS_PROD_ACCOUNT", raising=False)
        monkeypatch.delenv("KIS_HTS_ID", raising=False)

        # YAML 파일은 존재하지만 모든 KIS 키가 빈 문자열
        yaml_path = tmp_path / "kis_devlp.yaml"
        yaml_path.write_text(
            yaml.safe_dump(
                {
                    "my_app": "",
                    "my_sec": "",
                    "my_acct_stock": "",
                    "my_htsid": "",
                }
            ),
            encoding="utf-8",
        )

        from nuri.collectors.kis_realtime import load_credentials

        with patch("nuri.collectors.kis_realtime.KIS_YAML_PATH", yaml_path):
            creds = load_credentials("prod")

        assert creds is None
