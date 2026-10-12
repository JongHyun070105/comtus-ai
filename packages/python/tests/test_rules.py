import unittest

from comtus_ai.models import CardType, GameMode
from comtus_ai.rules import RosterCard, SynergyRule, apply_declared_effects, evaluate_synergies, unlocked_training_milestones


class RuleTests(unittest.TestCase):
    def setUp(self):
        self.roster = [
            RosterCard(f"card-{i}", CardType.SEASON, "Samsung Lions", "BATTER" if i < 3 else "PITCHER")
            for i in range(5)
        ]
        self.rule = SynergyRule(
            rule_id="ref-general-7", mode=GameMode.RANKING_CHALLENGE,
            card_types=frozenset({CardType.SEASON}), threshold=3,
            attributes=frozenset({"power", "control"}), delta=1,
            source="USER_PROVIDED_REFERENCE", rules_version="reference-unverified",
            targets="BATTERS",
        )

    def test_position_training_milestones_are_slot_level_gates(self):
        self.assertEqual(unlocked_training_milestones(0), ())
        self.assertEqual(unlocked_training_milestones(5), ("ATTRIBUTE_BONUS",))
        self.assertEqual(unlocked_training_milestones(10), ("ATTRIBUTE_BONUS", "SKILL_BONUS"))
        self.assertEqual(len(unlocked_training_milestones(20)), 4)
        with self.assertRaises(ValueError):
            unlocked_training_milestones(99)

    def test_mode_scoping_and_threshold(self):
        other_mode = evaluate_synergies(GameMode.LEAGUE, self.roster, [self.rule], stats_include_modifiers=False)
        self.assertFalse(other_mode[0].eligible)
        short_roster = evaluate_synergies(GameMode.RANKING_CHALLENGE, self.roster[:2], [self.rule], stats_include_modifiers=False)
        self.assertFalse(short_roster[0].eligible)

    def test_does_not_double_apply_when_stats_already_include_effects_or_unknown(self):
        base = {f"card-{i}": {"power": 50.0} for i in range(5)}
        for provenance in (True, None):
            decisions = evaluate_synergies(GameMode.RANKING_CHALLENGE, self.roster, [self.rule], stats_include_modifiers=provenance)
            self.assertTrue(decisions[0].eligible)
            self.assertFalse(decisions[0].applied)
            result = apply_declared_effects(base, [self.rule], decisions)
            self.assertEqual(result["card-0"]["power"], 50.0)

    def test_applies_only_declared_effect_to_targets_and_deduplicates_rule_id(self):
        base = {f"card-{i}": {"power": 50.0, "control": 40.0} for i in range(5)}
        decisions = evaluate_synergies(GameMode.RANKING_CHALLENGE, self.roster, [self.rule, self.rule], stats_include_modifiers=False)
        self.assertEqual(len(decisions), 1)
        result = apply_declared_effects(base, [self.rule], decisions)
        self.assertEqual(result["card-0"]["power"], 51.0)
        self.assertEqual(result["card-2"]["control"], 41.0)
        self.assertEqual(result["card-3"]["power"], 50.0)


if __name__ == "__main__":
    unittest.main()
