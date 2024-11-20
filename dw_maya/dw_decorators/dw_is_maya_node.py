from maya import cmds

def is_maya_node(f):
    def wrapper(self, *args, **kwargs):
        if not cmds.objExists(self._node):
            raise ValueError(f"Maya node '{self._node}' does not exist")
        return f(self, *args, **kwargs)
    return wrapper