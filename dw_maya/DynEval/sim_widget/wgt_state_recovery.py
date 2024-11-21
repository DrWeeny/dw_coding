from dataclasses import dataclass
from typing import List, Dict, Optional
from collections import deque
import maya.cmds as cmds


@dataclass
class ToggleOperation:
    """Represents a single toggle operation for undo/redo."""
    node: str
    previous_state: bool
    new_state: bool
    timestamp: float


class StateManager:
    """Manages toggle state history for undo/redo operations."""

    def __init__(self, max_history: int = 50):
        self.undo_stack: deque[ToggleOperation] = deque(maxlen=max_history)
        self.redo_stack: deque[ToggleOperation] = deque(maxlen=max_history)

    def push_operation(self, node: str, previous_state: bool, new_state: bool) -> None:
        """Record a new toggle operation."""
        from time import time
        operation = ToggleOperation(
            node=node,
            previous_state=previous_state,
            new_state=new_state,
            timestamp=time()
        )
        self.undo_stack.append(operation)
        self.redo_stack.clear()  # Clear redo stack when new operation is added

    def can_undo(self) -> bool:
        """Check if undo is available."""
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        """Check if redo is available."""
        return bool(self.redo_stack)

    def undo(self) -> Optional[ToggleOperation]:
        """Undo last toggle operation."""
        if not self.can_undo():
            return None

        operation = self.undo_stack.pop()
        self.redo_stack.append(operation)
        return operation

    def redo(self) -> Optional[ToggleOperation]:
        """Redo previously undone operation."""
        if not self.can_redo():
            return None

        operation = self.redo_stack.pop()
        self.undo_stack.append(operation)
        return operation