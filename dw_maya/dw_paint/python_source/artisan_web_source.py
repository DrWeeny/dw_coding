"""
https://www.charactersetup.com/tutorials/artisan.html
"""

import __main__
import logging
from maya import cmds, mel
from PySide2 import QtCore
from didi_maya.lib import m_dag						# sorry, this is local to me for now!

log = logging.getLogger(__name__)
log.setLevel(logging.DEBUG)							# super spammy prints for more info


class GenericPaint(QtCore.QObject):
    context_activated = QtCore.Signal()             # let a UI know the context has turned on
    context_deactivated = QtCore.Signal()           # let a UI know the context has turned off

    def __init__(self, parent=None, context='didiGenericPaintContext'):
        """
        A bare-bones artisan context that supports multi-select as well as applying changes per stamp projection for
        performance.  See the logging debug prints for more info on what is happening.
        """
        super(GenericPaint, self).__init__(parent)

        # settings that can be managed to modify how things are computed
        self.context = context
        self.value = 1.0

        # settings that are managed by a property
        self._stamp_type = 'gaussian'

        # used during painting
        self._shapes = []                   # selected shapes when the context turns on
        self._v_values = []                 # for each shape, tracks the hit {vert_id: opacity}
        self._init_shapes = {}              # track the shapes hit during a stroke
        self._init_shape_ids = []           # track the index of the hit shapes
        self._init_modifiers = None         # track which modifiers were pressed at the start of the stroke
        self._stroke_completed = False      # when the stroke is complete, we set weights that are undoable

        # supported brushes / stamps
        self._stamp_types = ('gaussian', 'poly', 'solid')

    @property
    def stamp_type(self):
        # name of the current brush stamp
        return self._stamp_type

    @stamp_type.setter
    def stamp_type(self, stamp_type):
        # switch to a different brush stamp for a different falloff
        if stamp_type not in self._stamp_types:
            raise Exception(f'Unsupported stamp type "{stamp_type}".')

        self._stamp_type = stamp_type
        cmds.artUserPaintCtx(self.context, edit=True, stampProfile=stamp_type)

    def start_context(self):
        """
        Setup the user paint context so that it will call into this class.
        """
        # store this instance into __main__ so it can be more easily called via the mel/python nonsense.
        __main__.__dict__[self.context] = self

        # create mel classes used by the artUserPaintCtx... just redirects to this class
        mel.eval(f'''
        global proc string {self.context}_init_cmd(string $shape){{
            return python("{self.context}.init_cmd('"+$shape+"')");}}
        global proc {self.context}_on_cmd(){{
            python("{self.context}.on_cmd()");}}
        global proc {self.context}_off_cmd(){{
            python("{self.context}.off_cmd()");}}
        global proc {self.context}_before_stroke_cmd(){{
            python("{self.context}.before_stroke_cmd()");}}
        global proc {self.context}_set_value_cmd(int $shape_id, int $v_id, float $value, string $shape_long){{
            python("{self.context}.set_value_cmd("+$shape_id+", "+$v_id+", "+$value+", '"+$shape_long+"')");}}            
        global proc {self.context}_during_stroke_cmd(){{
            python("{self.context}.during_stroke_cmd()");}}
        global proc {self.context}_after_stroke_cmd(){{
            python("{self.context}.after_stroke_cmd()");}}
        global proc {self.context}_final_cmd(string $shape){{
            python("{self.context}.final_cmd('"+$shape+"')");}}  
        ''')

        # create the context if it doesnt exist
        if not cmds.artUserPaintCtx(self.context, query=True, exists=True):
            cmds.artUserPaintCtx(self.context)

        # setup the context
        cmds.artUserPaintCtx(
            self.context,
            edit=True,
            value=1.0,
            opacity=1.0,
            fullpaths=True,
            accopacity=False,
            stampProfile=self.stamp_type,
            selectedattroper='additive',
            wst='userPaint',
            image1='userPaint.png',
            initializeCmd=f'{self.context}_init_cmd',
            toolOnProc=f'{self.context}_on_cmd',
            toolOffProc=f'{self.context}_off_cmd',
            beforeStrokeCmd=f'{self.context}_before_stroke_cmd',
            setValueCommand=f'{self.context}_set_value_cmd',
            duringStrokeCmd=f'{self.context}_during_stroke_cmd',
            afterStrokeCmd=f'{self.context}_after_stroke_cmd',
            finalizeCmd=f'{self.context}_final_cmd',
        )

        # turn on the context
        cmds.setToolTo(self.context)

    def on_cmd(self):
        """
        When the context is turned on, track the shapes that were selected.
        """
        log.debug('on_cmd')

        sel = cmds.ls(selection=True, objectsOnly=True)
        self._shapes = []
        for node in sel:
            shape = m_dag.get_dag(node, get_shape=True)         # just a helper func to convert the string to MDagPath
            if not shape:
                continue
            self._shapes.append(shape.fullPathName())
        self.context_activated.emit()

    def off_cmd(self):
        """
        When the context is turned off.
        """
        log.debug('off_cmd')

        self.context_deactivated.emit()

    def before_stroke_cmd(self):
        """
        This is called on click, before a stamp has been projected.
        """
        log.debug('before_stroke_cmd')

        self._v_values = []
        self._init_shapes = {}
        self._init_shape_ids = []
        self._stroke_completed = False

    def init_cmd(self, shape=None):
        """
        This is called when you click + drag over a surface, or after you release a click that hit a surface without
        dragging.  However, this only happens for the first surface, so the shape argument here is not really useful for
        tracking which shape the stamp hit, but see the returned -path flag below.
        """
        log.debug(('init_cmd', shape))

        # using the -path flag causes the set_value_cmd to also receive the hit shape
        return '-path 1'

    def set_value_cmd(self, shape_id, v_id, value, shape_long):
        """
        This is called for each vertex that is hit in a stamp, so you should just gather the vertices and opacities,
        and then work with them all as a group for faster modification.  The passed shape_id is not really useful so you need
        to track it yourself.  Also see the during_stroke_cmd / final_cmd.
        """
        log.debug(('set_value_cmd', v_id, value, shape_long))

        shape_init_id = self._init_shapes.get(shape_long)
        if shape_init_id is None:
            try:
                # get the "real" shape index, shape_id is bugged
                self._init_shape_ids.append(self._shapes.index(shape_long))
            except ValueError:
                log.warning(f'Brush hit a shape not attached to the context, {shape_long}')
                return
            shape_init_id = len(self._v_values)
            self._init_shapes[shape_long] = shape_init_id
            self._v_values.append({})

        self._v_values[shape_init_id][v_id] = value

    def during_stroke_cmd(self):
        """
        This happens during a drag after the projection of all vertices in a stamp, eg the set_value_cmd is finished.
        This should call into the final_cmd to apply updates.  However, this does not get called during a single click
        of vertices.
        """
        log.debug('during_stroke_cmd')

        self.final_cmd()

    def final_cmd(self, shape_id=None):
        """
        This is called on click or release of a drag.  However, the during_stroke_cmd also calls this to allow updates
        for each stamp projection.
        """
        log.debug(('final_cmd', shape_id))

        for shape_init_id, shape_id in enumerate(self._init_shape_ids):
            self.shape_final_cmd(shape_init_id, shape_id)
            self._v_values[shape_id].clear()				# clear the hit vert opacities after applying
        self._stroke_completed = False

    def shape_final_cmd(self, shape_init_id, shape_id):
        """
        The main function that should make changes to the scene.  Tracking the _stroke_completed variable allows you
        to switch between applying non-undoable and undoable changes for better performance.
        """
        v_ids = self._v_values[shape_id].keys()
        log.debug(('shape_final_cmd', shape_init_id, shape_id, v_ids))

        if not v_ids:
            return

    def after_stroke_cmd(self):
        """
        This is called on click release or drag release, followed by the final_cmd.  The _stroke_completed variable is
        used to help the final_cmd apply undoable changes.
        """
        log.debug('after_stroke_cmd')

        self._stroke_completed = True