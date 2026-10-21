#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYSTEM = ROOT / "episodes/_system"
if str(SYSTEM) not in sys.path:
    sys.path.insert(0, str(SYSTEM))

import storyos_config
import runtime_timeout_policy as ttp


class RuntimeTimeoutPolicyTests(unittest.TestCase):
    def test_config_matches_historical_defaults(self):
        cfg = storyos_config.load_config()
        policy = storyos_config.get_path(cfg, "timeout_policy")
        self.assertIsInstance(policy, dict)
        for role in ttp.REQUIRED_ROLES:
            self.assertEqual(policy.get(role), ttp.DEFAULT_SECONDS[role], role)
            self.assertEqual(ttp.seconds(role), policy[role], role)

    def test_clamp_bounds(self):
        self.assertEqual(ttp.clamp("fast_scout", 10_000), 240)
        self.assertEqual(ttp.clamp("fast_scout", 10), 60)
        self.assertEqual(ttp.clamp("image_lane_run", 10_000), 600)
        self.assertEqual(ttp.clamp("image_lane_run", 10), 60)
        self.assertEqual(ttp.clamp("review_critic", 456), 456)

    def test_unknown_role_rejected(self):
        with self.assertRaises(ValueError):
            ttp.seconds("no_such_role")

    def test_resolve_default_and_override(self):
        self.assertEqual(ttp.resolve("review_critic", None), ttp.DEFAULT_SECONDS["review_critic"])
        self.assertEqual(ttp.resolve("review_critic", 42), 42)
        with self.assertRaises(ValueError):
            ttp.resolve("review_critic", 0)

    def test_valid_range_covers_clamped_and_provider_roles(self):
        # Config defaults must sit inside their declared allowed range.
        for role in ttp.VALID_RANGE:
            low, high = ttp.VALID_RANGE[role]
            self.assertTrue(low <= ttp.DEFAULT_SECONDS[role] <= high, role)

    def test_validate_rejects_non_mapping(self):
        cfg = copy.deepcopy(storyos_config.load_config())
        cfg["timeout_policy"] = None
        errors = storyos_config.validate(cfg)
        self.assertTrue(any("timeout_policy must be a mapping" in e for e in errors))

    def test_validate_rejects_non_positive_int(self):
        cfg = copy.deepcopy(storyos_config.load_config())
        cfg["timeout_policy"]["fast_scout"] = -1
        errors = storyos_config.validate(cfg)
        self.assertTrue(any("timeout_policy.fast_scout" in e for e in errors))

    def test_validate_rejects_out_of_range_defaults(self):
        # B8: fast_scout below its clamp floor, image_worker_request above the
        # provider channel ceiling, and fast_scout above its 240 ceiling.
        cfg = copy.deepcopy(storyos_config.load_config())
        cfg["timeout_policy"]["fast_scout"] = 50
        errors = storyos_config.validate(cfg)
        self.assertTrue(any("timeout_policy.fast_scout" in e and "60..240" in e for e in errors))

        cfg = copy.deepcopy(storyos_config.load_config())
        cfg["timeout_policy"]["image_worker_request"] = 1300
        errors = storyos_config.validate(cfg)
        self.assertTrue(any("timeout_policy.image_worker_request" in e and "60..1200" in e for e in errors))

        cfg = copy.deepcopy(storyos_config.load_config())
        cfg["timeout_policy"]["fast_scout"] = 600
        errors = storyos_config.validate(cfg)
        self.assertTrue(any("timeout_policy.fast_scout" in e and "60..240" in e for e in errors))

    def test_role_mapping_matches_historical_module_defaults(self):
        # B8 mapping table: every role default equals its historical literal so
        # YAML remains the single default authority without behavior change.
        expected = {
            "codex_supervisor_run": 7200,
            "codex_scoped_step": 3600,
            "image_worker_request": 600,
            "image_lane_run": 600,
            "visual_baseline_critic": 300,
            "fast_scout": 240,
            "review_critic": 900,
            "codex_auth_probe": 30,
            "driver_carrier_control": 60,
            "image_probe": 900,
            "deep_semantic_review": 1800,
            "release_semantic": 1800,
            "isolated_ml_probe": 30,
            "isolated_ml_worker": 180,
        }
        # Preserve the historical contract, but new bounded roles are allowed
        # (and must also appear in the required YAML role registry).
        for role, seconds in expected.items():
            self.assertEqual(ttp.DEFAULT_SECONDS[role], seconds)
        additions = {
            "image_tool_visibility_probe": 120,
            "authority_lock": 30,
            "phase5a_canary_run": 900,
            "serial_episode_review": 1500,
            "serial_source_revision_review": 1200,
        }
        for role, seconds in additions.items():
            self.assertEqual(ttp.DEFAULT_SECONDS[role], seconds)
        self.assertEqual(set(ttp.DEFAULT_SECONDS), set(expected) | set(additions))
        self.assertEqual(ttp.REQUIRED_ROLES, tuple(ttp.DEFAULT_SECONDS))


if __name__ == "__main__":
    unittest.main()
