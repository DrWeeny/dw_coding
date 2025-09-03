from maya import cmds
import maya.app.renderSetup.model.renderLayer

RenderLayer = maya.app.renderSetup.model.renderLayer.RenderLayer

def set_template_layer(name: str):
    """
    Create a display layer for the given object name if it doesn't exist, and set its display type to 'template'.

    Args:
        name (str): The name of the object or node in Maya.

    Returns:
        Optional[str]: The name of the created or modified display layer, or None if no layer was created.
    """
    # Check if the object exists
    if not cmds.objExists(name):
        l_name = '{}Layer'.format(name)
        layer = cmds.createDisplayLayer(name=l_name, number=1, e=True)

    # Set the layer display type to 'template' (1)
    cmds.setAttr(f'{l_name}.displayType', 1)
    return l_name

def create_render_layer(name:str, renderable:bool=True)->RenderLayer:
    """
    Create a render layer with the given name.

    Note: Autodesk Maya automatically adds the 'rs_' prefix to the layer name.
    For example, if you provide 'occlusion_layer', the actual name will be 'rs_occlusion_layer'.

    :param name: Name of the render layer (without 'rs_' prefix).
    :param renderable: Whether the layer is renderable.
    :return: The created RenderLayer instance.
    """

    render_layer = maya.app.renderSetup.model.renderLayer.create(name)
    render_layer.setRenderable(renderable)
    return render_layer

