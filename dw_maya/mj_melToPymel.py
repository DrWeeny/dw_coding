__author__ = 'Mohammad,Jafarian,MARZA'

import pymel.tools.mel2py as mel2py

def convertMel(ns='cmds'):
    text = raw_input()
    print(mel2py.mel2pyStr(text, pymelNamespace=ns))
    return text

# mel2py.mel2py(input=file, pymelNamespace='cmds', outputDir='/home/abtidona/private/Documents/py_export/')