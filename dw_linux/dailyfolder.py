import os
import datetime

def make_daily_folder():

    path = '/work/21729_MOTH/dailies/CFX/PJ_Internal_Reviews'
    now = datetime.datetime.now()
    dirname = '{}{:02d}{:02d}'.format(now.year, now.month, now.day)
    fullpath = os.path.join(path, dirname)
    if not os.path.isdir(fullpath):
        os.makedirs(fullpath)
        print(dirname + ' has been created')


if __name__ == "__main__":

    make_daily_folder()