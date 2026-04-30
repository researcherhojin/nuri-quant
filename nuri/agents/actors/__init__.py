"""nuri.agents.actors — concrete 15-actor implementations (#529 Phase 2+).

Phase 2 첫 actor: ReleaseRollbackManager (Layer A enforcement).
다음 PR 부터는 이 actor 가 PR open + label + CI watch + merge 자동화.
"""

from nuri.agents.actors.release_rollback_manager import ReleaseRollbackManager

__all__ = ["ReleaseRollbackManager"]
