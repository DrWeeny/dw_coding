from maya import cmds
from typing import List, Union

#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

def current_timerange(range_: bool = False)  -> Union[List[int], range]:
    _min = cmds.playbackOptions(q=True, min=True)
    _max = cmds.playbackOptions(q=True, max=True)
    if not range_:
        return [int(_min), int(_max)]
    else:
        return range(int(_min), int(_max)+1)
