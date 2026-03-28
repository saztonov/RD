"""Тесты для InteractionState — state machine PageViewer."""
import pytest

from app.gui.interaction_state import (
    InteractionState,
    can_transition,
    is_throttled_state,
    is_write_state,
)


class TestInteractionState:
    def test_all_states_exist(self):
        expected = {
            "IDLE", "DRAWING_RECT", "DRAWING_POLYGON", "SELECTING",
            "MOVING_BLOCK", "RESIZING_BLOCK", "DRAGGING_POLYGON_VERTEX",
            "DRAGGING_POLYGON_EDGE", "PANNING",
        }
        actual = {s.name for s in InteractionState}
        assert actual == expected


class TestWriteStates:
    @pytest.mark.parametrize("state", [
        InteractionState.DRAWING_RECT,
        InteractionState.DRAWING_POLYGON,
        InteractionState.MOVING_BLOCK,
        InteractionState.RESIZING_BLOCK,
        InteractionState.DRAGGING_POLYGON_VERTEX,
        InteractionState.DRAGGING_POLYGON_EDGE,
    ])
    def test_write_states(self, state):
        assert is_write_state(state) is True

    @pytest.mark.parametrize("state", [
        InteractionState.IDLE,
        InteractionState.SELECTING,
        InteractionState.PANNING,
    ])
    def test_non_write_states(self, state):
        assert is_write_state(state) is False


class TestThrottledStates:
    def test_drawing_rect_throttled(self):
        assert is_throttled_state(InteractionState.DRAWING_RECT) is True

    def test_selecting_throttled(self):
        assert is_throttled_state(InteractionState.SELECTING) is True

    def test_moving_not_throttled(self):
        assert is_throttled_state(InteractionState.MOVING_BLOCK) is False


class TestTransitions:
    def test_idle_to_any(self):
        for state in InteractionState:
            if state != InteractionState.IDLE:
                assert can_transition(InteractionState.IDLE, state) is True

    def test_active_to_idle(self):
        for state in InteractionState:
            if state != InteractionState.IDLE:
                assert can_transition(state, InteractionState.IDLE) is True

    def test_active_to_active_blocked(self):
        assert can_transition(
            InteractionState.DRAWING_RECT, InteractionState.MOVING_BLOCK,
        ) is False

    def test_same_state_allowed(self):
        for state in InteractionState:
            assert can_transition(state, state) is True
