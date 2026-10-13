import unittest

from comtus_ai.models import EvidenceSource
from comtus_ai.observations import OCRObservation
from comtus_ai.parsing import (
    ExtractionStatus,
    VerifiedFieldContext,
    card_identity_candidate,
    parse_ocr_fields,
    resolve_season_year,
    verify_field_candidate,
)
from comtus_ai.screens import (
    ClassificationStatus,
    NormalizedRect,
    PanelLayout,
    PanelRole,
    ScreenState,
)


def observation(text, confidence=0.99, bbox=(0.42, 0.4, 0.12, 0.03), source=EvidenceSource.SYNTHETIC_TEST):
    return OCRObservation(text, confidence, bbox, source)


class OCRFieldParsingTests(unittest.TestCase):
    def test_player_name_and_year_are_candidates_with_provenance(self):
        rows = (observation("홍길동'25"),)
        active = NormalizedRect(0.4, 0.0, 0.2, 1.0)

        fields = parse_ocr_fields(rows, active_panel=active, reference_year=2026)

        self.assertEqual([(row.field_key, row.value) for row in fields], [
            ("player_name", "홍길동"), ("season_year", 2025),
        ])
        self.assertTrue(all(row.status == ExtractionStatus.CANDIDATE for row in fields))
        self.assertTrue(all(row.source == EvidenceSource.SYNTHETIC_TEST for row in fields))
        self.assertTrue(all(row.observation_indices == (0,) for row in fields))
        self.assertTrue(all(row.panel_role == PanelRole.ACTIVE for row in fields))
        identity = card_identity_candidate(fields)
        self.assertEqual(identity.canonical_name, "홍길동")
        self.assertEqual(identity.season_year, 2025)
        self.assertEqual(identity.panel_bounds, (0.4, 0.0, 0.2, 1.0))
        self.assertIsNone(identity.instance_key)
        self.assertEqual(identity.status, "UNRESOLVED")

    def test_card_type_stars_enhancement_and_labelled_ovr_are_independent_fields(self):
        rows = (
            observation("시그니처", bbox=(0.44, 0.45, 0.1, 0.03)),
            observation("★★★★★", bbox=(0.44, 0.40, 0.1, 0.03)),
            observation("+8", bbox=(0.44, 0.35, 0.1, 0.03)),
            observation("상대 타자 OVR", bbox=(0.62, 0.7, 0.15, 0.03)),
            observation("112.5", bbox=(0.65, 0.64, 0.08, 0.04)),
            observation("98", bbox=(0.2, 0.6, 0.04, 0.03)),
        )

        fields = parse_ocr_fields(rows, active_panel=NormalizedRect(0.58, 0.60, 0.22, 0.18))

        self.assertEqual({(row.field_key, row.value) for row in fields}, {
            ("card_type", "SIGNATURE"), ("stars", 5), ("enhancement", 8),
            ("opponent_batter_ovr", 112.5),
        })
        self.assertTrue(all(row.status == ExtractionStatus.CANDIDATE for row in fields))
        self.assertFalse(any(row.field_key == "overall" and row.value == 98 for row in fields))

    def test_low_confidence_values_are_preserved_as_unknown_not_promoted(self):
        row = observation("김선수'24", confidence=0.5, source=EvidenceSource.SCREEN_CAPTURE_VERIFIED)

        fields = parse_ocr_fields((row,))

        self.assertEqual([field.field_key for field in fields], ["player_name", "season_year"])
        self.assertTrue(all(field.status == ExtractionStatus.LOW_CONFIDENCE for field in fields))
        self.assertTrue(all(field.value is None and field.confidence == 0.5 for field in fields))
        self.assertTrue(all(field.source == EvidenceSource.SCREEN_CAPTURE_VERIFIED for field in fields))

    def test_ovr_requires_nearby_explicit_label_and_uses_minimum_confidence(self):
        rows = (
            observation("상대 타자 OVR", confidence=0.5, bbox=(0.62, 0.7, 0.15, 0.03)),
            observation("90.5", confidence=0.99, bbox=(0.65, 0.64, 0.08, 0.04)),
            observation("88.1", confidence=0.99, bbox=(0.2, 0.2, 0.08, 0.04)),
        )

        fields = parse_ocr_fields(rows, active_panel=NormalizedRect(0.58, 0.60, 0.22, 0.18))

        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0].field_key, "opponent_batter_ovr")
        self.assertIsNone(fields[0].value)
        self.assertEqual(fields[0].confidence, 0.5)
        self.assertEqual(fields[0].status, ExtractionStatus.LOW_CONFIDENCE)
        self.assertEqual(fields[0].observation_indices, (1, 0))

    def test_panel_layout_separates_active_and_previews_without_default_bounds(self):
        rows = (observation("홍길동'25", bbox=(0.66, 0.4, 0.1, 0.03)),)
        layout = PanelLayout(
            active=NormalizedRect(0.4, 0.0, 0.2, 1.0),
            left_preview=NormalizedRect(0.1, 0.0, 0.2, 1.0),
            right_preview=NormalizedRect(0.6, 0.0, 0.2, 1.0),
        )

        fields = parse_ocr_fields(rows, panel_layout=layout)

        self.assertTrue(all(field.panel_role == PanelRole.RIGHT_PREVIEW for field in fields))
        unscoped = parse_ocr_fields(rows)
        self.assertTrue(all(field.panel_role == PanelRole.UNKNOWN for field in unscoped))

    def test_duplicate_card_labels_remain_separate_observations(self):
        rows = (
            observation("홍길동'25", bbox=(0.2, 0.5, 0.1, 0.03)),
            observation("홍길동'25", bbox=(0.7, 0.5, 0.1, 0.03)),
        )

        fields = parse_ocr_fields(rows)
        names = [field for field in fields if field.field_key == "player_name"]

        self.assertEqual(len(names), 2)
        self.assertEqual([field.observation_indices for field in names], [(0,), (1,)])
        self.assertTrue(all(field.context_dict()["instance_identity"] == "UNRESOLVED" for field in names))
        identity = card_identity_candidate(fields)
        self.assertIsNone(identity.canonical_name)
        self.assertIsNone(identity.instance_key)
        self.assertIn("multiple cards", identity.reason)

    def test_two_digit_season_years_use_the_kbo_window_not_a_2000_prefix(self):
        cases = (
            ("이만수'83", 1983),
            ("동봉철'92", 1992),
            ("양준혁'98", 1998),
            ("이승엽'00", 2000),
            ("박진만'07", 2007),
            ("후라도'26", 2026),
        )
        for label, year in cases:
            with self.subTest(label=label):
                fields = parse_ocr_fields((observation(label),), reference_year=2026)
                year_field = next(field for field in fields if field.field_key == "season_year")
                self.assertEqual(year_field.value, year)
                self.assertEqual(year_field.status, ExtractionStatus.CANDIDATE)
                self.assertEqual(year_field.year_candidates, (year,))

    def test_unresolvable_year_preserves_original_and_candidate_years(self):
        none = resolve_season_year("'80", reference_year=2026)
        ambiguous = resolve_season_year("'00", reference_year=2100)
        self.assertEqual(none.status, ExtractionStatus.UNRESOLVED)
        self.assertEqual(none.original, "'80")
        self.assertEqual(none.candidates, ())
        self.assertEqual(ambiguous.status, ExtractionStatus.UNRESOLVED)
        self.assertEqual(ambiguous.original, "'00")
        self.assertEqual(ambiguous.candidates, (2000, 2100))
        fields = parse_ocr_fields((observation("이름'80"),), reference_year=2026)
        year_field = next(field for field in fields if field.field_key == "season_year")
        self.assertIsNone(year_field.value)
        self.assertEqual(year_field.status, ExtractionStatus.UNRESOLVED)
        self.assertEqual(year_field.raw_value, "이름'80")

    def test_panel_membership_requires_full_box_and_safe_edge_margin(self):
        panel = NormalizedRect(0.4, 0.2, 0.2, 0.6)
        self.assertTrue(panel.contains((0.45, 0.4, 0.1, 0.1)))
        self.assertFalse(panel.contains((0.55, 0.4, 0.1, 0.1)))
        self.assertFalse(panel.contains((0.585, 0.4, 0.01, 0.1)))
        with self.assertRaises(ValueError):
            PanelLayout(
                active=NormalizedRect(0.3, 0.1, 0.4, 0.8),
                left_preview=NormalizedRect(0.1, 0.1, 0.3, 0.8),
                right_preview=NormalizedRect(0.7, 0.1, 0.2, 0.8),
            )

    def test_ovr_values_crossing_panel_edges_are_not_attached_to_the_active_card(self):
        layout = PanelLayout(
            active=NormalizedRect(0.4, 0.1, 0.2, 0.8),
            left_preview=NormalizedRect(0.1, 0.1, 0.2, 0.8),
            right_preview=NormalizedRect(0.7, 0.1, 0.2, 0.8),
        )
        rows = (
            observation("OVR", bbox=(0.49, 0.6, 0.07, 0.04)),
            observation("88", bbox=(0.55, 0.58, 0.08, 0.04)),
        )
        self.assertFalse(any(field.field_key == "overall" for field in parse_ocr_fields(rows, panel_layout=layout)))

    def test_high_ocr_confidence_needs_player_screen_page_and_card_panel_review(self):
        row = observation("홍길동'25", bbox=(0.45, 0.4, 0.1, 0.04))
        panel = NormalizedRect(0.4, 0.2, 0.2, 0.6)
        candidate = next(field for field in parse_ocr_fields((row,), active_panel=panel)
                         if field.field_key == "player_name")
        self.assertEqual(candidate.status, ExtractionStatus.CANDIDATE)
        with self.assertRaises(ValueError):
            verify_field_candidate(candidate)

        context = VerifiedFieldContext(ScreenState.PLAYER_DETAIL_BATTER, ClassificationStatus.VERIFIED,
                                       "synthetic:player-1", 1, panel)
        grounded = next(field for field in parse_ocr_fields((row,), context=context, reference_year=2026)
                        if field.field_key == "player_name")
        verified = verify_field_candidate(grounded)
        self.assertEqual(verified.status, ExtractionStatus.VERIFIED)
        self.assertEqual(verified.player_key, "synthetic:player-1")
        self.assertEqual(verified.page, 1)
        self.assertEqual(verified.panel_role, PanelRole.ACTIVE)


if __name__ == "__main__":
    unittest.main()
