#!/usr/bin/env python
#----------------------------------------------------------------------------#
#------------------------------------------------------------------ HEADER --#

"""
@author:
    abtidona

@description:
    this is a description

@applications:
    - groom
    - cfx
    - fur
"""

#----------------------------------------------------------------------------#
#----------------------------------------------------------------- IMPORTS --#

# built-in
# internal
import maya.cmds as cmds

# external


#----------------------------------------------------------------------------#
#----------------------------------------------------------------- GLOBALS --#


#----------------------------------------------------------------------------#
#---------------------------------------------------------------   CLASSES --#


#----------------------------------------------------------------------------#
#--------------------------------------------------------------- FUNCTIONS --#

import dw_nucleus_utils as dwnx
reload(dwnx)

ncloth = 'winnie:shirt_NCLOTH'
xml = '/work/21729_MOTH/cache/nCache/winnie/nucleus1/shirt/shirt_v006.xml'
geometries = ['winnie:shirt_NCLOTHShape']
channelNames = False

fileName = xml

if fileName == "":
    cmds.error("m_doImportCacheFile.kNoFileSpecified")

channels = cmds.cacheFile(q=1, channelName=1, fileName=fileName)

sel = []
if len(geometries) <= 0:
    sel = dwnx.getGeometriesToCache()
else:
    sel = geometries

count = len(sel)
if count > len(channels):
    format = "m_doImportCacheFile.kTooFewChannels"
    channelCount = str(len(channels))
    selCount = str(count)
    errMsg = str(cmds.format(format, stringArg=[channelCount, selCount]))
    cmds.error(errMsg)

currObj = sel[0]
nBase = dwnx.find_type_in_history(currObj, "nBase", 0, 1)
hsys = dwnx.find_type_in_history(currObj, "hairSystem", 0, 1)
attachAttrs = []
multiChannel = 0


if (len(channels) > count):
    if len(nBase):
        if cmds.nodeType(nBase) == "nCloth":
            multiChannel = 1
            # if there are more channels than objects,
            # we probably need a bunch of connections
            # (unless its nParticles,
            # in which case it will just be one fat connection)
            # if an nCloth cache has more than just postions,
            # we should connect the other attrs
            # and nHair  has a bunch of connections
            # (fluids are done separately because of
            # more complex attribute matching problems)
            currObj = nBase

    if len(hsys):
        multiChannel = 1
        currObj = hsys

    if multiChannel:
        multiChannel = len(channels)


if not multiChannel:
    for ii in range(0, count):
        currObj = sel[ii]
        channelToUse = ""
        if len(channelNames) > 0:
            channelToUse = channelNames[ii]
        else:
            channelToUse = str(_findChannelForObject(ii, channels, currObj))

        if len(existingCaches) == 0:
            inputPointsAttr = ""
            inputRangeAttr = ""
            # first decide if it is an ncloth or a geometry cache
            #
            nBase = dwnx.find_type_in_history(currObj, "nBase", 0, 1)
            if len(nBase):
                inputPointsAttr = (nBase + ".positions")
                inputRangeAttr = (nBase + ".playFromCache")

            cacheFile = cmds.cacheFile(attachFile=True, fileName=fileName,
                           ia=inputPointsAttr, channelName=channelToUse)
            cmds.connectAttr((cacheFile + ".inRange"),
                             inputRangeAttr)
            if len(nBase):
                if cmds.nodeType(nBase) == "nParticle":
                    cmds.connectAttr((cacheFile + ".outCacheArrayData"),
                                     (nBase + ".cacheArrayData"),
                                     f=1)

else:
    existingCaches = findExistingCaches(currObj)
    # we assume we're just dealing with one object with multiple connections
    # currently hair system, or nCloth with velocity/internalState
    if len(existingCaches) == 0:
        inputRangeAttr = (currObj + ".playFromCache")
        attachCmd = ("cacheFile -attachFile -fileName \"" + fileName + "\"")
        chn = ""
        for chn in channels:
            attachCmd += (" -channelName " + str(chn))

        for chn in attachAttrs:
            attachCmd += (" -ia " + str(chn))

        cacheFile = str(cmds.mel.eval(attachCmd))
        cmds.connectAttr((cacheFile + ".inRange"),
                         inputRangeAttr)




