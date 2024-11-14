__author__ = 'abaudoin'

args = ['ffmpeg', '-start_number 101', '-f image2', '-r 25', '-i inputSequence%04d.exr', '-vcodec mjpeg', '-qscale 8', 'movFile']

args = ['ffmpeg', '-start_number 101', '-f image2', '-r 25', '-i inputSequence%04d.exr', '-vcodec libx264', '-qscale 8', 'movFile']

#ffmpeg -y -start_number 101 -r 25 -i /u/max/Users/abaudoin/Files/image/MAX/S1335/P2005/Cfx_Occ_Render/MAX_S1335_P2005-Cfx_Occ_Render/MAX_S1335_P2005-Cfx_Occ_Render.%04d.exr -vf lutrgb=r=gammaval(0.45454545):g=gammaval(0.45454545):b=gammaval(0.45454545) -vcodec libx264 -qscale 8 /u/abaudoin/Downloads/1335_2005.mov


#ffmpeg /u/max/Users/abaudoin/Files/image/MAX/S1335/P2005/Cfx_Occ_Movie/MAX_S1335_P2005-Cfx_Occ_Movie.mov -vcodec libx264 -r 24 /u/abaudoin/Downloads/1335_2005.mov
