import unittest

from comtus_ai.fingerprint import fingerprint
from comtus_ai.models import (
    BatterStats, CardInstance, CardMaster, CardType, EvidenceSource, PitchGradeRecord,
    PitcherStats, PlayerRole, PlayerSnapshot, PotentialRecord, SkillRecord,
    normalize_grade, parse_card_type,
)


class ModelTests(unittest.TestCase):
    def test_card_type_is_independent_of_stars_year_live_version_and_enhancement(self):
        card = CardInstance(
            account_key="account-a",
            master=CardMaster("example", "Samsung Lions", CardType.LIVE, 2026),
            stars=5,
            live_version="V2",
            enhancement=5,
        )
        self.assertEqual(card.master.card_type, CardType.LIVE)
        self.assertEqual((card.stars, card.master.season_year, card.live_version, card.enhancement), (5, 2026, "V2", 5))

    def test_unknown_card_types_do_not_guess(self):
        self.assertEqual(parse_card_type(None), CardType.UNKNOWN)
        self.assertEqual(parse_card_type("unrecognized"), CardType.UNKNOWN)
        self.assertEqual(parse_card_type("national_team"), CardType.NATIONAL_TEAM)

    def test_potential_and_pitch_grades_remain_ordinal_labels(self):
        self.assertEqual([normalize_grade(x) for x in ("E", "C", "C+", "S", "SR+")], ["E", "C", "C+", "S", "SR+"])
        self.assertIsNone(normalize_grade("   "))

    def test_instance_validation(self):
        with self.assertRaises(ValueError):
            CardInstance("account-a", CardMaster("a", None), stars=6)
        with self.assertRaises(ValueError):
            CardInstance("account-a", CardMaster("a", None), enhancement=-1)

    def test_fingerprint_is_key_order_independent_and_sensitive_to_roster_state(self):
        first = {"players": [{"card_id": "p1", "skills": ["x"]}], "ovr": 86.6}
        reordered = {"ovr": 86.6, "players": [{"skills": ["x"], "card_id": "p1"}]}
        upgraded = {"ovr": 86.6, "players": [{"card_id": "p1", "skills": ["y"]}]}
        self.assertEqual(fingerprint(first), fingerprint(reordered))
        self.assertNotEqual(fingerprint(first), fingerprint(upgraded))

    def test_player_snapshot_has_role_specific_stats_skills_grade_and_source(self):
        card = CardInstance("account-a", CardMaster("player", "Samsung", CardType.LIVE, 2026), stars=5, live_version="V2", enhancement=5)
        batter = PlayerSnapshot(card=card, role=PlayerRole.BATTER, stats=BatterStats(power=120),
                                skills=(SkillRecord(1, "skill", 6, EvidenceSource.USER_PROVIDED_REFERENCE),),
                                potentials=(PotentialRecord("potential", "e", False, EvidenceSource.MANUAL_TRANSCRIPTION),),
                                hot_cold_zones=(None,) * 9, source=EvidenceSource.USER_PROVIDED_REFERENCE)
        self.assertEqual(batter.potentials[0].grade, "E")
        self.assertEqual(batter.stats.power, 120)
        self.assertEqual(batter.source, EvidenceSource.USER_PROVIDED_REFERENCE)
        self.assertEqual(PitchGradeRecord("fastball", "sr+", EvidenceSource.SYNTHETIC_TEST).grade, "SR+")
        with self.assertRaises(ValueError):
            PlayerSnapshot(card=card, role=PlayerRole.BATTER, stats=PitcherStats(velocity=150))
        with self.assertRaises(ValueError):
            PlayerSnapshot(card=card, role=PlayerRole.BATTER, hot_cold_zones=(0.0,))


if __name__ == "__main__":
    unittest.main()
