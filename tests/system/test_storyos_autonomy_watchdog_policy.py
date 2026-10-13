from test_storyos_autonomy_watchdog_common import wd,good,EP
import pytest

@pytest.mark.parametrize("state,liveness,code,wanted",[
 ("ABNORMAL_DISAPPEARANCE","DEAD","","RECOVER"),
 ("EXITED","DEAD","0","RECOVER"),
 ("EXITED","DEAD","21","BLOCK"),
 ("EXITED","DEAD","23","BLOCK"),
 ("RUNNING","ALIVE","","WAIT"),
 ("ALIVE_NOT_BEATING","ALIVE","","BLOCK"),
 ("NEVER_STARTED","DEAD","","WAIT"),
 ("UNKNOWN","UNKNOWN","","BLOCK"),
 ("ABNORMAL_DISAPPEARANCE","UNKNOWN","","BLOCK"),
])
def test_readonly_policy_cannot_dispatch_unsafe_driver(state,liveness,code,wanted):
    report=good(state,liveness=liveness,code=code)
    decision=wd.policy_decision(report,expected_episode=EP)
    assert decision["action"]==wanted

@pytest.mark.parametrize("mutate",[
 lambda r:r.update(status="BLOCKED"),
 lambda r:r.update(episode="episodes/00_独立篇/other"),
 lambda r:r["attempt"].update(outcome_unknown_assets=["06"]),
 lambda r:r["attempt"].update(active_attempt_assets=["06"]),
 lambda r:r["mysql"].update(schema_status="UNKNOWN"),
 lambda r:r["episode_stage"].update(source="json"),
 lambda r:r.update(production_mode="COLLABORATIVE"),
 lambda r:r.update(read_only=False),
])
def test_authority_mismatch_never_recovers(mutate):
    report=good()
    mutate(report)
    assert wd.policy_decision(report,expected_episode=EP)["action"]=="BLOCK"
