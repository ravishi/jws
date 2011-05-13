# -*- coding: utf-8 -*-
import os
import hashlib
import optparse
import urllib
import urllib2
import tempfile
import sys


class Loader(object):
    def load(self, text, language):
        raise NotImplementedError


class Storage(object):
    def store(self, identifier, fp):
        raise NotImplementedError

    def retrieve(self, identifier):
        """ Should raise ``Exception`` if not found.
        TODO: specialized exception """
        raise NotImplementedError

    def release(self, identifier):
        """ Release a identified file if it was stored here.
        TODO: specialized exception """
        raise NotImplementedError


class Backend(object):
    named_file_required = None

    def __init__(self, *args):
        pass

    def play(self, fp):
        raise NotImplementedError


class DefaultLoader(Loader):
    def load(self, text, language):
        """ ``text`` must be unicode. ``language`` doesn't. """
        data = {
            'tl': language,
            'q': text.encode('utf-8'),
        }

        url = u'http://translate.google.com/translate_tts?' + urllib.urlencode(data)
        request = urllib2.Request(url)
        request.add_header('User-Agent', 'Mozilla/5.0')

        webfile = urllib2.urlopen(request)
        return webfile


class TempfileStorage(Storage):
    fmap = {}

    def store(self, identifier, fp):
        tf = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tf.write(fp.read())
        tf.close()

        self.fmap[identifier] = tf.name

        return self.retrieve(identifier)

    def retrieve(self, identifier):
        fp = None
        fname = self.fmap.get(identifier)
        if fname is not None:
            try:
                fp = open(fname, 'rb')
            except OSError:
                pass
        if fp is None:
            raise Exception('Not found')
        return fp

    def release(self, identifier):
        fname = self.fmap.get(identifier)
        if fname is not None:
            os.unlink(fname)


class StdoutBackend(Backend):
    """ Um backend que manda o áudio para o stdout. """
    def play(self, fp):
        print fp.read()


class ExternalProgramBackend(Backend):
    """ Um backend que usa programas externos para tocar o áudio. """
    named_file_required = True

    def __init__(self, command):
        self.command = command

    def play(self, fp):
        command = self.command
        if not '%s' in self.command:
            command = self.command + ' %s'
        os.system(command % (fp.name,))


class DefaultAppBackend(ExternalProgramBackend):
    """ Tenta usar a aplicação padrão do sistema operacional. """
    def __init__(self, *args):
        cmd = {'darwin': 'open %s',
               'win32': 'cmd /c "start %s"',
               'linux2': 'xdg-open %s'}.get(sys.platform)
        super(DefaultAppBackend, self).__init__(cmd)


class PyAudioBackend(Backend):
    """ Um backend que utiliza o PyAudio para tocar o áudio. """
    def play(self, fp):
        import mad, pyaudio

        mf = mad.MadFile(fp)

        # open stream
        p = pyaudio.PyAudio()
        stream = p.open(format=p.get_format_from_width(pyaudio.paInt32),
                channels=2, rate=mf.samplerate(), output=True)

        data = mf.read()
        while data != None:
            stream.write(data)
            data = mf.read()

        stream.close()
        p.terminate()


class AoBackend(Backend):
    """ Um backend que utiliza o libao para tocar o áudio. """
    def __init__(self, backend=None):
        self.backend = backend

    def play(self, fp):
        import mad, ao

        backend = self.backend
        if backend is None:
            import sys
            backend = {
                'darwin': 'macosx',
                'win32': 'wmm',
                'linux2': 'alsa'
            }.get(sys.platform)

        if backend is None:
            raise Exception("Can't guess a usable libao baceknd."
                            "If you know a backend that may work on your system then"
                            "you can specify it using the backend options parameter.")

        mf = mad.MadFile(fp)
        dev = ao.AudioDevice(backend)

        while True:
            buf = mf.read()
            if buf is None:
                break
            dev.play(buf, len(buf))


def autodetect_external_program():
    external_programs = (
        ('mpg123', 'mplayer %s >/dev/null 2>&1'),
        ('playsound', 'playsound %s >/dev/null 2>&1'),
        ('mplayer', 'mplayer %s >/dev/null 2>&1'),
    )
    def is_exe(fpath):
        return os.path.exists(fpath) and os.access(fpath, os.X_OK)

    for program, command in external_programs:
        for path in os.environ['PATH'].split(os.pathsep):
            if is_exe(os.path.join(path, program)):
                return command

def autodetect_backend():
    # test for pyaudio
    try:
        import pyaudio
    except ImportError:
        pass
    else:
        return PyAudioBackend()

    # test for external programs
    cmd = autodetect_external_program()
    if cmd is not None:
        return ExternalProgramBackend(cmd)

    # test for ao
    try:
        import ao
    except ImportError:
        pass
    else:
        return AoBackend()

    # usar o programa padrão do sistema para tocar áudio
    print (u'Nenhum backend foi encontrado. Tentaremos tocar o áudio'
           u' usando o programa padrão do seu sistema operacional.')
    return DefaultAppBackend()


def main():
    print "Just wanna say [version 2.0]\n"
    usage = 'usage: %prog [options] [phrases]'
    option_list = [
        optparse.make_option('-h', '--help', action='store_true',
            dest='help', default=False, help=u'Show this help'),
        optparse.make_option('-l', '--language', action='store',
            type='string', dest='language', default='pt',
            help=u'Change the input language'),
        optparse.make_option('-b', '--backend', action='store',
            type='string', dest='backend', default=None,
            help=u'Specify the audio output mean'),
        optparse.make_option('-o', '--backend-options', action='store',
            type='string', dest='backend_options', default=None,
            help=u'Options to be passed to the backend'),
    ]
    parser = optparse.OptionParser(usage=usage, option_list=option_list, add_help_option=False)
    options, phrases = parser.parse_args()

    if options.help:
        parser.print_help()
        print
        print u'Available backends:'
        for cls in Backend.__subclasses__():
            print '%s %s' % (cls.__name__[:-len('Backend')].ljust(20), (cls.__doc__ or u'No description given').strip())
        return

    if options.backend is not None:
        backend = globals().get('%sBackend' % (options.backend,))(options.backend_options)
    elif options.backend_options is not None:
        print u'Você especificou as opções, mas não especificou os backends.'
        return
    else:
        backend = autodetect_backend()

    text = (u' '.join([i.decode('utf-8') for i in phrases]) or u'JWS, o falador.')

    loader = DefaultLoader()
    lfp = loader.load(text, options.language)

    if backend.named_file_required:
        identifier = hashlib.md5(':'.join([options.language, text.encode('utf-8')])).hexdigest()

        storage = TempfileStorage()
        fp = storage.store(identifier, lfp)
        lfp.close()

        backend.play(fp)

        fp.close()
    else:
        backend.play(lfp)
        lfp.close()


if __name__ == '__main__':
    main()
