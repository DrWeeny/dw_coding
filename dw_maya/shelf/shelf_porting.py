import os
import maya.cmds as cmds

def printXGenPath():
    directory = cmds.workspace(fileRuleEntry='scene')
    char = cmds.file(q=True, sn=True).split('/')[-2]
    files = os.listdir(os.path.join(directory, char))
    xgen = [i for i in files if i.endswith('.xgen')][0]
    xgen_path = os.path.join(directory, char, xgen)
    cmd = ['kwrite', xgen_path]
    # p = subprocess.Popen(cmd)
    
    with open(xgen_path, 'r') as reader:
        # Further file processing goes here
        for line in reader.readlines():
            if 'xgDataPath' in line:
                print(line)
                break

# execute this on the scene you want to transfer
import locale
locale.setlocale(locale.LC_ALL, '')

# save the file to the target wip

# copy xgen to this phase
mel.eval( 'rfxXgenProjectUtils' )
mel.eval( 'rfxXgenProjectUtils.ui.copyToThisPhase()')

# save twice
cmds.setAttr('persp.tx', 15)
cmds.file(save=True)
cmds.setAttr('persp.tx', 0)
cmds.file(save=True)


# verify xgen path in kwrite, nlarge or any editor
printXGenPath()

# rename collection and below with comet
src_name = 'genMediumMale'
trg_name = 'genTallMale'
mel.eval('source eTools_cometRename.mel; executeRepeatableCmd "cometRename()";')
# xg.renamePalette("genMediumMaleDefault","genTallMaleDefault")
# xgui.refreshDescriptionEditor()


# fix button need to be hit one to three times (change path of patches and other xgen dependencies)
import xgenm as xg
for pal in xg.palettes():
    print 'Fixing patch names for "%s" collection' % pal
    xg.fixPatchNames( pal )
for pal in xg.palettes():
    print 'Fixing patch names for "%s" collection' % pal
    xg.fixPatchNames( pal )
for pal in xg.palettes():
    print 'Fixing patch names for "%s" collection' % pal
    xg.fixPatchNames( pal )
# save and exit
cmds.setAttr('persp.tx', 15)
cmds.file(save=True)
cmds.setAttr('persp.tx', 0)
cmds.file(save=True)

# open again and when there is the foreign nodes prompt, hit the button switch

# now you can save and run your modelUpdate



