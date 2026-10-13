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
class Transition:
    source: ScreenState
    action: UIAction
    target: ScreenState


@dataclass(frozen=True, slots=True)
class NavigationRoute:
    states: tuple[ScreenState, ...]
    transitions: tuple[Transition, ...]


class NavigationPlanner:
    """Plans only over a caller-supplied, evidence-backed transition graph."""

    def __init__(self, transitions: Sequence[Transition]):
        self.transitions = tuple(transitions)

    def plan(self, start: ScreenState, goal: ScreenState, *, max_depth: int = 8) -> NavigationRoute | None:
        if start == goal:
            return NavigationRoute((start,), ())
        queue = deque([(start, (start,), ())])
        visited = {start}
        while queue:
            state, states, route = queue.popleft()
            if len(route) >= max_depth:
                continue
            for transition in self.transitions:
                if transition.source != state or transition.target in visited:
                    continue
                next_states = (*states, transition.target)
                next_route = (*route, transition)
                if transition.target == goal:
                    return NavigationRoute(next_states, next_route)
                visited.add(transition.target)
                queue.append((transition.target, next_states, next_route))
        return None

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
    def perform(self, state: ScreenState, action: UIAction) -> ScreenFrame:
        """Return a new observed state. Implementations must not infer one."""


@dataclass(slots=True)
class MockUIActionAdapter:
    transitions: Mapping[tuple[ScreenState, UIAction], ScreenFrame]
    transient_failures: dict[tuple[ScreenState, UIAction], int] = field(default_factory=dict)
    actions: list[tuple[ScreenState, UIAction]] = field(default_factory=list)

    def perform(self, state: ScreenState, action: UIAction) -> ScreenFrame:
        key = (state, action)
        self.actions.append(key)
        failures_left = self.transient_failures.get(key, 0)
        if failures_left:
            self.transient_failures[key] = failures_left - 1
            raise TransientActionError("synthetic adapter did not observe a transition")
        try:
            return self.transitions[key]
        except KeyError as error:
            raise TransientActionError("no simulated transition is configured") from error


@dataclass(slots=True)
class SafetyController:
    max_depth: int = 8
    max_retries: int = 1
    status: SessionStatus = SessionStatus.STOPPED
    halt_reason: str | None = None
    _attempts: dict[int, int] = field(default_factory=dict)
    _visited: set[ScreenState] = field(default_factory=set)

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
        if not isinstance(transition.action, UIAction):
            return self._halt("action is outside the safe navigation allowlist")
        if transition.target in self._visited:
            return self._halt("duplicate screen visit blocked")
        attempts = self._attempts.get(step_index, 0)
        if attempts > self.max_retries:
            return self._halt("maximum retry count reached")
        self._attempts[step_index] = attempts + 1
        return True

    def after_action(self, *, frame: ScreenFrame, transition: Transition) -> bool:
        if self.status == SessionStatus.PAUSED:
            return False
        if self.status == SessionStatus.HALTED:
            return False
        if self.status != SessionStatus.COLLECTING:
            return self._halt("collection stopped during action")
        if frame.status != ClassificationStatus.VERIFIED or frame.state != transition.target:
            return self._halt("post-action screen did not match the verified target")
        self._visited.add(frame.state)
        return True

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

    def run(self, *, start_frame: ScreenFrame, goal: ScreenState, adapter: UIActionAdapter,
            safety: SafetyController, explicitly_requested: bool) -> NavigationResult:
        safety.start(explicitly_requested=explicitly_requested)
        if start_frame.status != ClassificationStatus.VERIFIED or start_frame.state == ScreenState.UNKNOWN:
            safety._halt("starting screen is not verified")
            return NavigationResult(safety.status, start_frame, None, safety.halt_reason)
        route = self.planner.plan(start_frame.state, goal, max_depth=safety.max_depth)
        if route is None:
            safety._halt("no safe route to the requested target")
            return NavigationResult(safety.status, start_frame, None, safety.halt_reason)
        safety._visited.add(start_frame.state)
        frame = start_frame
        for index, transition in enumerate(route.transitions):
            attempts = 0
            while True:
                if not safety.before_action(frame=frame, transition=transition, depth=index, step_index=index):
                    recovery = self.planner.recovery_plan(frame.state, start_frame.state, max_depth=safety.max_depth)
                    return NavigationResult(safety.status, frame, route, safety.halt_reason, recovery)
                attempts += 1
                try:
                    next_frame = adapter.perform(frame.state, transition.action)
                except TransientActionError:
                    if safety.action_failed(index) and attempts <= safety.max_retries:
                        continue
                    safety._halt("adapter retry limit reached")
                    recovery = self.planner.recovery_plan(frame.state, start_frame.state, max_depth=safety.max_depth)
                    return NavigationResult(safety.status, frame, route, safety.halt_reason, recovery)
                if not safety.after_action(frame=next_frame, transition=transition):
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
