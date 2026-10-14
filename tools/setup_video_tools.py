#!/usr/bin/env python3
"""Install the pinned imageio-ffmpeg Linux x86_64 binary without pip or root."""
import hashlib
import io
import json
from pathlib import Path
import platform
import urllib.request
import zipfile


def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise SystemExit('Install ffmpeg for your OS and pass --ffmpeg to capture_android_video.py')
    metadata = json.load(urllib.request.urlopen('https://pypi.org/pypi/imageio-ffmpeg/0.6.0/json', timeout=30))
    wheel = next(x for x in metadata['urls'] if x['filename'].endswith('manylinux2014_x86_64.whl'))
    blob = urllib.request.urlopen(wheel['url'], timeout=60).read()
    if hashlib.sha256(blob).hexdigest() != wheel['digests']['sha256']:
        raise SystemExit('FFmpeg wheel checksum mismatch')
    folder = Path.home()/'.local/share/google-play-release/video'
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        binary = next(n for n in archive.namelist() if n.startswith('imageio_ffmpeg/binaries/ffmpeg-linux'))
        target = folder/'ffmpeg'
        target.write_bytes(archive.read(binary))
        target.chmod(0o755)
    (folder/'download.json').write_text(json.dumps({'source': wheel['url'],
        'wheel_sha256': wheel['digests']['sha256'],
        'binary_sha256': hashlib.sha256(target.read_bytes()).hexdigest()}, indent=2)+'\n')
    print(target)


if __name__ == '__main__':
    main()
