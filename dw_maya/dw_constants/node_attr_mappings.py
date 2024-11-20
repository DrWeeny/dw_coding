"""
Maya Node Attribute Mappings

Defines input/output attribute mappings for various Maya node types.
Used by the attribute utilities to identify key connections.

Structure:
    NODE_IO_MAPPING = {
        'node_type': [
            input_attributes,  # Index 0
            output_attributes  # Index 1
        ]
    }

Where attributes can be:
    - Single string: 'attributeName'
    - List of strings: ['attr1', 'attr2']
    - Attribute with index: 'attribute[0]'
    - Compound path: 'parent.child[0]'

Example:
    NODE_IO_MAPPING['mesh'] = [
        'inMesh',           # Input
        'worldMesh[0]'      # Output
    ]
"""

# Node type to IO attribute mapping
NODE_IO_MAPPING = {
    # Geometry nodes
    'mesh': ['inMesh', 'worldMesh[0]'],
    'nurbsCurve': ['create', 'local'],
    'nurbsSurface': ['create', 'local'],
    'subdiv': ['inMesh', 'outMesh'],

    # Deformers
    'wrap': [
        ['basePoints[0]', 'input[0].inputGeometry', 'driverPoints[0]', 'geomMatrix'],
        'outputGeometry[0]'
    ],
    'blendShape': [
        'inputTarget[0].inputTargetGroup[0]',
        'outputGeometry[0]'
    ],
    'skinCluster': [
        'input[0].inputGeometry',
        'outputGeometry[0]'
    ],
    'lattice': [
        'input[0].inputGeometry',
        'outputGeometry[0]'
    ],
    'cluster': [
        'input[0].inputGeometry',
        'outputGeometry[0]'
    ],
    'softMod': [
        'input[0].inputGeometry',
        'outputGeometry[0]'
    ],

    # nCloth nodes
    'nucleus': [
        ['inputCurrent[0]', 'inputStart[0]'],
        'outputObjects[0]'
    ],
    'nCloth': [
        ['inputMesh', 'nextState'],
        ['outputMesh', 'nucleusId']
    ],
    'nRigid': [
        ['inputMesh', 'startFrame'],
        ['outputMesh', 'nucleusId']
    ],
    'nParticle': [
        ['targetGeometry', 'targetPosition'],
        ['output', 'nucleusId']
    ],

    # Hair system
    'hairSystem': [
        ['inputHair[0]'],
        ['outputHair[0]', 'nucleusId']
    ],
    'follicle': [
        ['startPosition', 'startPositionMatrix', 'inputMesh'],
        ['outCurve', 'outHair']
    ],
    'pfxHair': [
        'inputAttractors[0]',
        'outputCurves'
    ],
    # Utility nodes
    'transformGeometry': [
        ['transform', 'inputGeometry'],
        'outputGeometry'
    ],
    'choice': ['input[0]', 'output'],
    'groupParts': ['inputGeometry', 'outputGeometry'],
    'condition': [
        ['firstTerm', 'secondTerm'],
        'outColorR'
    ],
    'multiplyDivide': [
        ['input1', 'input2'],
        'output'
    ],
    'plusMinusAverage': [
        'input3D[0]',
        'output3D'
    ],
    'reverse': [
        'input',
        'output'
    ],
    'clamp': [
        ['input', 'min', 'max'],
        'output'
    ],

    # Constraints
    'pointConstraint': [
        'target[0].targetWeight',
        ['constraintTranslateX', 'constraintTranslateY', 'constraintTranslateZ']
    ],
    'orientConstraint': [
        'target[0].targetWeight',
        ['constraintRotateX', 'constraintRotateY', 'constraintRotateZ']
    ],
    'parentConstraint': [
        'target[0].targetWeight',
        ['constraintTranslate', 'constraintRotate']
    ],
    'aimConstraint': [
        ['target[0].targetWeight', 'worldUpMatrix'],
        ['constraintRotate', 'constraintAim']
    ],

    # Animation
    'animCurveTA': [
        'input',
        'output'
    ],
    'animCurveTL': [
        'input',
        'output'
    ],
    'animCurveTU': [
        'input',
        'output'
    ],

    # Rendering
    'shadingEngine': [
        ['surfaceShader', 'volumeShader'],
        'outColor'
    ],
    'lambert': [
        ['color', 'transparency'],
        'outColor'
    ],
    'blinn': [
        ['color', 'specularColor'],
        'outColor'
    ],
    'aiStandardSurface': [
        ['baseColor', 'specularColor', 'emission'],
        'outColor'
    ],

    # Misc nodes
    'locator': [
        'message',
        ['inverseMatrix[0]', 'worldMatrix[0]', 'worldPosition[0]']
    ],
    'tweak': ['input[0]', 'outputGeometry[0]'],
    'transform': [
        'input',
        ['matrix', 'worldMatrix[0]']
    ],
    'joint': [
        'input',
        ['matrix', 'worldMatrix[0]', 'scale']
    ],

    # XGen
    'xgmSplineDescription': [
        ['splineData', 'displayColor'],
        'outSpline'
    ],
    'xgmModifierClump': [
        'input',
        'output'
    ],
}

# Common attribute groups for reference
TRANSFORM_ATTRS = ['translate', 'rotate', 'scale', 'visibility']
SHAPE_ATTRS = ['intermediateObject', 'lodVisibility', 'renderInfo']
CONSTRAINT_ATTRS = ['interpType', 'constraintParentInverseMatrix']
DEFORMER_ATTRS = ['envelope', 'deformerTools', 'weightList[0].weights']
