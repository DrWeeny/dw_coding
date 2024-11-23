
from .base_standarditem import BaseSimulationItem



class NucleusStandardItem(BaseSimulationItem):
    """Item for representing nucleus nodes in the tree."""

    def __init__(self, node):
        super().__init__(node)
        self.setText(self.short_name)
        self._setup_item()


    def set_state(self, state):
        """Overrides base method to set icon based on state."""
        super().set_state(state)

    @property
    def short_name(self):
        return self.node.split('|')[-1].split(':')[-1].split('_Sim')[0]