"""walk-forward 재현성 키 — 빈 데이터도 결정론 해시를 낸다."""

from __future__ import annotations

import pandas as pd

from nuri.agents.actors.walkforward_validator import FoldSpec, _compute_pit_hash


def test_an_empty_frame_still_hashes_deterministically():
    spec = FoldSpec(kind="rolling", train_size=20, test_size=5, step=5)
    empty = pd.DataFrame({"x": pd.Series([], dtype=float)})

    first = _compute_pit_hash(empty, "model-a", spec)

    assert first == _compute_pit_hash(empty.copy(), "model-a", spec)
    assert len(first) == 16
    assert first != _compute_pit_hash(pd.DataFrame({"x": [1.0, 2.0]}), "model-a", spec)
