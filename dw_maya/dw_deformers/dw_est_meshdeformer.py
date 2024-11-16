import sys, os
# ----- Edit sysPath -----#
rdPath = 'E:\\dw_coding\\dw_open_tools'
if not rdPath in sys.path:
    print("Add {} to sysPath".format(rdPath))
    sys.path.insert(0, rdPath)

from maya import cmds, mel

from dw_maya.dw_decorators import acceptString


@acceptString('drivenMesh')
def eST_meshDeformer(drivenMesh=list, driverMesh=str, **kwargs):

    '''
    Args :
        cage               = string     - the driver mesh node name.
                                          ( default: the 1st selection )
        objs               = [string]   - a list of geometry node names to be deformed.
                                          ( default: after 2nd selections )


    Kwargs:

              n|name           = string     - a node name expression of new eSTmeshDeformer
                                              node.
                                              ( default: [ '~', '~[meshDeformer]', '(@)~' ] )
              s|smooth         = int        - smooth level of the driver mesh output.
                                              ( default: 0 )
             kb|keepBorder     = bool       - do not smooth border edges.
                                              this option effects with smooth option.
                                              ( default: False )
              l|local          = bool       - use local space to setting up.
                                              ( default: False )
             ec|echoResult     = bool       - print binding information after creation.
                                              ( default: False )
              m|mode           = string     - valid values are 'fixInput', 'updatePoints',
                                              'updateBinding' or 'rebind'.
                                              ( default: 'fixInput' )
             cm|centeringMethod = string    - valid values are 'medianPoint', 'average' or
                                              'centerOfBindingBox'.
                                              ( default: 'medianPoint' )
             ds|depthSource    = string     - valid values are 'face' or 'vertex'.
                                              ( default: 'face' )
             dm|driverMatrix   = mixed      - the driver matrix. when EMatrix was specified to
                                              this option, it will be set in static. if string
                                              based value was specified, it will be connected
                                              as plug name. this option is ignored when local
                                              option was set to False.
                                              ( default: do nothing )
            bdm|bindDriverMesh = string     - a substitute driver mesh to getting original
                                              point positions when rebinding.
                                              ( default: None )
             bg|bindGeometry   = [(int,string)]  - a list of tuples that contains index of objs
                                                   and a substitute driven geometry to getting
                                                   original point positions when rebinding.
                                                   ( default: [] )
            csg|connectSubstituteGeometries - create connections with specified bindDriverMesh
                                              and bindGeometries.
                                              ( default: False )
            ump|useMP          = bool       - if True, use multithread when update binding or
                                              rebinding.
                                              ( default: False )
            pfp|priorFixedPints = bool      - prior fixed points when (re)binding time.
                                              ( default: False )
            idd|ignoreDriverDisconnection = bool  - if True then suppress rebinding when the
                                                    driver mesh has been disconnected.
                                                    when using a referenced mesh as a driver,
                                                    set this option to True.
                                                    ( default: False )
            before             = bool       -
                                              ( default: False )
            after              = bool       -
                                              ( default: False )
            split              = bool       -
                                              ( default: False )
            parallel           = bool       -
                                              ( default: False )
            exclusive          = bool       -
                                              ( default: False )
            partition          = string     -
                                              ( default: '' )

    Return Value:
            string   - a new eSTmeshDeformer node name.

    '''

    try:
        cmds.loadPlugin("eSTcmds.so")
    except:
        return

    from eST.tools.setup.setupMeshDeformer import setupMeshDeformer
    o = setupMeshDeformer(cage = driverMesh, objs = drivenMesh, echoResult = True, **kwargs)
    return o

    # help(eST.tools.setup.setupMeshDeformer)