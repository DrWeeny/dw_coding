'''
Created on 10 fevr. 2014

@author: ABaudouin
'''

import sys

sys.path.append("Y:\\99_DEV\\_DW_TOOLS")
import PipelineTools.Class_MayaUI as ui
reload(ui)

import xlrd
import unicodedata
import re
import os
import glob
import os.path, time

import maya.cmds as cmds

from functools import partial




#Get BKL File
#Studio List = ["MAGA", "XYZ"]
def getBKL_File(studioList = ["MAGA", "XYZ"], path = "Y:\\03_References\\FDRX_REF\\FOR_", *args):
    
    "Procedure to take episode name and associated excel file as:"
    "[ [ episode , [excel file] ] , ... ]"
    
    epBKL = {} 
    
    BKL_Folders = []
    FDRX_Episodes = []
    
    #LOOP THROUGH STUDIO
    for studio in studioList:
        
        #COLLECT FOLDERS
        BKL_Folders = os.listdir(path + studio)
        
        #LOOP THROUGH EPISODE FOLDERS
        for folder in BKL_Folders:
            
            #FIND VALID NAMES
            expression = "^F2RX_EP[0-9]{3}_(\D+)$"
            
            if re.search(expression, folder) is not None:
                
                #CREATE NICE NAME
                string = ""
                for l in folder:
                    string += str(''.join((c for c in unicodedata.normalize('NFD', unichr(ord(l))) if unicodedata.category(c) != 'Mn'))).upper()
                
                string = string.replace(" ", "_")
                
                #APPEND NICE NAME    
                FDRX_Episodes.append(string)
                
                #CREATE DIC KEYS WITH NICE NAME AND ADD THE STUDIO NAME
                epBKL[string.replace("F2RX_","")] = [studio, ["excelFile"], "path"]
            
                #COLLECT EXCEL FILES
                try:
                    fBF = path + studio + "\\" + folder + "\\01_BREAKDOWN_LIST"
                    excelFiles = os.listdir(path + studio + "\\" + folder + "\\01_BREAKDOWN_LIST")
                    epBKL[string.replace("F2RX_","")][2] = fBF
                except:
                    findBreakdownFolder = glob.glob(path + studio + "\\" + folder + "\\*")
                    for fBF in findBreakdownFolder:
                        expression02 = "breakdown"
                        if re.search(expression02, fBF.split("\\")[-1].lower()) is not None:
                            excelFiles = os.listdir(fBF)
                            epBKL[string.replace("F2RX_","")][2] = fBF
                            break
                
                excelToDic = []
                for ex in excelFiles:
                    if ex.endswith(".xls"):
                        excelToDic.append(ex)
                
                epBKL[string.replace("F2RX_","")][1] = excelToDic

             
    return epBKL
       
    
def getExcelFile(epNumber = "EP001_FRERES_MALGRE_EUX", studioList = ["MAGA", "XYZ"], path = "Y:\\03_References\\FDRX_REF\\FOR_", *args):
    
    myEpisodes = getBKL_File(studioList, path)
    
    if str(epNumber).upper() in myEpisodes.keys():
            
        temp = []
        
        for xsl in myEpisodes[epNumber][1]:
            
            myFullPath = myEpisodes[epNumber][2] + "\\" + xsl
            temp.append(myFullPath)
            
        longName = sorted(temp, key=lambda x: os.path.getmtime(x))
        shortName = [t.split("\\")[-1] for t in temp]

        return zip(shortName,longName)

    elif str(epNumber).upper() in [i[0:5] for i in myEpisodes.keys()]:
        
        temp = []
        
        for k in myEpisodes.keys():
            if k.startswith(epNumber.upper()):
                
                for xsl in myEpisodes[k][1]:
                    
                    myFullPath = myEpisodes[k][2] + "\\" + xsl
                    temp.append(myFullPath)
                    
                longName = sorted(temp, key=lambda x: os.path.getmtime(x))
                shortName = [t.split("\\")[-1] for t in temp]
                
                return zip(shortName,longName)
    
    elif type(epNumber) is int:
        if int(epNumber) in [int(i[2:5]) for i in myEpisodes.keys()]:
             
            temp = []
            
            for k in myEpisodes.keys():
                if k.startswith(("EP" + str(epNumber).zfill(3)).upper()):
                    
                    for xsl in myEpisodes[k][1]:
                        
                        myFullPath = myEpisodes[k][2] + "\\" + xsl
                        temp.append(myFullPath)
                        
                    longName = sorted(temp, key=lambda x: os.path.getmtime(x))
                    shortName = [t.split("\\")[-1] for t in temp]
                    
                    return zip(shortName,longName)
            
        
class BKL_File(object):
    '''
    classdocs
    '''

    def __init__(self, BKL_File):
        '''
        Constructor
        '''
        self.wb = xlrd.open_workbook(BKL_File)
        self.sheetName = self.wb.sheets()[0].name


    def getBGandLocation(self, shotNumber):
        
        "Function to find BG and Location"
        
        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.BG = s.cell(row, 5).value.split("\n")
                    self.Location = s.cell(row, 6).value.split("\n")
                    
                    self.BG_Location = [self.BG, self.Location]
                    
                    break
        
        return self.BG_Location  
    
    def getMainCharacters(self, shotNumber):
        
        self.myMainCharacters = []
        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.myMainCharacters = (s.cell(row, 8).value).split("\n")
                    print s.cell(row, 8).value

                    if self.myMainCharacters != ['']:
                        return self.myMainCharacters
                    else:
                        self.myMainCharacters = []
                        return self.myMainCharacters
                    
                    break
                    
    def getIncidentalCharacters(self, shotNumber):

        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.myIncidentalCharacters = s.cell(row, 9).value.split("\n") 
                    
                    if self.myIncidentalCharacters != ['']:
                        return self.myIncidentalCharacters
                    else:
                        self.myIncidentalCharacters = []
                        return self.myIncidentalCharacters
                    
                    break
            
    def getProps(self, shotNumber):

        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.myProps = s.cell(row, 11).value.split("\n") 
                    
                    if self.myProps != ['']:
                        return self.myProps
                    else:
                        self.myProps = []
                        return self.myProps
                    
                    break


    def getComments(self, shotNumber):

        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    BG_Comments = str(s.cell(row, 7).value)
                    Char_Comments = str(s.cell(row, 10).value)
                    Props_Comments = str(s.cell(row, 12).value)
                    
                    self.myComments = ''
                    
                    if BG_Comments != '':
                        self.myComments += "BG Comments :\n" + BG_Comments + "\n"  
                    if Char_Comments != '':
                        self.myComments += "Char Comments :\n" + Char_Comments + "\n"
                    if Props_Comments != '':
                        self.myComments += "Props Comments :\n" + Props_Comments + "\n"
                                            
                    if self.myComments != '':
                        return self.myComments
                    else:
                        self.myComments = 'No comment in BKL'
                        return self.myComments
                    
                    break
                
                
    def getShotDuration(self, shotNumber):

        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.myDuration = int(s.cell(row, 3).value)
                    
                    if int(self.myDuration) > 1:
                        return (str(self.myDuration) + " Frames")
                    else:
                        return (str(self.myDuration) + " Frame")
                    
                    break
            
    def getSequence(self, shotNumber):
        
        #Loop through sheets
        for s in self.wb.sheets():
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if s.cell(row, 2).value == shotNumber:
                    self.mySequence = int(s.cell(row, 1).value)
                    
                    return self.mySequence
                    
                    break
            
    def getNbfSequences(self):
        
        #Loop through sheets
        for s in self.wb.sheets():
            
            self.epSequences = []
            
            #find shot in rows
            for row in range(s.nrows):
                #find my shot
                if type(s.cell(row, 1).value) is float:
                    self.epSequences += int(s.cell(row, 1).value)
                else:
                    pass
                
                self.epSequences = list(set(self.epSequences))        
                return self.epSequences
            
    def getNbfShots(self):
        
        #Loop through sheets
        for s in self.wb.sheets():
            
            self.epShots = []
            self.epTransition = []
            self._epShotNumbers = []
            
            #find shot in rows
            for row in range(s.nrows):
                
                #find valid name of shot
                if len(str(s.cell(row, 2).value)) < 6 and len(str(s.cell(row, 2).value)) > 0:
                    
                    #Find Transtion
                    if (s.cell(row, 1).value).upper() == "TR":
                        self.epTransition.append( str(s.cell(row, 2).value) )
                        
                    #Create Hidden Variable to build lightboard
                    expression = r"^([0-9][0-9]?[0-9]?)([A-Z]?[A-Z]?)$"
                    
                    if type(s.cell(row, 2).value) is float:
                        
                        if re.search(expression, str(int(s.cell(row, 2).value))) is not None:
                            parts = re.split('(\d+)', str(s.cell(row, 2).value) )
                            self._epShotNumbers.append(int(parts[1]))

                    else:
                        
                        if re.search(expression, str(s.cell(row, 2).value)) is not None:
                            parts = re.split('(\d+)', str(s.cell(row, 2).value) )
                            self._epShotNumbers.append(int(parts[1]))                    
                        
                    
                    self.epShots.append( str(s.cell(row, 2).value) )
                else:
                    pass
                
                self.epShots = list(set(self.epShots))
                self.epShots.sort()
                self._epShotNumbers = list(set(self._epShotNumbers))  
                self._epShotNumbers.sort()
                
                return self.epShots
            
    def getUnusedShots(self):
        a = self._epShotNumbers
        return [(e1+1) for e1,e2 in zip(a, a[1:]) if e2-e1 != 1]


class SceneBuilder():
    '''
    classdocs
    '''

    def __init__(self):
        '''
        Constructor
        '''
        
        #Initialize Values
        self.setEpisode = cmds.file(q=True, loc=True).split("/")[3].upper()
        
        self.myXLS = getBKL_File()
        self.file = getExcelFile(self.setEpisode)
        
        self.setStudio = self.myXLS[self.setEpisode][0]
        
        self.setBKL = self.file
        
        #Read my bkl
        self.myBkl = BKL_File(self.file[0][1])


    def showUI(self):    
        myUI = ui.createUI()
        myUI.window("TIP_SceneBuilder", w=650, h=450, sizeable=False)

        MAIN_LAYOUT = myUI.createLayout("rowLayout", numberOfColumns=2, columnWidth2=(438, 190), adjustableColumn=2, columnAlign=(1, 'right'), columnAttach=[(1, 'both', 5), (2, 'both', 5)] )
        
        FIRST_nestedLayout = myUI.createLayout("formLayout", h=83, w=438, p = MAIN_LAYOUT)

        #FIRST_nestedLayout UI ELEMENTS
        
        #IMAGE
        image = myUI.addImage("Y:\\99_DEV\\_DW_TOOLS\\ImagesRessources\\sceneBuilder.png", h=83, w=100)

        #STUDIO ROLLOUT
        self.ui_StudioRollOut = cmds.optionMenu(w=250, label="Studio :" ,ann="Studio Detected", cc="print True")

        studio = []
        
        for i in self.myXLS.values():
            if i[0] not in studio:
                studio.append(i[0])
                
        for i in studio:
            cmds.menuItem(label=i, p=self.ui_StudioRollOut)
         
        #cmds.optionMenu(self.ui_StudioRollOut, e=True, value=self.Tin_getCamera(), cc=partial(self.ParseOptionMenu, self.Tin_setCamera , self.ui_StudioRollOut, ""))

        
        SECOND_nestedLayout = myUI.createLayout("formLayout", h=83, w=198, p = MAIN_LAYOUT)
        
        
        myUI.show()
        
        




def readBKL_example(path_input):
    wb = xlrd.open_workbook(path_input)#'D:\\temp\\F2RX_EP018_BKL_04112013.xls'

    for s in wb.sheets():
        print 'Sheet:',s.name
        for row in range(s.nrows):
            values = []
            
            if s.ncols > 14:
                clampRangeColumn = 14
            else:
                clampRangeColumn = s.ncols
            
            for col in range(clampRangeColumn):
            
                try:
                    if type(s.cell(row,col).value) is float:
                        values.append(str(s.cell(row,col).value))
                    
                    elif type(s.cell(row,col).value) is unicode:
                        #Because accents are like devils !!!
                        myAccentString = s.cell(row,col).value
                        values.append( str(''.join((c for c in unicodedata.normalize('NFD', myAccentString) if unicodedata.category(c) != 'Mn'))) )
                    
                    elif type(s.cell(row,col).value) is str:
                        values.append(str(s.cell(row,col).value))
                        
                
                except UnicodeDecodeError:
                    #Because accents are like devils !!!
                    myAccentString = s.cell(row,col).value
                    values.append( unicode(s.cell(row,col).value, errors="replace" ) )                 
                    
            print '  // '.join(values), "\n"
        print