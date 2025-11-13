import sys, os

# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print(f"Add {rdPath} to sysPath")
    sys.path.insert(0, rdPath)

from maya import cmds, mel
import dw_maya.dw_maya_nodes as dwnn
import dw_maya.dw_maya_utils as dwu
from dw_maya.dw_decorators import acceptString, viewportOff
import dw_maya.dw_presets_io as dwpreset
import dw_maya

class nConstraint(dwnn.MayaNode):
    """This class represents a dynamic constraint (nConstraint) in Maya.

    This can manage various types of constraints, including pointToSurface, weldBorders, force, etc.

    Examples:
        mn = nConstraint('nConstraint1')
        mn.nComponents
        mn.nucleus
        mn.network
    """

    def __init__(self, name: str, preset: dict = {}, blendValue: float = 1.0):
        """Initialize the nConstraint with a node name, preset, and blend value.

                    "transform", "pointToSurface",
            "slideOnSurface", "weldBorders", "force", "match", "tearableSurface",
            "weldBorders", "collisionExclusion", "disableCollision", "pointToPoint"

        Args:
            name (str): The name of the dynamic constraint node.
            preset (dict, optional): Preset used for node creation. Defaults to an empty dict.
            blendValue (float, optional): The blend value for the constraint. Defaults to 1.0.
        """
        super().__init__(name, preset, blendValue)

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
        nNodes = list(set(cmds.listConnections(ncomp_names, type='nBase') or [] +
                          cmds.listConnections(ncomp_names, type='hairSystem') or []))
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

    def attrPreset(self) -> dict:
        """Create a preset of the node attributes.

        Returns:
            dict: A dictionary containing all attributes for both `tr` and `sh`.
        """
        tr_dic = dwpreset.createAttrPreset(self.tr)
        sh_dic = dwpreset.createAttrPreset(self.sh)
        combined_dic = dwu.merge_two_dicts(tr_dic, sh_dic)

        key = self.sh.split(':')[-1] + '_network'
        combined_dic[key] = self.network

        out_dic = {self.tr.split(':')[-1]: combined_dic}
        out_dic[f'{self.tr.split(":")[-1]}_nodeType'] = self.nodeType

        return out_dic

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

    def _build_network(self,
                       src_node_name:str,
                       node_preset:dict=None,
                       target_node_name:str=None,
                       namespace:str=None):
        # look first if the dictionnary entry exists
        network_key = f"{src_node_name}_network"
        if not node_preset.get(network_key, None):
            return

        # Validate the cloth/hair/nucleus elements exist
        nBase = [f'{namespace}:{i.split(".")[-1]}'.replace('::', ':') for i in node_preset[network_key]['nBases']]
        if not all(cmds.objExists(j) for j in nBase):
            invalid_input = ', '.join(nBase)
            cmds.warning(
                f'Cannot create dynamicConstraint node "{target_node_name}" due to missing elements: {invalid_input}')
            return

        # Connect to nucleus using the shape node
        nucleus = [f'{namespace}:{n}' if namespace not in [':', ''] else n for n in node_preset[network_key]['nBases'] if
                   cmds.nodeType(n) == 'nucleus'][0]
        # connect to nucleus next available slots : multi = 2
        for out_attr, in_attr in zip(dwu.get_type_io(target_node_name), dwu.get_type_io(nucleus, io=0, multi=2)):
            cmds.connectAttr(out_attr, in_attr, f=True)

        # Look for nComponents :
        component_connections_list = node_preset[network_key].get('nComponent', None)
        # if there are nothing, do nothing
        if not component_connections_list:
            return

        # lets check if components exists, if not, lets create them
        component_final_list = []
        for component in component_connections_list:
            if not cmds.objExists(component[0]):
                component_node = dwnn.MayaNode(component.split(".")[0],
                                               preset='nComponent')
            else:
                component_node = dwnn.MayaNode(component)
            component_final_list.append(component_node)

        # lets iterate with the component list
        for ccl, cf in zip(component_connections_list, component_final_list):
            # seek the id number in bracket for destination connection
            idx = ccl[1].split('[')[-1][:-1]
            suffix = self.tr.rsplit(':', 1)[-1].replace('dynamicConstraint', 'dynC')
            ncomp_name = f'{namespace}:nComp{idx}_{suffix}' if namespace not in [':',
                                                                                 ''] else f'nComp{idx}_{suffix}'

            # Set attributes
            component_key = f'nComponent_{idx}'
            component_attr_dic = node_preset[network_key].get(component_key, None)
            if component_attr_dic:
                src_component = component_attr_dic.keys()[0]
                dwpreset.dw_preset.blend_attr_dic(src_component, cf.tr, component_attr_dic)

            # Connect nComponent to nConstraint using the shape
            for out_attr, in_attr in zip(dwu.get_type_io(cf.tr), dwu.get_type_io(self.sh, io=0, index=0, multi=2)):
                cmds.connectAttr(out_attr, in_attr, f=True)
            # connect time :
            cmds.connectAttr("time1.outTime", f"{self.sh}.currentTime", f=True)


            # Connect nBase to nComponent
            nbase_dic_connections = node_preset[network_key].get(f'nComponent_{idx}_nbase', None)
            nmesh_out = nbase_dic_connections[0]
            cmds.connectAttr(f'{namespace}:{nmesh_out}', f'{cf.tr}.objectId', f=True)

            # Create and connect maps
            map_key = f'nComponent_{idx}_maps'
            map_dic = node_preset[network_key].get(map_key, None)
            if map_key in map_dic:
                for x, np in enumerate(map_dic):
                    if map_dic[np]:
                        texture = map_dic[np]
                        map_connections = map_dic.get(f'{map_key}_connections', None)
                        correspondance = dw_maya.dw_presets_io.dw_preset.reconnectPreset(map_connections, True)

                        if texture in correspondance:
                            texture = correspondance[texture]

                        cmds.connectAttr(f'{texture}.{np}Map', f'{cf.tr}.{np}')

    def loadNode(self, preset: dict, blend: float = 1, namespace: str = ':') -> None:
        """Load the dynamic constraint node based on a preset.

        Args:
            preset (dict): The preset data.
            blend (float, optional): The blend value. Defaults to 1.
            namespace (str, optional): Target namespace for the node. Defaults to ':'.
        """
        if isinstance(preset, str):
            self.createNode(preset)
            return

        if isinstance(preset, dict):
            # preset should have two parts : node with all his network and node_nodeType
            # theorically inside the main node dictionnary, you can find in saved attributes :
            # nodeType = "node_name_type"
            # so you should find transform if there is one and shapes under this transform
            # name provided to this node can be different from the one inside the class
            # if the node exists already, it should apply the preset to it
            # if it doesnt it should first create the node

            # future name of the node
            futur_node_name_transform = self.__dict__['node']

            preset_node_type_key = [pname for pname in preset if pname.endswith("_nodeType")]

            node_type = None
            if preset_node_type_key:
                node_type = preset[preset_node_type_key[0]]

            if not node_type or node_type != "dynamicConstraint":
                return

            if not cmds.objExists(futur_node_name_transform):
                self.createNode(node_type, targ_ns=namespace, name=futur_node_name_transform)

            # find the key name of the main dictionnary provided
            node_preset_key = preset_node_type_key[0].rsplit('_', 1)[0]
            # get the sub dic with all the network and attributes per node
            sub_dic = preset[node_preset_key]

            for key in sub_dic:
                # find dictrionnaries for transform and shape
                sub_nt = sub_dic[key].get("nodeType", None)
                if sub_nt == "transform":
                    dwpreset.dw_preset.blend_attr_dic(src_node=key,
                                            target_node=self.tr,
                                            preset=sub_dic,
                                            blend_value=blend)

                    self._build_network(src_node_name=key,
                                        node_preset=sub_dic,
                                        target_node_name=self.tr,
                                        namespace=namespace)

                elif sub_nt == "dynamicConstraint":
                    dwpreset.dw_preset.blend_attr_dic(src_node=key,
                                            target_node=self.sh,
                                            preset=sub_dic,
                                            blend_value=blend)

                    self._build_network(src_node_name=key,
                                        node_preset=sub_dic,
                                        target_node_name=self.sh,
                                        namespace=namespace)



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

    def __init__(self, name: str, preset: dict = {}, blendValue: float = 1.0):
        """Initialize the nComponent with a node name, preset, and blend value.

        Args:
            name (str): The name of the nComponent node.
            preset (dict, optional): Used for node creation. Defaults to an empty dict.
            blendValue (float, optional): The blend value for the nComponent. Defaults to 1.0.
        """
        super().__init__(name, preset, blendValue)

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
                    error_msg = f"This map '{a}' doesn't exist. Pick one of these: {list(self._maps_dic.keys())}."
                    cmds.error(error_msg)
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
                pattern = '{geometry}.{component}[{id}]'.format
                if isinstance(nodes, str):
                    m_ids = dwu.create_maya_ranges(ids)
                    return [pattern(geometry=self.geometry, component=compo, id=i) for i in m_ids]
                else:
                    curve_ranges = {}
                    offset = 0
                    for crv in nodes:
                        cv_count = len(cmds.ls(crv + '.cv[*]', fl=True))
                        previous_value = offset
                        offset += cv_count
                        curve_ranges[offset] = [crv, previous_value]

                    m_sel = []
                    for i in ids:
                        curve_id = min(curve_ranges.keys(), key=lambda x: abs(x - i))
                        m_sel.append(f'{curve_ranges[curve_id][0]}.cv[{i - curve_ranges[curve_id][1]}]')
                    return m_sel

            elif elem_type == 2:
                # Select all components
                pattern = '{geometry}.{component}[:]'.format
                if isinstance(self.geometry, str):
                    return cmds.ls(pattern(geometry=self.geometry, component=compo))
                else:
                    return [pattern(geometry=p, component='cv') for p in self.geometry]
            else:
                return self.geometry

        elif compo_type == 6:
            return self.geometry
