from maya import cmds, mel
import dw_maya.dw_maya_nodes as dwnn
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString, viewportOff
import dw_maya.dw_presets_io as dwpreset
import dw_maya.dw_presets_io.preset_components as pcomp
import dw_maya
from dw_logger import get_logger

from dw_maya.dw_node_registry import register_type

logger = get_logger()


class NConstraintNetworkComponent(pcomp.PresetComponent):
    """Capture / rebuild the bespoke dynamicConstraint network.

    Unlike the generic ConnectionComponent (a flat plug-pair list), an
    nConstraint carries a structured nucleus <-> nComponent <-> constraint <->
    nBase graph plus per-component maps. Capture defers to :attr:`nConstraint.network`;
    apply defers to :meth:`nConstraint._apply_network`, so the intricate,
    already-validated build logic stays in one place and just plugs into the
    component pipeline.
    """

    key = "network"
    enabled_by_default = True

    def capture(self, node, ctx):
        try:
            return node.network
        except Exception as e:
            logger.warning(f"NConstraintNetworkComponent: capture failed on "
                           f"'{node.node}': {e}")
            return None

    def apply(self, node, data, ctx):
        node._apply_network(data, ctx=ctx)


class nConstraint(dwnn.MayaNode):
    """This class represents a dynamic constraint (nConstraint) in Maya.

    This can manage various types of constraints, including pointToSurface, weldBorders, force, etc.

    Examples:
        mn = nConstraint('nConstraint1')
        mn.nComponents
        mn.nucleus
        mn.network
    """

    #: Attributes + the bespoke network. The generic ConnectionComponent is
    #: intentionally omitted: the network component owns all of this node's
    #: wiring, so including it would double-capture the nucleus/nComponent links.
    preset_components = (pcomp.AttributeComponent(), NConstraintNetworkComponent())

    def __init__(self, name: str, preset: dict = None, blendValue: float = 1.0):
        """Initialize the nConstraint with a node name, preset, and blend value.

                    "transform", "pointToSurface",
            "slideOnSurface", "weldBorders", "force", "match", "tearableSurface",
            "weldBorders", "collisionExclusion", "disableCollision", "pointToPoint"

        Args:
            name (str): The name of the dynamic constraint node.
            preset (dict, optional): Preset used for node creation. Defaults to None.
            blendValue (float, optional): The blend value for the constraint. Defaults to 1.0.
        """
        super().__init__(name, preset or {}, blendValue)

    @property
    def nComponents(self) -> list:
        """Retrieve all the nComponents connected to this constraint."""
        components = cmds.listConnections(self.sh, type='nComponent')
        return [nComponent(comp) for comp in components] if components else []

    @property
    def nucleus(self) -> str:
        """Get the nucleus node associated with the constraint."""
        nuclei = list(set(cmds.listConnections(self.sh, type='nucleus')))
        return nuclei[0] if nuclei else None

    @property
    def network(self) -> dict:
        """Get the network of connections for this dynamic constraint."""
        nuclei = list(set(cmds.listConnections(self.sh, type='nucleus')))
        nucleus_agnostic = [n.split(':')[-1] for n in nuclei]

        # Get nComponents and their connections
        ncomp_names = [n.sh for n in self.nComponents]
        ncomp_connections = cmds.listConnections(self.sh, type='nComponent', p=True)
        nconst_connections = cmds.listConnections(ncomp_connections, type='dynamicConstraint', p=True)

        # Build agnostic connections
        ncomp_connections_agnostic = [con.split(':')[-1] for con in ncomp_connections]
        nconst_connections_agnostic = [con.split(':')[-1] for con in nconst_connections]

        # Get nBase and hairSystem nodes
        nNodes = list(set(
            (cmds.listConnections(ncomp_names, type='nBase') or []) +
            (cmds.listConnections(ncomp_names, type='hairSystem') or [])
        ))
        nNodes_agnostic = [n.split(':')[-1] for n in nNodes]

        # Create the network dictionary
        network_dict = {
            'nBases': nNodes_agnostic + [nucleus_agnostic[0]],
            'nComponent': list(zip(ncomp_connections_agnostic, nconst_connections_agnostic))
        }

        # Add nComponent presets to the network
        for idx, nc in enumerate(self.nComponents):
            key_id = nconst_connections[idx].split('[')[-1][:-1]  # Get index part from "[idx]"
            value_preset = nc.attrPreset()
            network_dict[f'nComponent_{key_id}'] = value_preset

            nbase_connections = cmds.listConnections(nc.tr, type='nBase', p=True) or []
            hair_connections = cmds.listConnections(nc.tr, type='hairSystem', p=True)
            if hair_connections:
                nbase_connections += hair_connections
            network_dict[f'nComponent_{key_id}_nbase'] = [
                nbase_connections[0].split(':')[-1],
                dwu.get_type_io(nc.tr, io=0).split(':')[-1]
            ]

            # Get maps and connections
            maps = nc.maps()
            maps_agnostic = {k.split('.')[-1]: v.split('.')[-1] if v else None for k, v in maps.items()}
            if maps_agnostic:
                network_dict[f'nComponent_{key_id}_maps'] = maps_agnostic
                map_connections = dwpreset.dw_preset.createConnectionPreset([v.split('.')[0] for v in maps_agnostic.values() if v])
                network_dict[f'nComponent_{key_id}_maps_connections'] = map_connections

        return network_dict

    @property
    def components(self) -> list:
        """Retrieve all components associated with the nComponents."""
        components = []
        for nc in self.nComponents[::-1]:
            component = nc.component
            if isinstance(component, str):
                components.append(component)
            else:
                components += component
        return components

    def _apply_network(self,
                       network: dict,
                       namespace: str = None,
                       target: str = None,
                       ctx=None):
        """Rebuild the constraint network from a network dict.

        Reconnects the dynamicConstraint to its nucleus, recreates/reconnects
        nComponents, restores their attributes, rewires nBase inputs and maps.
        Requires the cloth/hair/nucleus targets to already exist in the scene.
        Stored names resolve through the shared preset resolver
        (``resolve_scene_node``), so targets are found whether the rig lives
        at root, in ``ctx.target_ns`` or in any other unambiguous namespace.

        Args:
            network: The network dict (as produced by :attr:`network`).
            namespace: Namespace the targets live in (``:`` / ``''`` for root).
                Kept for backward compatibility; ignored when ``ctx`` is given.
            target: The constraint node to wire (defaults to this shape).
            ctx: PresetContext from the component pipeline.
        """
        target = target or self.sh
        if ctx is None:
            ctx = pcomp.PresetContext(target_ns=namespace or ':')

        # Resolve the cloth/hair/nucleus elements through the shared resolver
        resolved = {}
        missing = []
        for stored in network.get('nBases', []):
            stored_node = stored.split('.')[0]
            scene_node = pcomp.resolve_scene_node(stored_node, ctx)
            if scene_node:
                resolved[stored_node] = scene_node
            else:
                missing.append(stored_node)
        if missing:
            logger.warning(f'Cannot rebuild network of "{target}", missing '
                           f'elements: {", ".join(missing)}')
            return

        # Connect the constraint to its nucleus (next available multi slots)
        nucleus = next((n for n in resolved.values()
                        if cmds.nodeType(n) == 'nucleus'), None)
        if not nucleus:
            logger.warning(f'No nucleus among the stored nBases of "{target}", '
                           f'network skipped')
            return
        for out_attr, in_attr in zip(dwu.get_type_io(target),
                                     dwu.get_type_io(nucleus, io=0, multi=2)):
            cmds.connectAttr(out_attr, in_attr, f=True)
        cmds.connectAttr('time1.outTime', f'{target}.currentTime', f=True)

        # Look for nComponents :
        component_connections_list = network.get('nComponent', None)
        # if there are nothing, do nothing
        if not component_connections_list:
            return

        for ccl in component_connections_list:
            stored_comp = ccl[0].split('.')[0]
            # index part of the stored "constraintShape.componentIds[idx]"
            idx = ccl[1].split('[')[-1][:-1]

            # Reuse the nComponent when it already exists, create it otherwise
            existing = pcomp.resolve_scene_node(stored_comp, ctx)
            if existing:
                cf = dwnn.MayaNode(existing)
            else:
                cf = dwnn.MayaNode(stored_comp, 'nComponent')

            # Set attributes
            component_attr_dic = network.get(f'nComponent_{idx}', None)
            if component_attr_dic:
                src_component = list(component_attr_dic.keys())[0]
                dwpreset.dw_preset.blend_attr_dic(src_component,
                                                  cf.node,
                                                  component_attr_dic)

            # Connect nComponent to nConstraint at the stored index
            cmds.connectAttr(f'{cf.node}.outComponent',
                             f'{target}.componentIds[{idx}]',
                             f=True)

            # Connect nBase to nComponent
            nbase_dic_connections = network.get(f'nComponent_{idx}_nbase', None)
            if nbase_dic_connections:
                src_node, src_attr = nbase_dic_connections[0].split('.', 1)
                src_resolved = pcomp.resolve_scene_node(src_node, ctx)
                if src_resolved:
                    cmds.connectAttr(f'{src_resolved}.{src_attr}',
                                     f'{cf.node}.objectId',
                                     f=True)
                else:
                    logger.warning(f'nComponent_{idx}: nBase source '
                                   f'"{src_node}" not found, objectId not '
                                   f'connected')

            # Reconnect texture-driven maps
            map_dic = network.get(f'nComponent_{idx}_maps', None)
            if map_dic:
                map_connections = network.get(f'nComponent_{idx}_maps_connections', None)
                correspondance = {}
                if map_connections:
                    correspondance = dw_maya.dw_presets_io.dw_preset.reconnectPreset(map_connections, True)
                for map_attr, texture_plug in map_dic.items():
                    if not texture_plug:
                        continue
                    texture = texture_plug.split('.')[0]
                    if texture in correspondance:
                        texture = correspondance[texture]
                    try:
                        cmds.connectAttr(f'{texture}.{map_attr}Map',
                                         f'{cf.node}.{map_attr}')
                    except Exception as e:
                        logger.warning(f'nComponent_{idx}: map "{map_attr}" '
                                       f'reconnection failed: {e}')


class nComponent(dwnn.MayaNode):
    """This class represents an nComponent node in Maya. It provides methods to manage
    the geometry, constraints, and map attributes of the nComponent.

    Examples:
        mn = nComponent('nComponent18')
        mn.tangentStrength.set(.5)
        mn.componentIndices.get()[0]
        mn.geometry
        mn.maps('strength')

        c = mn.component
        mn.nConstraint
        cmds.select(c)
    """

    def __init__(self, name: str, preset: dict = None, blendValue: float = 1.0):
        """Initialize the nComponent with a node name, preset, and blend value.

        Args:
            name (str): The name of the nComponent node.
            preset (dict, optional): Used for node creation. Defaults to None.
            blendValue (float, optional): The blend value for the nComponent. Defaults to 1.0.
        """
        super().__init__(name, preset or {}, blendValue)

    @property
    def geometry(self) -> list:
        """Get the geometry associated with the nComponent node."""
        connections = cmds.listConnections(f'{self.node}.objectId')
        if connections:
            # Check if connected to a hairSystem
            if cmds.ls(connections, dag=True, type='hairSystem'):
                attr = dwu.get_type_io(connections[0], io=1, multi=0)[0]
                follicles = cmds.listConnections(attr, sh=True)
                io = 1
                if not follicles:
                    attr = dwu.get_type_io(connections[0], io=0, multi=0)[0]
                    follicles = cmds.listConnections(attr, sh=True)
                    io = 0

                curve_list = []
                for follicle in follicles:
                    fol_attr = dwu.get_type_io(follicle, io=io)[0]
                    curve = cmds.listConnections(fol_attr)
                    if cmds.nodeType(curve[0]) == 'groupParts':
                        curve = cmds.listConnections(curve[0] + '.outputGeometry')
                    curve_list.append(curve[0])
                return curve_list

            # If not hairSystem, check for mesh connection
            geo = cmds.listConnections(f'{connections[0]}.inputMesh')
            if geo:
                return geo[0]

    @property
    def nConstraint(self) -> str:
        """Get the dynamic constraint associated with the nComponent."""
        constraint = cmds.listConnections(f'{self.node}.outComponent', type='dynamicConstraint')
        return constraint[0] if constraint else None

    @property
    def _maps_dic(self) -> dict:
        """Get the dictionary mapping attribute names to their respective map types."""
        return {'strength': self.strengthMapType,
                'glueStrength': self.glueStrengthMapType,
                'weight': self.weightMapType}

    @acceptString('attr')
    def maps(self, attr=None) -> dict:
        """Get the map attribute values for the given attribute(s).

        Args:
            attr (str or list, optional): The attribute(s) to retrieve map data for. If None, returns all maps.

        Returns:
            dict: A dictionary of map data.
        """
        result = {}

        if attr and attr != [None]:
            for a in attr:
                if a not in self._maps_dic:
                    raise ValueError(
                        f"Map '{a}' doesn't exist. Pick one of: {list(self._maps_dic.keys())}."
                    )
        else:
            attr = list(self._maps_dic.keys())

        for a in attr:
            map_type = self._maps_dic[a].getAttr()
            if map_type == 0:
                out = None
            elif map_type == 1:
                out = cmds.getAttr(f'{self.node}.{a}PerVertex')
            elif map_type == 2:
                con = cmds.listConnections(f'{self.node}.{a}Map')
                if con:
                    texture_node = con[0]
                    texture_type = cmds.nodeType(texture_node)
                    dest_connections = cmds.listConnections(texture_node, d=True, s=False, p=True, type='nComponent')
                    valid_dest_connections = [i for i in dest_connections if i == f'{self.node}.{a}Map']
                    src_connections = cmds.listConnections(valid_dest_connections, d=False, s=True, p=True,
                                                           type=texture_type)
                    out = src_connections[0] if src_connections else None
                else:
                    out = None
            if len(attr) == 1:
                return out
            result[a] = out

        return result

    @property
    def component(self) -> list:
        """Get the component selection for the nComponent.

        Returns:
            list: A list of Maya components (e.g., vertices, edges, faces) associated with the nComponent.
        """
        component_types = {2: 'vtx', 3: 'e', 4: 'f'}
        elem_type = self.elements.get()  # 0 - From Indice List, 1 - Borders, 2 - All
        compo_type = self.componentType.get()  # 0: None, 2: Point, 3: Edge, 4: Face, 6: Object

        if compo_type in [2, 3, 4]:
            compo = component_types[compo_type]
            if elem_type == 0:
                # Select specific indices
                ids = self.componentIndices.get()[0]
                ids = map(int, ids)

                nodes = self.geometry
                if isinstance(nodes, str):
                    m_ids = dwu.create_maya_ranges(ids)
                    return [f'{self.geometry}.{compo}[{i}]' for i in m_ids]
                else:
                    curve_ranges = {}
                    offset = 0
                    for crv in nodes:
                        cv_count = len(cmds.ls(f'{crv}.cv[*]', fl=True))
                        previous_value = offset
                        offset += cv_count
                        curve_ranges[offset] = [crv, previous_value]

                    m_sel = []
                    for i in ids:
                        curve_id = min(list(curve_ranges.keys()), key=lambda x: abs(x - i))
                        m_sel.append(f'{curve_ranges[curve_id][0]}.cv[{i - curve_ranges[curve_id][1]}]')
                    return m_sel

            elif elem_type == 2:
                # Select all components
                if isinstance(self.geometry, str):
                    return cmds.ls(f'{self.geometry}.{compo}[:]')
                else:
                    return [f'{p}.cv[:]' for p in self.geometry]
            else:
                return self.geometry

        elif compo_type == 6:
            return self.geometry

# register for lsNode
register_type('dynamicConstraint', nConstraint)
register_type('nComponent', nComponent)
