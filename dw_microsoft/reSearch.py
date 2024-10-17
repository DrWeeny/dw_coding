'''
Created on 31 janv. 2014

@author: DW
'''

import re

def reSearch(expression = "[a-zA-Z]", searchList = []):
    
    items = []
    for i in searchList:
        if re.search(expression, i) is not None:
            items.append(i)
    
    return items