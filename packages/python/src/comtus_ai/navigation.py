from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
import math
from typing import Mapping, Protocol, Sequence

from .screens import ClassificationStatus, PanelRole, ScreenState


DETAIL_STATES = frozenset({
    ScreenState.OPPONENT_STARTING_PITCHER_DETAIL,
    ScreenState.PLAYER_DETAIL_BATTER,
    ScreenState.PLAYER_DETAIL_PITCHER,
})


class UIAction(StrEnum):
    BACK = "BACK"
    OPEN_PITCHER_ORDER = "OPEN_PITCHER_ORDER"
    OPEN_OPPONENT_LINEUP = "OPEN_OPPONENT_LINEUP"
    OPEN_STARTER_DETAIL = "OPEN_STARTER_DETAIL"
    OPEN_BATTER_DETAIL = "OPEN_BATTER_DETAIL"
    OPEN_TEAM_ROSTER = "OPEN_TEAM_ROSTER"
    OPEN_SYNERGY = "OPEN_SYNERGY"
    OPEN_POSITION_TRAINING = "OPEN_POSITION_TRAINING"
    NEXT_PLAYER = "NEXT_PLAYER"
    PREVIOUS_PLAYER = "PREVIOUS_PLAYER"
    NEXT_PAGE = "NEXT_PAGE"
    PREVIOUS_PAGE = "PREVIOUS_PAGE"


class SessionStatus(StrEnum):
    STOPPED = "STOPPED"
    COLLECTING = "COLLECTING"
    PAUSED = "PAUSED"
    HALTED = "HALTED"
    COMPLETE = "COMPLETE"


@dataclass(frozen=True, slots=True)
class ScreenFrame:
    state: ScreenState
    status: ClassificationStatus
    player_key: str | None = None
    player_verified: bool = False
    page: int | None = None
    page_verified: bool = False
    panel_role: PanelRole = PanelRole.UNKNOWN


@dataclass(frozen=True, slots=True)
class NavigationVisitKey:
    state: ScreenState
    player_key: str | None
    page: int | None
    goal: str

    @classmethod
    def from_frame(cls, frame: ScreenFrame, goal: str) -> NavigationVisitKey:
        player = frame.player_key if frame.player_verified else None
        page = frame.page if frame.page_verified else None
        return cls(frame.state, player, page, goal)


@dataclass(frozen=True, slots=True)
class CollectionKey:
    state: ScreenState
    player_key: str
    page: int


@dataclass(frozen=True, slots=True)
class Transition:
    source: ScreenState
    action: UIAction
    target: ScreenState
    source_player_key: str | None = None
    source_page: int | None = None
    target_player_key: str | None = None
    target_page: int | None = None
    navigation_goal: str | None = None


@dataclass(frozen=True, slots=True)
class NavigationRoute:
    states: tuple[ScreenState, ...]
    transitions: tuple[Transition, ...]
    visits: tuple[NavigationVisitKey, ...] = ()


class NavigationPlanner:
    """Plans only over a caller-supplied, evidence-backed transition graph."""

    def __init__(self, transitions: Sequence[Transition]):
        self.transitions = tuple(transitions)

    def plan(self, start: ScreenState | NavigationVisitKey, goal: ScreenState | NavigationVisitKey,
             *, max_depth: int = 8, navigation_goal: str | None = None) -> NavigationRoute | None:
        goal_key = goal if isinstance(goal, NavigationVisitKey) else NavigationVisitKey(
            goal, None, None, navigation_goal or goal.value)
        goal_name = goal_key.goal
        start_key = start if isinstance(start, NavigationVisitKey) else NavigationVisitKey(
            start, None, None, goal_name)
        if start_key.state == goal_key.state and self._matches_goal(start_key, goal_key):
            return NavigationRoute((start_key.state,), (), (start_key,))
        queue = deque([(start_key, (start_key,), ())])
        visited = {start_key}
        while queue:
            visit, visits, route = queue.popleft()
            if len(route) >= max_depth:
                continue
            for transition in self.transitions:
                if (transition.source != visit.state
                        or (transition.source_player_key is not None and transition.source_player_key != visit.player_key)
                        or (transition.source_page is not None and transition.source_page != visit.page)):
                    continue
                next_visit = NavigationVisitKey(
                    transition.target,
                    transition.target_player_key,
                    transition.target_page,
                    transition.navigation_goal or goal_name,
                )
                if next_visit in visited:
                    continue
                next_visits = (*visits, next_visit)
                next_route = (*route, transition)
                if self._matches_goal(next_visit, goal_key):
                    return NavigationRoute(tuple(item.state for item in next_visits), next_route, next_visits)
                visited.add(next_visit)
                queue.append((next_visit, next_visits, next_route))
        return None

    @staticmethod
    def _matches_goal(current: NavigationVisitKey, goal: NavigationVisitKey) -> bool:
        return (current.state == goal.state
                and (goal.player_key is None or current.player_key == goal.player_key)
                and (goal.page is None or current.page == goal.page)
                and current.goal == goal.goal)

    def recovery_plan(self, current: ScreenState, previous_verified: ScreenState, *, max_depth: int = 8) -> NavigationRoute | None:
        return self.plan(current, previous_verified, max_depth=max_depth)


@dataclass(frozen=True, slots=True)
class TrackerUpdate:
    accepted: bool
    reason: str
    player_changed: bool = False
    page_changed: bool = False
    fields_invalidated: bool = False


@dataclass(slots=True)
class PlayerPageTracker:
    screen_state: ScreenState = ScreenState.UNKNOWN
    screen_status: ClassificationStatus = ClassificationStatus.UNKNOWN
    player_key: str | None = None
    page: int | None = None
    player_epoch: int = 0
    page_epoch: int = 0
    panel_role: PanelRole = PanelRole.UNKNOWN
    pending_fields: list[object] = field(default_factory=list)

    def observe(self, frame: ScreenFrame, *, expected_action: UIAction | None = None) -> TrackerUpdate:
        self.pending_fields.clear()
        if frame.status != ClassificationStatus.VERIFIED or frame.state == ScreenState.UNKNOWN:
            self._clear_identity()
            self.screen_state, self.screen_status = frame.state, frame.status
            return TrackerUpdate(False, "screen is not verified", fields_invalidated=True)

        old_player, old_page = self.player_key, self.page
        player_changed = frame.player_key != old_player and frame.player_key is not None
        page_changed = frame.page != old_page and frame.page is not None
        if frame.state in DETAIL_STATES:
            if not frame.player_verified or not frame.player_key:
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "player identity is not verified", fields_invalidated=True)
            if not frame.page_verified or frame.page not in (1, 2, 3):
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "detail page is not verified", fields_invalidated=True)
            if old_player is not None and player_changed and expected_action not in (UIAction.NEXT_PLAYER, UIAction.PREVIOUS_PLAYER):
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "player changed without a tracked player transition", True, page_changed, True)
            if old_player == frame.player_key and page_changed and expected_action not in (UIAction.NEXT_PAGE, UIAction.PREVIOUS_PAGE):
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "page changed without a tracked page transition", False, True, True)
            if expected_action in (UIAction.NEXT_PLAYER, UIAction.PREVIOUS_PLAYER) and not player_changed:
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "expected player transition was not observed", False, page_changed, True)
            if expected_action in (UIAction.NEXT_PAGE, UIAction.PREVIOUS_PAGE) and not page_changed:
                self._clear_identity()
                self.screen_state, self.screen_status = frame.state, frame.status
                return TrackerUpdate(False, "expected page transition was not observed", False, False, True)
            if player_changed:
                self.player_epoch += 1
            if page_changed or player_changed:
                self.page_epoch += 1
            self.player_key, self.page = frame.player_key, frame.page
        else:
            self._clear_identity()

        self.screen_state = frame.state
        self.screen_status = frame.status
        self.panel_role = frame.panel_role
        return TrackerUpdate(True, "frame context verified", player_changed, page_changed, False)

    @property
    def can_commit_player_fields(self) -> bool:
        return (self.screen_status == ClassificationStatus.VERIFIED
                and self.screen_state in DETAIL_STATES
                and self.player_key is not None and self.page in (1, 2, 3)
                and self.panel_role == PanelRole.ACTIVE)

    def stage_field(self, value: object) -> bool:
        if not self.can_commit_player_fields:
            return False
        self.pending_fields.append(value)
        return True

    def take_fields(self) -> tuple[object, ...]:
        if not self.can_commit_player_fields:
            self.pending_fields.clear()
            return ()
        values = tuple(self.pending_fields)
        self.pending_fields.clear()
        return values

    def _clear_identity(self) -> None:
        self.player_key = None
        self.page = None
        self.panel_role = PanelRole.UNKNOWN
        self.pending_fields.clear()


class TransientActionError(RuntimeError):
    pass


class UIActionAdapter(Protocol):
    def perform(self, frame: ScreenFrame, action: UIAction) -> ScreenFrame:
        """Return a new observed state. Implementations must not infer one."""


@dataclass(slots=True)
class MockUIActionAdapter:
    transitions: Mapping[tuple[object, ...], ScreenFrame]
    transient_failures: dict[tuple[ScreenState, UIAction], int] = field(default_factory=dict)
    actions: list[tuple[ScreenState, UIAction]] = field(default_factory=list)

    def perform(self, frame: ScreenFrame | ScreenState, action: UIAction) -> ScreenFrame:
        if isinstance(frame, ScreenState):
            frame = ScreenFrame(frame, ClassificationStatus.VERIFIED)
        key = (frame.state, action)
        identity_keys = (
            (frame.state, frame.player_key, frame.page, action),
            (frame.state, frame.player_key, action),
            key,
        )
        self.actions.append(key)
        failures_left = self.transient_failures.get(key, 0)
        if failures_left:
            self.transient_failures[key] = failures_left - 1
            raise TransientActionError("synthetic adapter did not observe a transition")
        for identity_key in identity_keys:
            if identity_key in self.transitions:
                return self.transitions[identity_key]
        raise TransientActionError("no simulated transition is configured")


@dataclass(slots=True)
class SafetyController:
    max_depth: int = 8
    max_retries: int = 1
    status: SessionStatus = SessionStatus.STOPPED
    halt_reason: str | None = None
    _attempts: dict[int, int] = field(default_factory=dict)
    navigation_goal: str | None = None
    _visited: set[NavigationVisitKey] = field(default_factory=set)
    _collected: set[CollectionKey] = field(default_factory=set)

    def __post_init__(self) -> None:
        if self.max_depth < 1 or self.max_retries < 0:
            raise ValueError("max_depth must be positive and max_retries non-negative")

    def start(self, *, explicitly_requested: bool) -> None:
        if not explicitly_requested:
            raise ValueError("collection requires an explicit user start request")
        if self.status not in (SessionStatus.STOPPED, SessionStatus.PAUSED):
            raise RuntimeError(f"cannot start a session in state {self.status}")
        self.status = SessionStatus.COLLECTING
        self.halt_reason = None

    def begin_goal(self, goal: str) -> None:
        if self.status != SessionStatus.COLLECTING:
            raise RuntimeError("a navigation goal can be set only for an active session")
        if not goal.strip():
            raise ValueError("navigation goal must not be empty")
        self.navigation_goal = goal

    def record_visit(self, frame: ScreenFrame, *, goal: str | None = None) -> bool:
        key = NavigationVisitKey.from_frame(frame, goal or self.navigation_goal or frame.state.value)
        if key in self._visited:
            return False
        self._visited.add(key)
        return True

    def record_collection(self, frame: ScreenFrame) -> bool:
        """Idempotently mark verified player/page data as collected, independent of visit goal."""
        if (frame.state not in DETAIL_STATES or frame.status != ClassificationStatus.VERIFIED
                or not frame.player_verified or not frame.player_key or not frame.page_verified
                or frame.page not in (1, 2, 3) or frame.panel_role != PanelRole.ACTIVE):
            return False
        key = CollectionKey(frame.state, frame.player_key, frame.page)
        if key in self._collected:
            return False
        self._collected.add(key)
        return True

    def pause_for_user_input(self) -> None:
        if self.status == SessionStatus.COLLECTING:
            self.status = SessionStatus.PAUSED

    def resume(self, *, explicitly_requested: bool) -> None:
        if self.status != SessionStatus.PAUSED or not explicitly_requested:
            raise RuntimeError("resume requires a paused session and explicit user request")
        self.status = SessionStatus.COLLECTING

    def emergency_stop(self) -> None:
        self.status = SessionStatus.HALTED
        self.halt_reason = "emergency stop"

    def before_action(self, *, frame: ScreenFrame, transition: Transition, depth: int, step_index: int) -> bool:
        if self.status in (SessionStatus.PAUSED, SessionStatus.HALTED, SessionStatus.STOPPED, SessionStatus.COMPLETE):
            return False
        if self.status != SessionStatus.COLLECTING:
            return self._halt("collection is not active")
        if depth >= self.max_depth:
            return self._halt("maximum exploration depth reached")
        if frame.status != ClassificationStatus.VERIFIED or frame.state != transition.source:
            return self._halt("current screen does not match the expected verified screen")
        if transition.source_player_key is not None and frame.player_key != transition.source_player_key:
            return self._halt("current player does not match the expected transition source")
        if transition.source_page is not None and frame.page != transition.source_page:
            return self._halt("current page does not match the expected transition source")
        if frame.state in DETAIL_STATES and (not frame.player_verified or not frame.player_key
                                             or not frame.page_verified or frame.page not in (1, 2, 3)):
            return self._halt("detail navigation requires verified player and page identity")
        if not isinstance(transition.action, UIAction):
            return self._halt("action is outside the safe navigation allowlist")
        expected = self._expected_visit(transition)
        if expected is not None and expected in self._visited:
            return self._halt("duplicate player/page visit blocked")
        attempts = self._attempts.get(step_index, 0)
        if attempts > self.max_retries:
            return self._halt("maximum retry count reached")
        self._attempts[step_index] = attempts + 1
        return True

    def after_action(self, *, frame: ScreenFrame, transition: Transition,
                     previous_frame: ScreenFrame | None = None) -> bool:
        if self.status == SessionStatus.PAUSED:
            return False
        if self.status == SessionStatus.HALTED:
            return False
        if self.status != SessionStatus.COLLECTING:
            return self._halt("collection stopped during action")
        if frame.status != ClassificationStatus.VERIFIED or frame.state != transition.target:
            return self._halt("post-action screen did not match the verified target")
        if transition.target_player_key is not None and frame.player_key != transition.target_player_key:
            return self._halt("post-action player did not match the expected player")
        if transition.target_page is not None and frame.page != transition.target_page:
            return self._halt("post-action page did not match the expected page")
        if frame.state in DETAIL_STATES and (not frame.player_verified or not frame.player_key
                                             or not frame.page_verified or frame.page not in (1, 2, 3)):
            return self._halt("post-action detail identity is not verified")
        if previous_frame is not None and previous_frame.state == frame.state and frame.state in DETAIL_STATES:
            if transition.action in (UIAction.NEXT_PLAYER, UIAction.PREVIOUS_PLAYER):
                if frame.player_key == previous_frame.player_key:
                    return self._halt("player transition did not change the verified player")
            if transition.action in (UIAction.NEXT_PAGE, UIAction.PREVIOUS_PAGE):
                if frame.player_key != previous_frame.player_key or frame.page == previous_frame.page:
                    return self._halt("page transition changed the player or did not change the page")
        goal = transition.navigation_goal or self.navigation_goal or transition.target.value
        key = NavigationVisitKey.from_frame(frame, goal)
        if key in self._visited:
            return self._halt("duplicate player/page visit blocked")
        self._visited.add(key)
        return True

    def _expected_visit(self, transition: Transition) -> NavigationVisitKey | None:
        if transition.target_player_key is None and transition.target_page is None:
            return None
        return NavigationVisitKey(
            transition.target, transition.target_player_key, transition.target_page,
            transition.navigation_goal or self.navigation_goal or transition.target.value,
        )

    def action_failed(self, step_index: int) -> bool:
        if self._attempts.get(step_index, 0) > self.max_retries:
            return self._halt("maximum retry count reached")
        return self.status == SessionStatus.COLLECTING

    def complete(self) -> None:
        if self.status == SessionStatus.COLLECTING:
            self.status = SessionStatus.COMPLETE

    def _halt(self, reason: str) -> bool:
        self.status = SessionStatus.HALTED
        self.halt_reason = reason
        return False


@dataclass(frozen=True, slots=True)
class NavigationResult:
    status: SessionStatus
    final_frame: ScreenFrame
    route: NavigationRoute | None
    halt_reason: str | None = None
    recovery_plan: NavigationRoute | None = None


class SimulatedNavigator:
    def __init__(self, planner: NavigationPlanner):
        self.planner = planner

    def run(self, *, start_frame: ScreenFrame, goal: ScreenState | NavigationVisitKey, adapter: UIActionAdapter,
            safety: SafetyController, explicitly_requested: bool) -> NavigationResult:
        safety.start(explicitly_requested=explicitly_requested)
        if start_frame.status != ClassificationStatus.VERIFIED or start_frame.state == ScreenState.UNKNOWN:
            safety._halt("starting screen is not verified")
            return NavigationResult(safety.status, start_frame, None, safety.halt_reason)
        goal_name = goal.goal if isinstance(goal, NavigationVisitKey) else goal.value
        safety.begin_goal(goal_name)
        if start_frame.state in DETAIL_STATES and (not start_frame.player_verified or not start_frame.player_key
                                                   or not start_frame.page_verified or start_frame.page not in (1, 2, 3)):
            safety._halt("starting detail identity is not verified")
            return NavigationResult(safety.status, start_frame, None, safety.halt_reason)
        start_key = NavigationVisitKey.from_frame(start_frame, goal_name)
        route = self.planner.plan(start_key, goal, max_depth=safety.max_depth)
        if route is None:
            safety._halt("no safe route to the requested target")
            return NavigationResult(safety.status, start_frame, None, safety.halt_reason)
        safety.record_visit(start_frame, goal=goal_name)
        frame = start_frame
        for index, transition in enumerate(route.transitions):
            attempts = 0
            while True:
                if not safety.before_action(frame=frame, transition=transition, depth=index, step_index=index):
                    recovery = self.planner.recovery_plan(frame.state, start_frame.state, max_depth=safety.max_depth)
                    return NavigationResult(safety.status, frame, route, safety.halt_reason, recovery)
                attempts += 1
                try:
                    next_frame = adapter.perform(frame, transition.action)
                except TransientActionError:
                    if safety.action_failed(index) and attempts <= safety.max_retries:
                        continue
                    safety._halt("adapter retry limit reached")
                    recovery = self.planner.recovery_plan(frame.state, start_frame.state, max_depth=safety.max_depth)
                    return NavigationResult(safety.status, frame, route, safety.halt_reason, recovery)
                if not safety.after_action(frame=next_frame, transition=transition, previous_frame=frame):
                    recovery = self.planner.recovery_plan(next_frame.state, frame.state, max_depth=safety.max_depth)
                    return NavigationResult(safety.status, next_frame, route, safety.halt_reason, recovery)
                frame = next_frame
                break
        safety.complete()
        return NavigationResult(safety.status, frame, route)


class CoordinateOrigin(StrEnum):
    TOP_LEFT = "TOP_LEFT"
    BOTTOM_LEFT = "BOTTOM_LEFT"


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    origin_x_points: float
    origin_y_points: float
    width_points: float
    height_points: float

    def __post_init__(self) -> None:
        if (not all(math.isfinite(value) for value in
                    (self.origin_x_points, self.origin_y_points, self.width_points, self.height_points))
                or self.width_points <= 0 or self.height_points <= 0):
            raise ValueError("window dimensions must be positive")

    def map_vision_bbox(self, bbox: Sequence[float], *, origin: CoordinateOrigin) -> tuple[float, float]:
        if (len(bbox) != 4 or any(not math.isfinite(item) or not 0 <= item <= 1 for item in bbox)
                or bbox[0] + bbox[2] > 1.000001 or bbox[1] + bbox[3] > 1.000001):
            raise ValueError("Vision bounds must be a normalized rectangle")
        center_x = bbox[0] + bbox[2] / 2
        center_y = bbox[1] + bbox[3] / 2
        local_y = (1 - center_y) * self.height_points if origin == CoordinateOrigin.TOP_LEFT else center_y * self.height_points
        return self.origin_x_points + center_x * self.width_points, self.origin_y_points + local_y
