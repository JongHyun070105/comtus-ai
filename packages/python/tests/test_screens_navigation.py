import json
from pathlib import Path
import unittest

from comtus_ai.navigation import (
    CoordinateOrigin,
    MockUIActionAdapter,
    NavigationVisitKey,
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
    ScreenClassification,
    ScreenState,
    recognize_screen,
)
from comtus_ai.ui_input import (
    AccountStateChangingAction,
    FIRST_STARTER_CARD_BOUNDS,
    LocalizedActionTarget,
    PITCHER_ORDER_LAYOUT_VERSION,
    SafeTargetKind,
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

    def test_shared_screen_contract_matches_python_state_anchor_confidence_and_version(self):
        fixture_path = Path(__file__).parents[3] / "schemas" / "v1" / "screen-classification-fixtures.json"
        fixture = json.loads(fixture_path.read_text())
        self.assertEqual([state.value for state in ScreenState], fixture["screen_states"])
        self.assertEqual(fixture["profile_version"], "screen-profiles-v3")
        for case in fixture["cases"]:
            rows = tuple(ocr(item["text"], item["confidence"], tuple(item["bbox"]))
                         for item in case["observations"])
            result = recognize_screen(rows)
            expected = case["expected"]
            with self.subTest(case=case["name"]):
                self.assertEqual(result.state.value, expected["state"])
                self.assertEqual(result.status.value, expected["status"])
                self.assertEqual(result.confidence, expected["confidence"])
                self.assertEqual(list(result.anchor_indices), expected["anchor_indices"])
                self.assertEqual(result.profile_version, fixture["profile_version"])

    def test_pitcher_order_uses_both_lineup_columns_and_footer_for_verified_status(self):
        rows = (
            ocr("선발 투수 변경", 0.5, (0.4, 0.82, 0.2, 0.03)),
            ocr("좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", 1.0, (0.289, 0.789, 0.435, 0.016)),
            ocr("원래대로", 1.0, (0.245, 0.056, 0.080, 0.019)),
            ocr("저장", 0.5, (0.696, 0.056, 0.042, 0.019)),
            ocr("1선발 R", 1.0, (0.222, 0.737, 0.050, 0.012)),
            ocr("3선발 L", 1.0, (0.222, 0.218, 0.050, 0.013)),
            ocr("3선발 R", 1.0, (0.373, 0.735, 0.050, 0.013)),
            ocr("5선발 R", 1.0, (0.373, 0.218, 0.050, 0.012)),
            ocr("선수 교체", 0.5, (0.457, 0.053, 0.086, 0.021)),
            ocr("< 뒤로가기", 0.5, (0.439, 0.012, 0.114, 0.019)),
        )

        result = recognize_screen(rows)

        self.assertEqual(result.state, ScreenState.PITCHER_ORDER)
        self.assertEqual(result.status, ClassificationStatus.VERIFIED)
        self.assertEqual(result.confidence, 1.0)
        self.assertEqual(result.anchor_indices, tuple(range(10)))

    def test_pitcher_order_does_not_verify_repeated_or_low_confidence_roles(self):
        rows = (
            ocr("선발 투수 변경", 0.5, (0.4, 0.82, 0.2, 0.03)),
            ocr("좌측에 표시되는 내 선발 투수의 순서를 변경할 수 있습니다.", 1.0, (0.289, 0.789, 0.435, 0.016)),
            ocr("원래대로", 1.0, (0.245, 0.056, 0.080, 0.019)),
            ocr("저장", 0.5, (0.696, 0.056, 0.042, 0.019)),
            ocr("1선발 R", 1.0, (0.222, 0.737, 0.050, 0.012)),
            ocr("1선발 R", 1.0, (0.222, 0.609, 0.050, 0.012)),
            ocr("3선발 L", 0.6, (0.222, 0.218, 0.050, 0.013)),
        )

        self.assertEqual(recognize_screen(rows).status, ClassificationStatus.CANDIDATE)


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

    def test_user_input_pauses_with_checkpoint_and_resume_rechecks_current_screen(self):
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        frame = verified(ScreenState.PITCHER_ORDER)
        transition = self.transitions[1]

        self.assertFalse(safety.before_action(frame=frame, transition=transition, depth=0, step_index=4,
                                              user_idle=False))
        self.assertEqual(safety.status, SessionStatus.PAUSED)
        self.assertEqual(safety.checkpoint.screen_state, ScreenState.PITCHER_ORDER)
        self.assertEqual(safety.checkpoint.step_index, 4)
        with self.assertRaisesRegex(RuntimeError, "fresh verified"):
            safety.resume(explicitly_requested=True)
        safety.resume(explicitly_requested=True, observed_frame=frame)
        self.assertEqual(safety.status, SessionStatus.COLLECTING)

    def test_game_focus_loss_pauses_without_stealing_focus_and_emergency_stops(self):
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        frame = verified(ScreenState.PITCHER_ORDER)
        transition = self.transitions[1]

        self.assertFalse(safety.before_action(frame=frame, transition=transition, depth=0, step_index=2,
                                              game_focused=False))
        self.assertEqual(safety.status, SessionStatus.PAUSED)
        self.assertEqual(safety.halt_reason, "game window focus lost")
        safety.resume(explicitly_requested=True, observed_frame=frame)
        self.assertFalse(safety.before_action(frame=frame, transition=transition, depth=0, step_index=2,
                                              emergency_stop_requested=True))
        self.assertEqual(safety.status, SessionStatus.HALTED)
        self.assertEqual(safety.checkpoint.reason, "emergency stop")

    def test_only_allowlisted_navigation_intents_are_accepted(self):
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        unsafe = Transition(ScreenState.RANKING_LOBBY, "START_MATCH", ScreenState.PITCHER_ORDER)  # type: ignore[arg-type]
        self.assertFalse(safety.before_action(frame=verified(ScreenState.RANKING_LOBBY), transition=unsafe,
                                             depth=0, step_index=0))
        self.assertEqual(safety.status, SessionStatus.HALTED)

    def test_same_detail_screen_can_visit_batters_one_through_nine(self):
        players = [f"synthetic:batter-{slot}" for slot in range(1, 10)]
        goal_name = "scan-samsung-batters"
        transitions = tuple(
            Transition(ScreenState.PLAYER_DETAIL_BATTER, UIAction.NEXT_PLAYER,
                       ScreenState.PLAYER_DETAIL_BATTER, source_player_key=players[index], source_page=1,
                       target_player_key=players[index + 1], target_page=1, navigation_goal=goal_name)
            for index in range(8)
        )
        planner = NavigationPlanner(transitions)
        start = verified(ScreenState.PLAYER_DETAIL_BATTER, player=players[0], page=1, panel=PanelRole.ACTIVE)
        goal = NavigationVisitKey(ScreenState.PLAYER_DETAIL_BATTER, players[-1], 1, goal_name)
        adapter = MockUIActionAdapter({
            (ScreenState.PLAYER_DETAIL_BATTER, players[index], 1, UIAction.NEXT_PLAYER):
                verified(ScreenState.PLAYER_DETAIL_BATTER, player=players[index + 1], page=1,
                         panel=PanelRole.ACTIVE)
            for index in range(8)
        })
        safety = SafetyController(max_depth=9)

        result = SimulatedNavigator(planner).run(start_frame=start, goal=goal, adapter=adapter,
                                                 safety=safety, explicitly_requested=True)

        self.assertEqual(result.status, SessionStatus.COMPLETE)
        self.assertEqual(result.route.states, (ScreenState.PLAYER_DETAIL_BATTER,) * 9)
        self.assertEqual(len(safety._visited), 9)
        self.assertEqual(len(adapter.actions), 8)

    def test_pitcher_collection_plan_visits_five_players_and_pages_one_to_three(self):
        players = [f"synthetic:pitcher-{slot}" for slot in range(1, 6)]
        goal_name = "collect-five-starters"
        transitions = []
        adapter_transitions = {}
        for player_index, player in enumerate(players):
            for page in (1, 2):
                action = UIAction.NEXT_PAGE
                source = verified(ScreenState.PLAYER_DETAIL_PITCHER, player=player, page=page,
                                  panel=PanelRole.ACTIVE)
                target = verified(ScreenState.PLAYER_DETAIL_PITCHER, player=player, page=page + 1,
                                  panel=PanelRole.ACTIVE)
                transitions.append(Transition(ScreenState.PLAYER_DETAIL_PITCHER, action,
                                              ScreenState.PLAYER_DETAIL_PITCHER,
                                              source_player_key=player, source_page=page,
                                              target_player_key=player, target_page=page + 1,
                                              navigation_goal=goal_name))
                adapter_transitions[(ScreenState.PLAYER_DETAIL_PITCHER, player, page, action)] = target
            if player_index < len(players) - 1:
                next_player = players[player_index + 1]
                action = UIAction.NEXT_PLAYER
                transitions.append(Transition(ScreenState.PLAYER_DETAIL_PITCHER, action,
                                              ScreenState.PLAYER_DETAIL_PITCHER,
                                              source_player_key=player, source_page=3,
                                              target_player_key=next_player, target_page=1,
                                              navigation_goal=goal_name))
                adapter_transitions[(ScreenState.PLAYER_DETAIL_PITCHER, player, 3, action)] = verified(
                    ScreenState.PLAYER_DETAIL_PITCHER, player=next_player, page=1,
                    panel=PanelRole.ACTIVE)

        start = verified(ScreenState.PLAYER_DETAIL_PITCHER, player=players[0], page=1,
                          panel=PanelRole.ACTIVE)
        goal = NavigationVisitKey(ScreenState.PLAYER_DETAIL_PITCHER, players[-1], 3, goal_name)
        adapter = MockUIActionAdapter(adapter_transitions)
        result = SimulatedNavigator(NavigationPlanner(transitions)).run(
            start_frame=start, goal=goal, adapter=adapter,
            safety=SafetyController(max_depth=20), explicitly_requested=True,
        )

        self.assertEqual(result.status, SessionStatus.COMPLETE)
        self.assertEqual(len(adapter.actions), 14)
        self.assertEqual(len({key.player_key for key in result.route.visits if key.player_key}), 5)
        self.assertEqual([key.page for key in result.route.visits if key.page],
                         [1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3])

    def test_one_pitcher_then_nine_batters_are_distinct_verified_visits(self):
        pitcher = "synthetic:pitcher-1"
        batters = [f"synthetic:batter-{slot}" for slot in range(1, 10)]
        goal_name = "scan-samsung-lineup"
        transitions = [
            Transition(ScreenState.PLAYER_DETAIL_PITCHER, UIAction.BACK, ScreenState.OPPONENT_LINEUP,
                       source_player_key=pitcher, source_page=1, navigation_goal=goal_name),
            Transition(ScreenState.OPPONENT_LINEUP, UIAction.OPEN_BATTER_DETAIL, ScreenState.PLAYER_DETAIL_BATTER,
                       target_player_key=batters[0], target_page=1, navigation_goal=goal_name),
        ]
        transitions.extend(
            Transition(ScreenState.PLAYER_DETAIL_BATTER, UIAction.NEXT_PLAYER, ScreenState.PLAYER_DETAIL_BATTER,
                       source_player_key=batters[index], source_page=1, target_player_key=batters[index + 1],
                       target_page=1, navigation_goal=goal_name)
            for index in range(8)
        )
        start = verified(ScreenState.PLAYER_DETAIL_PITCHER, player=pitcher, page=1, panel=PanelRole.ACTIVE)
        adapter_transitions = {
            (ScreenState.PLAYER_DETAIL_PITCHER, pitcher, 1, UIAction.BACK): verified(ScreenState.OPPONENT_LINEUP),
            (ScreenState.OPPONENT_LINEUP, None, None, UIAction.OPEN_BATTER_DETAIL):
                verified(ScreenState.PLAYER_DETAIL_BATTER, player=batters[0], page=1, panel=PanelRole.ACTIVE),
        }
        adapter_transitions.update({
            (ScreenState.PLAYER_DETAIL_BATTER, batters[index], 1, UIAction.NEXT_PLAYER):
                verified(ScreenState.PLAYER_DETAIL_BATTER, player=batters[index + 1], page=1,
                         panel=PanelRole.ACTIVE)
            for index in range(8)
        })
        safety = SafetyController(max_depth=12)
        result = SimulatedNavigator(NavigationPlanner(transitions)).run(
            start_frame=start,
            goal=NavigationVisitKey(ScreenState.PLAYER_DETAIL_BATTER, batters[-1], 1, goal_name),
            adapter=MockUIActionAdapter(adapter_transitions), safety=safety, explicitly_requested=True,
        )
        self.assertEqual(result.status, SessionStatus.COMPLETE)
        self.assertEqual(result.route.states.count(ScreenState.PLAYER_DETAIL_PITCHER), 1)
        self.assertEqual(result.route.states.count(ScreenState.PLAYER_DETAIL_BATTER), 9)

    def test_page_return_is_a_new_navigation_goal_but_does_not_duplicate_collection(self):
        frame_page_one = verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:b1", page=1,
                                   panel=PanelRole.ACTIVE)
        frame_page_two = verified(ScreenState.PLAYER_DETAIL_BATTER, player="synthetic:b1", page=2,
                                   panel=PanelRole.ACTIVE)
        safety = SafetyController()
        safety.start(explicitly_requested=True)
        safety.begin_goal("collect-page-one")
        self.assertTrue(safety.record_visit(frame_page_one))
        self.assertFalse(safety.record_visit(frame_page_one))
        self.assertTrue(safety.record_visit(frame_page_two))
        self.assertTrue(safety.record_collection(frame_page_one))
        self.assertFalse(safety.record_collection(frame_page_one))
        self.assertTrue(safety.record_visit(frame_page_one, goal="return-to-page-one"))
        self.assertFalse(safety.record_collection(frame_page_one))

    def test_expected_player_mismatch_halts_before_a_candidate_can_be_reused(self):
        p1, p2, p3 = "synthetic:b1", "synthetic:b2", "synthetic:b3"
        transition = Transition(ScreenState.PLAYER_DETAIL_BATTER, UIAction.NEXT_PLAYER,
                                ScreenState.PLAYER_DETAIL_BATTER, source_player_key=p1, source_page=1,
                                target_player_key=p2, target_page=1)
        start = verified(ScreenState.PLAYER_DETAIL_BATTER, player=p1, page=1, panel=PanelRole.ACTIVE)
        wrong = verified(ScreenState.PLAYER_DETAIL_BATTER, player=p3, page=1, panel=PanelRole.ACTIVE)
        result = SimulatedNavigator(NavigationPlanner((transition,))).run(
            start_frame=start, goal=NavigationVisitKey(ScreenState.PLAYER_DETAIL_BATTER, p2, 1,
                                                       ScreenState.PLAYER_DETAIL_BATTER.value),
            adapter=MockUIActionAdapter({(ScreenState.PLAYER_DETAIL_BATTER, p1, 1, UIAction.NEXT_PLAYER): wrong}),
            safety=SafetyController(max_depth=2), explicitly_requested=True,
        )
        self.assertEqual(result.status, SessionStatus.HALTED)
        self.assertIn("expected player", result.halt_reason)


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


class SafeInputTargetTests(unittest.TestCase):
    def test_measured_first_card_is_safe_only_with_verified_screen_and_player_identity(self):
        target = LocalizedActionTarget(
            SafeTargetKind.FIRST_STARTER_CARD, UIAction.OPEN_STARTER_DETAIL,
            ScreenState.PITCHER_ORDER, FIRST_STARTER_CARD_BOUNDS,
            PITCHER_ORDER_LAYOUT_VERSION, "후라도'26", "a" * 64, 0.99,
        )
        classification = ScreenClassification(ScreenState.PITCHER_ORDER, ClassificationStatus.VERIFIED,
                                              1.0, tuple(range(8)))

        self.assertFalse(target.authorize(classification, identity_confidence=0.5)[0])
        self.assertTrue(target.authorize(classification, identity_confidence=0.95)[0])
        candidate = ScreenClassification(ScreenState.PITCHER_ORDER, ClassificationStatus.CANDIDATE,
                                          0.5, (0, 1, 2, 3))
        self.assertFalse(target.authorize(candidate, identity_confidence=0.99)[0])

    def test_mutating_actions_wrong_regions_and_unknown_profiles_are_rejected(self):
        classification = ScreenClassification(ScreenState.PITCHER_ORDER, ClassificationStatus.VERIFIED,
                                              1.0, tuple(range(8)))
        baseline = LocalizedActionTarget(
            SafeTargetKind.FIRST_STARTER_CARD, UIAction.OPEN_STARTER_DETAIL,
            ScreenState.PITCHER_ORDER, FIRST_STARTER_CARD_BOUNDS,
            PITCHER_ORDER_LAYOUT_VERSION, "후라도'26", "b" * 64, 0.99,
        )
        unsafe_action = LocalizedActionTarget(
            SafeTargetKind.FIRST_STARTER_CARD, AccountStateChangingAction.SAVE_STARTER_ORDER,  # type: ignore[arg-type]
            ScreenState.PITCHER_ORDER, FIRST_STARTER_CARD_BOUNDS,
            PITCHER_ORDER_LAYOUT_VERSION, "후라도'26", "b" * 64, 0.99,
        )
        wrong_bounds = LocalizedActionTarget(
            SafeTargetKind.FIRST_STARTER_CARD, UIAction.OPEN_STARTER_DETAIL,
            ScreenState.PITCHER_ORDER, NormalizedRect(0.495, 0.03, 0.20, 0.06),
            PITCHER_ORDER_LAYOUT_VERSION, "후라도'26", "b" * 64, 0.99,
        )
        wrong_profile = LocalizedActionTarget(
            SafeTargetKind.FIRST_STARTER_CARD, UIAction.OPEN_STARTER_DETAIL,
            ScreenState.PITCHER_ORDER, FIRST_STARTER_CARD_BOUNDS,
            "old-profile", "후라도'26", "b" * 64, 0.99,
        )

        self.assertFalse(unsafe_action.authorize(classification, identity_confidence=0.99)[0])
        self.assertFalse(wrong_bounds.authorize(classification, identity_confidence=0.99)[0])
        self.assertFalse(wrong_profile.authorize(classification, identity_confidence=0.99)[0])
        self.assertEqual(len(AccountStateChangingAction), 12)


if __name__ == "__main__":
    unittest.main()
