"""State machine for PageViewer interactions.

Replaces 9+ boolean flags with a single typed state enum.
Prevents invalid state combinations and simplifies event handling.
"""
from __future__ import annotations

from enum import Enum, auto
from typing import Optional


class InteractionState(Enum):
    """Mutually exclusive interaction states for PageViewer."""

    IDLE = auto()
    DRAWING_RECT = auto()
    DRAWING_POLYGON = auto()
    SELECTING = auto()
    MOVING_BLOCK = auto()
    RESIZING_BLOCK = auto()
    DRAGGING_POLYGON_VERTEX = auto()
    DRAGGING_POLYGON_EDGE = auto()
    PANNING = auto()


# States that require read-write mode (blocked in read_only)
_WRITE_STATES = frozenset({
    InteractionState.DRAWING_RECT,
    InteractionState.DRAWING_POLYGON,
    InteractionState.MOVING_BLOCK,
    InteractionState.RESIZING_BLOCK,
    InteractionState.DRAGGING_POLYGON_VERTEX,
    InteractionState.DRAGGING_POLYGON_EDGE,
})

# States where mouse move should be throttled
_THROTTLED_STATES = frozenset({
    InteractionState.DRAWING_RECT,
    InteractionState.SELECTING,
})

# Valid transitions from each state
_VALID_TRANSITIONS: dict[InteractionState, frozenset[InteractionState]] = {
    InteractionState.IDLE: frozenset({
        InteractionState.DRAWING_RECT,
        InteractionState.DRAWING_POLYGON,
        InteractionState.SELECTING,
        InteractionState.MOVING_BLOCK,
        InteractionState.RESIZING_BLOCK,
        InteractionState.DRAGGING_POLYGON_VERTEX,
        InteractionState.DRAGGING_POLYGON_EDGE,
        InteractionState.PANNING,
    }),
    # All active states can return to IDLE
    InteractionState.DRAWING_RECT: frozenset({InteractionState.IDLE}),
    InteractionState.DRAWING_POLYGON: frozenset({InteractionState.IDLE}),
    InteractionState.SELECTING: frozenset({InteractionState.IDLE}),
    InteractionState.MOVING_BLOCK: frozenset({InteractionState.IDLE}),
    InteractionState.RESIZING_BLOCK: frozenset({InteractionState.IDLE}),
    InteractionState.DRAGGING_POLYGON_VERTEX: frozenset({InteractionState.IDLE}),
    InteractionState.DRAGGING_POLYGON_EDGE: frozenset({InteractionState.IDLE}),
    InteractionState.PANNING: frozenset({InteractionState.IDLE}),
}


def is_write_state(state: InteractionState) -> bool:
    """Check if state requires write access (blocked in read_only mode)."""
    return state in _WRITE_STATES


def is_throttled_state(state: InteractionState) -> bool:
    """Check if mouse moves should be throttled in this state."""
    return state in _THROTTLED_STATES


def can_transition(current: InteractionState, target: InteractionState) -> bool:
    """Check if transition from current to target state is valid."""
    if current == target:
        return True
    allowed = _VALID_TRANSITIONS.get(current, frozenset())
    return target in allowed
