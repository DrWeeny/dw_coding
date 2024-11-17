__author__ = 'baua'

import maya.cmds as cmds
import maya.mel as mel

def get_channels():
    """
    Retrieves the selected channels from the Maya Channel Box.

    Returns:
        list: A list of strings in the form 'object.attribute' if channels are selected.
        bool: False if no channels are selected.
    """
    gChannelBoxName = mel.eval('$temp=$gChannelBoxName')
    chList = []

    # Helper function to get channels from channelBox
    def query_channels(name_object_query, attr_query):
        name_object = cmds.channelBox(gChannelBoxName, q=True, **{name_object_query: 1}) or []
        if name_object:
            name_object = cmds.ls(sl=1) and list(set(cmds.ls(sl=1)) & set(name_object))[0]
            attr_selected = cmds.channelBox(gChannelBoxName, q=True, **{attr_query: True}) or []
            if attr_selected:
                return [f"{name_object}.{attr}" for attr in attr_selected]
        return []

    # Query different channelBox sections
    chList.extend(query_channels('hol', 'sha'))
    chList.extend(query_channels('mainObjectList', 'sma'))
    chList.extend(query_channels('sol', 'ssa'))
    chList.extend(query_channels('sol', 'soa'))

    if chList:
        return chList
    else:
        cmds.warning('No channels selected!')
        return False

def set_outliner_in_panel(outliner='outlinerPanel1', panel='modelPanel1'):
    """
    Sets the outliner panel to display in the given model panel.

    Args:
        outliner (str): The name of the outliner panel to connect.
        panel (str): The name of the model panel to connect to the outliner.
    """
    cmds.outlinerPanel(outliner, edit=True, rp=panel)
