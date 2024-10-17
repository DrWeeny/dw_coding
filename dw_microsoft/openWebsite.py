import webbrowser

webbrowser.open_new_tab("http://foot2rue.teleimage.spiprod.com/")

import urllib
import urllib2

name =  "name field"
data = {
        "name" : name 
       }

encoded_data = urllib.urlencode(data)
content = urllib2.urlopen("http://foot2rue.teleimage.spiprod.com/",
        encoded_data)
print content.readlines()