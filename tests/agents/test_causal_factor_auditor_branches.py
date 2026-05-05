"""causal_factor_auditor.py branch coverage — Issue #616 Phase 3-C1.

147→149: `if rng is None:` False (호출자가 rng 주입) → 기본값 fallback skip.
"""

from __future__ import annotations

import numpy as np


class TestPlaceboFalsificationRngInjection:
    def test_with_caller_supplied_rng(self):
        """147→149: rng != None → 기본 default_rng(42) fallback skip."""
        from nuri.agents.actors.causal_factor_auditor import _placebo_falsification

        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02, 0.01, -0.01, 0.02])
        factor = np.array([1.0, 2.0, 1.5, 0.5, 1.8, 1.2, 0.9, 1.6])
        rng = np.random.default_rng(123)

        result = _placebo_falsification(returns, factor, n_runs=10, rng=rng)
        assert isinstance(result, dict)
