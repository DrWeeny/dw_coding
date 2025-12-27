"""
DataHub Integration for DynEval Widgets

DEPRECATED: Use sim_widget.wgt_base instead.

This module re-exports from wgt_base for backwards compatibility.
New code should import directly from:
    from dw_maya.DynEval.sim_widget.wgt_base import DynEvalWidget, HubPublisher

Usage (legacy):
    class MyWidget(QtWidgets.QWidget, HubSubscriberMixin):
        def __init__(self):
            super().__init__()
            self.init_hub()
            self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)

        def closeEvent(self, event):
            self.cleanup_hub()
            super().closeEvent(event)

Usage (recommended):
    class MyWidget(DynEvalWidget):
        def __init__(self):
            super().__init__()
            self.hub_subscribe(HubKeys.SELECTED_ITEM, self._on_selection_changed)
        # closeEvent handled automatically
"""

# Re-export from wgt_base for backwards compatibility
from .sim_widget.wgt_base import (
    HubMixin as HubSubscriberMixin,  # Alias for backwards compatibility
    HubPublisher,
    publishes,
    on_hub_change as subscribes_to,  # Alias
)

from .hub_keys import HubKeys, SelectionContext, PaintContext
from dw_logger import get_logger

logger = get_logger()


def auto_subscribe(widget_instance):
    """
    Automatically subscribe all methods decorated with @subscribes_to.

    Call this after widget initialization:
        auto_subscribe(self)
    """
    for name in dir(widget_instance):
        method = getattr(widget_instance, name, None)
        if callable(method) and hasattr(method, '_hub_key'):
            widget_instance.hub_subscribe(method._hub_key, method)