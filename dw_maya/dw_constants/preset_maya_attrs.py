gAEAttrPresetExcludeAttrs = ["doubleSided",
                             "rotateQuaternionX",
                             "rotateQuaternionY",
                             "rotateQuaternionZ",
                             "rotateQuaternionW",
                             "outStippleThreshold",
                             "face",
                             "boundary",
                             "currentDisplayLayer",
                             "useComponentPivot",
                             "currentRenderLayer",	# layer needs to exist
                             "springStiffness",
                             "springDamping",
                             "springRestLength",
                             "caching",
                             "overridePlayback",
                             "overrideEnabled",
                             "playFromCache",
                             "nodeState"]


gAEAttrPresetExcludeNodeAttrs = [
                                    "timeToUnitConversion.output",	# should be output-only
                                    "unitToTimeConversion.output",
                                    "oceanShader.outFoam",
                                    "solidNoise.outColorR",
                                    "solidNoise.outColorG",
                                    "solidNoise.outColorB",
                                    "solidNoise.outAlpha",
                                    "joint.rotatePivotX",			# normalised, so they affect one another
                                    "joint.rotatePivotY",
                                    "joint.rotatePivotZ",
                                    "hikFKJoint.rotatePivotX",
                                    "hikFKJoint.rotatePivotY",
                                    "hikFKJoint.rotatePivotZ",
                                    "samplerInfo.normalCameraX",	# normalised, so they affect one another
                                    "samplerInfo.normalCameraY",
                                    "samplerInfo.normalCameraZ",
                                    "samplerInfo.rayDirectionX",	# normalised, so they affect one another
                                    "samplerInfo.rayDirectionY",
                                    "samplerInfo.rayDirectionZ",
                                    "airField.maxDistance",		# can be set below their minimum value by presets
                                    "dragField.maxDistance",
                                    "gravityField.maxDistance",
                                    "newtonField.maxDistance",
                                    "radialField.maxDistance",
                                    "turbulenceField.maxDistance",
                                    "uniformField.maxDistance",
                                    "volumeAxisField.maxDistance",
                                    "vortexField.maxDistance",
                                    "torusField.maxDistance",
                                    "FurFeedback.realUSamples",	# dynamic/internal, affected by other attributes
                                    "FurFeedback.realVSamples",
                                    "globalStitch.updateSampling", # reset by the 'sampling' attribute
                                    "fluidShape.controlPoints.xValue",
                                    "fluidShape.controlPoints.yValue",
                                    "fluidShape.controlPoints.zValue",
                                    "fluidShape.weights",
                                    "fluidShape.seed",
                                    "stroke.pathCurve.samples", # because these depend on the actual curve thats connected
                                    "stroke.pathCurve.opposite",
                                    "cpStitcher.outputPropertyChangeNotify",
                                    "cpStitcher.outputCreaseAngleChangeNotify",
                                    "nCloth.collisionDamp",
                                    "nCloth.collisionDampMap",
                                    "nCloth.collisionDampPerVertex",
                                    "nCloth.collisionDampMapType",
                                    "nCloth.displayThickness",
                                    "nCloth.numDampingIterations",
                                    "nCloth.numSelfCollisionIterations",
                                    "nCloth.numSelfCollisionSubcycles",
                                    "nCloth.sphereTree",
                                    "nCloth.numStretchIter",
                                    "nCloth.maxStretchIter",
                                    "nCloth.stretchSubcycles",
                                    "nCloth.numBendIter",
                                    "nCloth.linksTension",
                                    "nCloth.numShearIter",
                                    "nCloth.numRigidityIterations",
                                    "nCloth.selfCrossoverCheck",
                                    "nCloth.newStretchModel",
                                    "nCloth.selfCollisionThicknessScale",
                                    "nCloth.pressureStrength",
                                    "nCloth.betterVolumeConserve",
                                    "nCloth.maxPressureIter",
                                    "nCloth.solverOverride",
                                    "nCloth.gravity",
                                    "nCloth.gravityDirectionX",
                                    "nCloth.gravityDirectionY",
                                    "nCloth.gravityDirectionZ",
                                    "nCloth.dragOffset",
                                    "nCloth.windSpeed",
                                    "nCloth.windDirectionX",
                                    "nCloth.windDirectionY",
                                    "nCloth.windDirectionZ",
                                    "nCloth.collisionDrag"]