import os
import subprocess

try:
    import winsound
except:
    pass

def get_linux_volume():
    p = subprocess.Popen(["amixer", "get", "Master"],
                         stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE)

    output, err = p.communicate(b"input data that is passed to subprocess' stdin")
    rc = p.returncode

    for i in output.split('\n'):
        if i.strip().startswith('Front Left'):
            volume = int(i.split('%')[0].split('[')[-1])
            break
        elif len(i.split('%')) > 1:
            volume = int(i.split('%')[0].split('[')[-1])
            break
        else:
            volume = None
    return volume


def playAudio(audio_file_path = "../dw_open_tools/audio_files/PeonReady1.mp3"):
    #amixer set Master 100
    vol = get_linux_volume()
    if vol:
        if vol > 60:
            subprocess.call(["amixer", "set", "Master", str(vol/2)])
        subprocess.call(["ffplay", "-nodisp", "-autoexit", audio_file_path])
        if vol > 60:
            subprocess.call(["amixer", "set", "Master", str(vol)])
    else:
        subprocess.call(["ffplay", "-nodisp", "-autoexit", audio_file_path])


def win_sound_test():
    duration = 1000  # millisecond
    freq = 440  # Hz
    winsound.Beep(freq, duration)

def linux_sound_test():
    duration = 1  # second
    freq = 440  # Hz
    os.system('play --no-show-progress --null --channels 1 synth %s sine %f' % (duration, freq))


def sox_play(file_path, *args):
    '''
    source : http://sox.sourceforge.net/sox.html
    examples : https://linux.die.net/man/1/play

    trim 0 1
    The syntax is sox input output trim <start> <duration>


    Args:
        file_path ():
        *args ():

    Returns:

    '''
    validate = ['reverse', 'copy', 'rate', 'avg', 'stat', 'vibro', 'lowp', 'highp', 'band', 'reverb']

    args_list = ['play', file_path]
    trim = ['trim', 0, 2]
    fade = ['fade','h',0.1,1.5,1]
    if not 'trim' in args:
        args_list+=[str(i) for i in trim]
    if not 'fade' in args:
        args_list+=[str(i) for i in fade]

    for a in args:
        args_list.append(str(a))
    args_list = [str(i) for i in args_list]
    subprocess.Popen(args_list)