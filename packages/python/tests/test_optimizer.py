import unittest

from comtus_ai.optimizer import Opponent, Pitcher, optimize_rotation


def inputs():
    pitchers = [Pitcher(f"card-{i}", "same visible name" if i < 2 else f"Pitcher {i}") for i in range(5)]
    opponents = [Opponent(f"team-{i}", f"Opponent {i}") for i in range(5)]
    return pitchers, opponents


class OptimizerTests(unittest.TestCase):
    def test_explores_all_one_to_one_permutations_and_finds_best_specific_pairings(self):
        pitchers, opponents = inputs()
        scores = {(p.card_id, o.opponent_id): 0.0 for p in pitchers for o in opponents}
        for i in range(5):
            scores[(f"card-{i}", f"team-{i}")] = 100.0
        result = optimize_rotation(pitchers, opponents, scores)
        self.assertEqual(len(result.ties), 1)
        self.assertEqual(result.recommended, tuple(f"card-{i}" for i in range(5)))
        self.assertEqual(result.known_matchups, 25)
        self.assertEqual(result.total_matchups, 25)
        self.assertEqual(result.score_type, "HEURISTIC_SCORE")

    def test_all_tied_scores_report_all_120_optima_deterministically(self):
        pitchers, opponents = inputs()
        scores = {(p.card_id, o.opponent_id): 2.0 for p in pitchers for o in opponents}
        result = optimize_rotation(pitchers, opponents, scores)
        self.assertEqual(len(result.ties), 120)
        self.assertEqual(result.recommended, result.ties[0])

    def test_missing_scores_are_unknown_not_wins_and_report_low_confidence(self):
        pitchers, opponents = inputs()
        scores = {("card-0", "team-0"): 5.0}
        result = optimize_rotation(pitchers, opponents, scores)
        self.assertEqual(result.known_matchups, 1)
        self.assertEqual(result.data_confidence, "LOW")
        self.assertIsNone(result.matrix["card-1"]["team-1"])
        self.assertFalse(result.to_dict(pitchers, opponents)["probability_calibrated"])

    def test_even_if_every_opponent_is_stronger_best_available_assignment_is_returned(self):
        pitchers, opponents = inputs()
        scores = {(p.card_id, o.opponent_id): -float(i + 1) for i, p in enumerate(pitchers) for o in opponents}
        result = optimize_rotation(pitchers, opponents, scores)
        self.assertEqual(len(result.recommended), 5)
        self.assertEqual(len(set(result.recommended)), 5)

    def test_same_visible_name_cards_remain_distinct_by_identity(self):
        pitchers, opponents = inputs()
        result = optimize_rotation(pitchers, opponents, {}, input_source="SYNTHETIC_TEST")
        rendered = result.to_dict(pitchers, opponents)["recommended_rotation"]
        self.assertEqual(rendered[0]["pitcher"], rendered[1]["pitcher"])
        self.assertNotEqual(rendered[0]["pitcher_card_id"], rendered[1]["pitcher_card_id"])
        report = result.to_dict(pitchers, opponents)
        self.assertEqual(report["input_source"], "SYNTHETIC_TEST")
        self.assertEqual(report["baseline_rotation"][0]["opponent_id"], "team-0")
        self.assertFalse(report["probability_calibrated"])

    def test_invalid_inputs_are_rejected(self):
        pitchers, opponents = inputs()
        with self.assertRaises(ValueError):
            optimize_rotation(pitchers[:4], opponents, {})
        with self.assertRaises(ValueError):
            optimize_rotation(pitchers, opponents, {("card-0", "team-0"): float("nan")})


if __name__ == "__main__":
    unittest.main()
