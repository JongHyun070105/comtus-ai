import json
import unittest

from comtus_ai.learning import MatchLabel, evaluate_predictions
from comtus_ai.observations import OCRObservation, load_ocr_document
from comtus_ai.models import EvidenceSource


class ObservationAndLearningTests(unittest.TestCase):
    def test_ocr_schema_adapter_validates_bbox_confidence_and_version(self):
        document = {"schema_version": 1, "observations": [{"schema_version": 1, "text": "후라도'26", "confidence": 0.98,
                     "bbox": [0.1, 0.2, 0.3, 0.05], "source": "SYNTHETIC_TEST", "field": "player_name"}]}
        parsed = load_ocr_document(json.dumps(document))
        self.assertEqual(parsed[0].text, "후라도'26")
        self.assertEqual(parsed[0].source, EvidenceSource.SYNTHETIC_TEST)
        with self.assertRaises(ValueError):
            OCRObservation.from_dict({**document["observations"][0], "confidence": 1.1})
        with self.assertRaises(ValueError):
            load_ocr_document(json.dumps({"schema_version": 2, "observations": []}))

    def test_no_real_results_means_no_metrics_and_labeled_rows_are_evaluated(self):
        self.assertEqual(evaluate_predictions([])["status"], "NO_LABELED_RESULTS")
        result = evaluate_predictions([MatchLabel(0.8, True, 4, 2), MatchLabel(0.2, False, 1, 3)])
        self.assertEqual(result["sample_count"], 2)
        self.assertAlmostEqual(result["metrics"]["brier_score"], 0.04)
        self.assertEqual(result["metrics"]["actual_win_rate"], 0.5)
        with self.assertRaises(ValueError):
            evaluate_predictions([MatchLabel(1.2, True)])


if __name__ == "__main__":
    unittest.main()
