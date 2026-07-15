"""Op taxonomy: the semantic node kinds a recipe can use.

Summary:
    Declares, per op type, the input ports a node of that kind consumes.
    This is recipe-format vocabulary (DCC-agnostic), not backend code:
    backends *implement* these kinds, the UI *displays* them, and neither
    needs the other importable. Ports listed here are affordances, not
    requirements - a recipe may wire extra ports (backends ignore unknown
    ones) and may leave declared ones unwired where optional.

Author:
    DrWeeny
"""

#: op type -> declared input ports, in display order.
OP_INPUTS = {
    'script': (),
    'merge': ('in0', 'in1'),
    'file': ('roots', 'trigger'),
    'group': ('source',),
    'hierarchy': (),
    'solver': ('objects', 'parent'),
    'cloth': ('meshes',),
    'collider': ('meshes',),
    'step': ('meshes', 'parent'),
    'preset': (),
    'constraint': ('first', 'second'),
    'deformer': ('driven', 'driver'),
}

#: full authoring palette (the registry only knows imported backends).
OP_TYPES = tuple(OP_INPUTS)

#: solver family -> op types its backends support. Today everything is
#: implemented for nucleus (maya); a bifrost/vellum/ziva backend adds an
#: entry here without touching the UI.
SOLVER_OPS = {
    'nucleus': OP_TYPES,
}