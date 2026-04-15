from functools import wraps
from maya import cmds

def keep_selection(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # Sauvegarde sel + mode
        sel = cmds.ls(sl=True, long=True) or []
        hilite = cmds.ls(hl=True, long=True) or []
        mode = cmds.selectMode(q=True, component=True)

        try:
            return func(*args, **kwargs)
        finally:
            try:
                # Restore selection
                if sel:
                    cmds.select(sel, r=True)
                else:
                    cmds.select(clear=True)

                # Restore hilite (important pour composants)
                if hilite:
                    cmds.hilite(hilite, r=True)

                # Restore mode
                if mode:
                    cmds.selectMode(component=True)
                else:
                    cmds.selectMode(object=True)

            except Exception:
                pass

    return wrapper