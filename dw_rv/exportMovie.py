
import subprocess


cmd = '/net/prime3-fs/ifs/marza/team/rnd/tools/shell/rv/7.1.2/all/linux/x64/bin/rvio_hw'
arg0 = ["-v",
        "-err-to-out",
        "/tmp/temp_13442_3.rv",
        "-o",
        "/net/prime3-fs/ifs/marza/proj/fuji2019/work/Character/longclaw/sim/alexis/feathers/images/gymRender/v003/gymRender_v003_beauty_test.mov",
        "-t",
        "1-25"]
arg1 = 1
img_seq = "/net/prime3-fs/ifs/marza/proj/fuji2019/work/Character/longclaw/sim/alexis/feathers/images/gymRender/v003/beauy/Character_longclaw_feathers_gymRender_v003_beauty.%04d.exr"
img_seq = "/marza/proj/fuji2019/work/Character/longclaw/sim/alexis/feathers/images/gymRender/v003/beauy/Character_longclaw_feathers_gymRender_v003_beauty.%04d.exr"

ffmpeg = '/marza/team/rnd/tools/shell/ffmpeg/3.1.3/all/linux/bin/ffmpeg'
args = [ffmpeg, '-start_number 1', '-f image2', '-r 25', '-i {}'.format(img_seq), '-vcodec libx264', '-qscale 8', 'movFile.mov']

test = 'ffmpeg -framerate 24 -i {} -r 30 video.mov'.format(img_seq)

p = subprocess.Popen(test, stdout=subprocess.PIPE)
out, err = p.communicate()
print(out, err)