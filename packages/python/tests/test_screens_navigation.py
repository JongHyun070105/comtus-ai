import unittest

from comtus_ai.navigation import (
    CoordinateOrigin,
    MockUIActionAdapter,
    NavigationPlanner,
    PlayerPageTracker,
    SafetyController,
    ScreenFrame,
    SessionStatus,
    SimulatedNavigator,
    Transition,
    UIAction,
    WindowGeometry,
)
from comtus_ai.observations import OCRObservation
from comtus_ai.models import EvidenceSource
from comtus_ai.screens import (
    ClassificationStatus,
    NormalizedRect,
    PanelLayout,
    PanelRole,
    ScreenState,
    recognize_screen,
)


def verified(state, *, player=None, page=None, panel=PanelRole.UNKNOWN):
    return ScreenFrame(state, ClassificationStatus.VERIFIED, player, player is not None,
                       page, page is not None, panel)


def ocr(text, confidence, bbox):
    return OCRObservation(text, confidence, bbox, EvidenceSource.SCREEN_CAPTURE_VERIFIED)


class ScreenRecognitionTests(unittest.TestCase):
    def test_pitcher_order_uses_title_instruction_and_bottom_actions(self):
        rows = (
            ocr("{ 선발 투수 변경", 0.5, (0.365, 0.825, 0.244, 0.028)),
            ocr("좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", 1.0, (0.289, 0.789, 0.435, 0.016)),
            ocr("원래대로", 1.0, (0.245, 0.056, 0.080, 0.019)),
            ocr("저장", 0.5, (0.696, 0.056, 0.042, 0.019)),
        )

        result = recognize_screen(rows)

        self.assertEqual(result.state, ScreenState.PITCHER_ORDER)
        self.assertEqual(result.status, ClassificationStatus.CANDIDATE)
        self.assertEqual(result.confidence, 0.5)
        self.assertEqual(len(result.anchor_indices), 4)
        self.assertIsNone(result.active_panel)
        self.assertIsNone(result.left_preview)
        self.assertIsNone(result.right_preview)

    def test_single_anchor_and_unprofiled_screens_remain_unknown(self):
        self.assertEqual(recognize_screen((ocr("랭킹 챌린지", 1.0, (0.43, 0.93, 0.1, 0.02)),)).state,
                         ScreenState.UNKNOWN)
        for state in (
            ScreenState.RANKING_LOBBY, ScreenState.OPPONENT_LINEUP,
            ScreenState.OPPONENT_STARTING_PITCHER_DETAIL, ScreenState.PLAYER_DETAIL_BATTER,
            ScreenState.PLAYER_DETAIL_PITCHER, ScreenState.TEAM_ROSTER,
            ScreenState.SYNERGY, ScreenState.POSITION_TRAINING,
        ):
            self.assertNotEqual(state, ScreenState.PITCHER_ORDER)

    def test_panel_layout_requires_explicit_non_overlapping_bounds(self):
        layout = PanelLayout(
            active=NormalizedRect(0.4, 0.0, 0.2, 1.0),
            left_preview=NormalizedRect(0.1, 0.0, 0.2, 1.0),
            right_preview=NormalizedRect(0.7, 0.0, 0.2, 1.0),
        )
        self.assertEqual(layout.role_for((0.45, 0.4, 0.1, 0.1)), PanelRole.ACTIVE)
        self.assertEqual(layout.role_for((0.15, 0.4, 0.1, 0.1)), PanelRole.LEFT_PREVIEW)
        self.assertEqual(layout.role_for((0.75, 0.4, 0.1, 0.1)), PanelRole.RIGHT_PREVIEW)
        self.assertEqual(layout.role_for((0.32, 0.4, 0.04, 0.1)), PanelRole.UNKNOWN)


class PlayerPageTrackingTests(unittest.TestCase):
    def test_player_switch_and_page_switch_are_independent_and_invalidate_fields(self):
        tracker = PlayerPageTracker()
        first = tracker.observe(verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:p1", page=1,
                                         panel=PanelRole.ACTIVE))
        self.assertTrue(first.accepted)
        self.assertTrue(tracker.can_commit_player_fields)
        self.assertTrue(tracker.stage_field({"contact": 80}))

        page_two = tracker.observe(verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:p1", page=2,
                                            panel=PanelRole.ACTIVE), expected_action=UIAction.NEXT_PAGE)
        self.assertTrue(page_two.accepted)
        self.assertFalse(page_two.player_changed)
        self.assertTrue(page_two.page_changed)
        self.assertEqual(tracker.player_epoch, 1)
        self.assertEqual(tracker.page_epoch, 2)
        self.assertEqual(tracker.take_fields(), ())

        second_player = tracker.observe(verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:p2", page=1,
                                                 panel=PanelRole.ACTIVE), expected_action=UIAction.NEXT_PLAYER)
        self.assertTrue(second_player.accepted)
        self.assertTrue(second_player.player_changed)
        self.assertEqual(tracker.player_key, "synthetic:p2")
        self.assertEqual(tracker.page, 1)
        self.assertEqual(tracker.take_fields(), ())

    def test_unexpected_player_or_page_change_cannot_receive_fields(self):
        tracker = PlayerPageTracker()
        tracker.observe(verified(ScreenState.PLAYER_DETAIL_PITCHER, player="synthetic:p1", page=1,
                                 panel=PanelRole.ACTIVE))
        tracker.stage_field({"velocity": 90})

        unexpected = tracker.observe(verified(ScreenState.PLAYER_DETAIL_PITCHER, player="synthetic:p2", page=1,
                                              panel=PanelRole.ACTIVE))
        self.assertFalse(unexpected.accepted)
        self.assertTrue(unexpected.fields_invalidated)
        self.assertIsNone(tracker.player_key)
        self.assertFalse(tracker.can_commit_player_fields)
        self.assertEqual(tracker.take_fields(), ())

    def test_unverified_or_preview_context_never_commits_player_fields(self):
        tracker = PlayerPageTracker()
        tracker.observe(verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:p1", page=1,
                                 panel=PanelRole.RIGHT_PREVIEW))
        self.assertFalse(tracker.can_commit_player_fields)
        self.assertFalse(tracker.stage_field({"power": 90}))
        tracker.observe(ScreenFrame(ScreenState.PLAYER_DETAIL_BATTER, ClassificationStatus.CANDIDATE))
        self.assertFalse(tracker.can_commit_player_fields)


class NavigationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.transitions = (
            Transition(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER, ScreenState.PITCHER_ORDER),
            Transition(ScreenState.PITCHER_ORDER, UIAction.OPEN_OPPONENT_LINEUP, ScreenState.OPPONENT_LINEUP),
            Transition(ScreenState.OPPONENT_LINEUP, UIAction.BACK, ScreenState.PITCHER_ORDER),
        )
        self.planner = NavigationPlanner(self.transitions)

    def test_planner_finds_route_without_revisiting_states(self):
        route = self.planner.plan(ScreenState.RANKING_LOBBY, ScreenState.OPPONENT_LINEUP)
        self.assertEqual(route.states, (ScreenState.RANKING_LOBBY, ScreenState.PITCHER_ORDER, ScreenState.OPPONENT_LINEUP))
        self.assertEqual(len(set(route.states)), len(route.states))
        self.assertIsNone(self.planner.plan(ScreenState.RANKING_LOBBY, ScreenState.OPPONENT_LINEUP, max_depth=1))
        self.assertIsNone(self.planner.plan(ScreenState.RANKING_LOBBY, ScreenState.SYNERGY))

    def test_mock_navigation_requires_explicit_start_and_verifies_each_transition(self):
        start = verified(ScreenState.RANKING_LOBBY)
        order = verified(ScreenState.PITCHER_ORDER)
        lineup = verified(ScreenState.OPPONENT_LINEUP)
        adapter = MockUIActionAdapter({
            (ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): order,
            (ScreenState.PITCHER_ORDER, UIAction.OPEN_OPPONENT_LINEUP): lineup,
        })
        navigator = SimulatedNavigator(self.planner)
        with self.assertRaises(ValueError):
            navigator.run(start_frame=start, goal=ScreenState.OPPONENT_LINEUP, adapter=adapter,
                          safety=SafetyController(), explicitly_requested=False)

        result = navigator.run(start_frame=start, goal=ScreenState.OPPONENT_LINEUP, adapter=adapter,
                               safety=SafetyController(max_depth=3), explicitly_requested=True)
        self.assertEqual(result.status, SessionStatus.COMPLETE)
        self.assertEqual(result.final_frame.state, ScreenState.OPPONENT_LINEUP)
        self.assertEqual(len(adapter.actions), 2)

    def test_wrong_post_action_screen_halts_and_does_not_retry(self):
        start = verified(ScreenState.RANKING_LOBBY)
        wrong = verified(ScreenState.SYNERGY)
        adapter = MockUIActionAdapter({(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): wrong})
        safety = SafetyController(max_depth=3, max_retries=2)

        result = SimulatedNavigator(self.planner).run(
            start_frame=start, goal=ScreenState.PITCHER_ORDER, adapter=adapter,
            safety=safety, explicitly_requested=True,
        )

        self.assertEqual(result.status, SessionStatus.HALTED)
        self.assertIn("post-action screen", result.halt_reason)
        self.assertEqual(len(adapter.actions), 1)

    def test_transient_failure_retries_once_but_emergency_stop_is_terminal(self):
        start = verified(ScreenState.RANKING_LOBBY)
        order = verified(ScreenState.PITCHER_ORDER)
        adapter = MockUIActionAdapter(
            {(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): order},
            {(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): 1},
        )
        result = SimulatedNavigator(self.planner).run(
            start_frame=start, goal=ScreenState.PITCHER_ORDER, adapter=adapter,
            safety=SafetyController(max_depth=2, max_retries=1), explicitly_requested=True,
        )
        self.assertEqual(result.status, SessionStatus.COMPLETE)
        self.assertEqual(len(adapter.actions), 2)

        stopped = SafetyController()
        stopped.start(explicitly_requested=True)
        stopped.emergency_stop()
        self.assertEqual(stopped.status, SessionStatus.HALTED)
        self.assertEqual(stopped.halt_reason, "emergency stop")

    def test_retry_and_depth_limits_halt_without_extra_actions(self):
        start = verified(ScreenState.RANKING_LOBBY)
        adapter = MockUIActionAdapter(
            {(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): verified(ScreenState.PITCHER_ORDER)},
            {(ScreenState.RANKING_LOBBY, UIAction.OPEN_PITCHER_ORDER): 2},
        )
        result = SimulatedNavigator(self.planner).run(
            start_frame=start, goal=ScreenState.PITCHER_ORDER, adapter=adapter,
            safety=SafetyController(max_depth=2, max_retries=1), explicitly_requested=True,
        )
        self.assertEqual(result.status, SessionStatus.HALTED)
        self.assertIn("retry", result.halt_reason)
        self.assertEqual(len(adapter.actions), 2)

        safety = SafetyController(max_depth=1)
        safety.start(explicitly_requested=True)
        transition = self.transitions[0]
        self.assertFalse(safety.before_action(frame=start, transition=transition, depth=1, step_index=0))
        self.assertIn("depth", safety.halt_reason)

    def test_user_input_pauses_and_requires_explicit_resume(self):
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        safety.pause_for_user_input()
        self.assertEqual(safety.status, SessionStatus.PAUSED)
        with self.assertRaises(RuntimeError):
            safety.resume(explicitly_requested=False)
        safety.resume(explicitly_requested=True)
        self.assertEqual(safety.status, SessionStatus.COLLECTING)

    def test_only_allowlisted_navigation_intents_are_accepted(self):
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        unsafe = Transition(ScreenState.RANKING_LOBBY, "START_MATCH", ScreenState.PITCHER_ORDER)  # type: ignore[arg-type]
        self.assertFalse(safety.before_action(frame=verified(ScreenState.RANKING_LOBBY), transition=unsafe,
                                             depth=0, step_index=0))
        self.assertEqual(safety.status, SessionStatus.HALTED)


class CoordinateMappingTests(unittest.TestCase):
    def test_window_move_and_resize_change_coordinates_from_current_geometry(self):
        bbox = (0.25, 0.25, 0.1, 0.1)
        first = WindowGeometry(100, 200, 800, 1000)
        moved_and_resized = WindowGeometry(300, 400, 1200, 1500)

        point_one = first.map_vision_bbox(bbox, origin=CoordinateOrigin.TOP_LEFT)
        point_two = moved_and_resized.map_vision_bbox(bbox, origin=CoordinateOrigin.TOP_LEFT)
        bottom_origin = first.map_vision_bbox(bbox, origin=CoordinateOrigin.BOTTOM_LEFT)

        self.assertEqual(point_one, (340.0, 900.0))
        self.assertEqual(point_two, (660.0, 1450.0))
        self.assertNotEqual(point_one, point_two)
        self.assertEqual(bottom_origin, (340.0, 500.0))


if __name__ == "__main__":
    unittest.main()
