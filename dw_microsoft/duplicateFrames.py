'''
Created on 3 fevr. 2014

@author: ABaudouin
'''

import os
import shutil

"Get The directory where is located the .py"
myDir = os.getcwd()
#myDir = "Y:\\_PROD\\EPISODES\\TEST\\Background"

"list file in directory"
try:
    imageSeq = os.listdir(myDir)
except:
    imageSeq = []
"find all .exr files in my list"
imageSeq = [exrFile for exrFile in imageSeq if exrFile.endswith('.exr')]

"empty variable to list image by number"    
existingImage = []

for imgPadd in imageSeq:
    if imgPadd.endswith(".exr"):
        myNum = imgPadd.split(".")[-2]
        myNum = int(myNum)
        existingImage.append(myNum)
"sort my numbers"
existingImage = sorted(existingImage)

"trigger for while loop"
chooseFrameTrigger = False
choosePasteTrigger = False

"Frame to copy"  
while chooseFrameTrigger == False:
    if imageSeq:
        duplicatedFrame = raw_input(imageSeq[0].split(".")[0] + "\nChoose a frame to duplicate :")
    else:
        duplicatedFrame = raw_input("WARNING, no Image Detected !\nPlease, drag and drop a frame to duplicate :")
        if duplicatedFrame.split("\\") == 1:
            print "Please, drag and drop a frame or copy/paste the full path !"
            continue
    
    "try if integer is inputed" 
    try:
        duplicatedFrame = int(duplicatedFrame)
    except:
        
        "IF AN IMAGE IS DROPPED !"
        
        if duplicatedFrame.endswith(".exr"):
            myDir = "\\".join(duplicatedFrame.split("\\")[:-1])
            duplicatedFrame = int(duplicatedFrame.split(".")[-2])
            
            "list file in directory"
            imageSeq = os.listdir(myDir)
            "find all .exr files in my list"
            imageSeq = [exrFile for exrFile in imageSeq if exrFile.endswith('.exr')]

            "empty variable to list image by number"    
            existingImage = []
            
            for imgPadd in imageSeq:
                if imgPadd.endswith(".exr"):
                    myNum = imgPadd.split(".")[-2]
                    myNum = int(myNum)
                    existingImage.append(myNum)
            "sort my numbers"
            existingImage = sorted(existingImage)
            
        else:
            print ("Saisissez un nombre ou deposer une image!")
            continue
    
    "find if this frame exists"
    if duplicatedFrame not in existingImage:
        print "Choose an existing image"
        continue
    
    "trigger the first while"
    chooseFrameTrigger = True
    
    "input a frame range"
    while choosePasteTrigger == False:
        "raw input in order to have unicode"
        frameRange = str(raw_input("Choose Frame Range to Copy :"))
        
        if type(frameRange) == str:
            "remove space and find if the frame range is one frame or a frame range with '-'"
            if len(frameRange.replace(" ","").split("-")) == 1:
                "it is only one frame"
                if os.path.exists(myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(frameRange).zfill(4) + ".exr") == True:
                    "find if the frame already exist in order to override it"
                    override = raw_input("WARNING : this file already exists\nDo you want to override it.\n y/n ?")
                    if override.lower() == "y":
                        "override and rename it"
                        shutil.copy2((myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(duplicatedFrame).zfill(4) + ".exr"), (myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(frameRange).zfill(4) + ".exr"))
                    else:
                        break
                else:
                    "no need to override, just copy and rename it !"
                    shutil.copy2((myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(duplicatedFrame).zfill(4) + ".exr"), (myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(frameRange).zfill(4) + ".exr"))
            
            
            elif len(frameRange.replace(" ","").split("-")) > 1:
                "if it is a frame range :"
                print "from", frameRange.replace(" ","").split("-")[0], "to", frameRange.replace(" ","").split("-")[1]
                
                "iterate"
                for i in xrange(int(frameRange.replace(" ","").split("-")[0]), int(frameRange.replace(" ","").split("-")[1]) + 1):
                    
                    "find it already exists"
                    if os.path.exists(myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr") == True:
                        while True:
                            "prompt warning"
                            override = raw_input("WARNING : this file already exists\nDo you want to override it :" + (imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr") + ".\n y/n ?")
                            if override.lower() == "y":                    
                                print "copying :", imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr"
                                shutil.copy2((myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(duplicatedFrame).zfill(4) + ".exr"), (myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr"))
                                break
                            elif override.lower() == "n":
                                break
                            else:
                                print "please, enter 'n' or 'y' !"
                                continue
                    else:
                        "no override, prompt copy iterration"
                        print "copying :", imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr"
                        shutil.copy2((myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(duplicatedFrame).zfill(4) + ".exr"), (myDir + "\\" + imageSeq[0].split(".")[0] + "." + imageSeq[0].split(".")[1] + "." + str(i).zfill(4) + ".exr"))
                            
                print "Finish !"
                #shutil.copy2("D:\\test.txt", "D:\\temp\\test2.txt")
        
        choosePasteTrigger = True
        
#     askQuit = str(raw_input("do you want to quit ?\n y/n ?")).lower()    
#     if askQuit == "n":
#         continue
#     else:
#         "trigger last while"   