#!/usr/bin/env python3
"""Run a configured real Android UI scenario and record its screen with ADB."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET


class CaptureError(RuntimeError):
    pass


def tap_target(xml, selector):
    """Return an unambiguous visible, enabled UI node's center."""
    nodes = []
    for node in ET.fromstring(xml).iter('node'):
        if node.get('enabled') != 'true':
            continue
        if not all(node.get(key) in (value if isinstance(value, list) else [value])
                   for key, value in selector.items()):
            continue
        bounds = re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', node.get('bounds', ''))
        if bounds:
            x1, y1, x2, y2 = map(int, bounds.groups())
            if x2 > x1 and y2 > y1:
                nodes.append(((x1+x2)//2, (y1+y2)//2))
    if len(nodes) > 1:
        raise CaptureError('UI selector matches multiple nodes; refine the scenario selector')
    return nodes[0] if nodes else None


def service_state(dump, service):
    blocks = re.split(r'(?=\* ServiceRecord\{)', dump)
    name = service.rsplit('.', 1)[-1]
    for block in blocks:
        if re.search(r'ServiceRecord\{[^\n]*/[^\n]*\b' + re.escape(name) + r'\b', block):
            kind = re.search(r'(?:types|foregroundServiceType)=(0x[\da-fA-F]+|\d+)', block)
            return {'present': True, 'foreground': 'isForeground=true' in block,
                    'type': int(kind.group(1), 0) if kind else None}
    return {'present': False, 'foreground': False, 'type': None}


class Adb:
    def __init__(self, binary, serial, port):
        self.prefix = [binary, '-P', str(port), '-s', serial]

    def run(self, *args, timeout=30):
        r = subprocess.run(self.prefix + list(args), stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, timeout=timeout)
        if r.returncode:
            raise CaptureError(r.stderr.decode(errors='replace').strip() or 'ADB command failed')
        return r.stdout

    def shell(self, *args, timeout=30):
        # ADB invokes an Android shell: quote every argument for that shell too.
        return self.run('shell', shlex.join(args), timeout=timeout).decode(errors='replace').strip()

    def save(self, target, *args):
        with target.open('wb') as f:
            r = subprocess.run(self.prefix + list(args), stdout=f, stderr=subprocess.PIPE, timeout=60)
        if r.returncode:
            raise CaptureError(r.stderr.decode(errors='replace').strip())


class Recorder:
    def __init__(self, adb, output, config):
        self.adb, self.output, self.config = adb, output, config
        self.remote = '/sdcard/play-video-' + uuid.uuid4().hex + '.mp4'
        self.pid = None
        self.events = []
        self.started = None

    def start(self):
        command = ('nohup screenrecord --bit-rate 6000000 --time-limit 170 '
                   + shlex.quote(self.remote) + ' > ' + shlex.quote(self.remote+'.log')
                   + ' 2>&1 < /dev/null & echo $!')
        self.pid = int(self.adb.run('shell', command).decode().strip())
        self.started = time.monotonic()
        time.sleep(1)
        if not self.adb.shell('kill', '-0', str(self.pid)) == '':
            raise CaptureError('Screen recorder did not start')

    def ui(self):
        remote = '/sdcard/play-ui-' + self.remote.rsplit('-', 1)[1] + '.xml'
        try:
            self.adb.shell('uiautomator', 'dump', remote, timeout=15)
            return self.adb.run('exec-out', 'cat', remote).decode()
        finally:
            self.adb.shell('rm', '-f', remote)

    def tap(self, step):
        deadline = time.monotonic() + step.get('timeout', 12)
        while time.monotonic() < deadline:
            xml = self.ui()
            point = tap_target(xml, step['selector'])
            if point:
                self.adb.shell('input', 'tap', *(str(x) for x in point))
                return True
            time.sleep(.5)
        if step.get('optional'):
            return False
        raise CaptureError('Required UI action was not visible: '+step.get('caption', 'tap'))

    def assert_service(self, active):
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            dump = self.adb.shell('dumpsys', 'activity', 'services', self.config['package'])
            state = service_state(dump, self.config['service'])
            passed = (state['foreground'] and state['type'] == self.config['service_type']) if active else not state['present']
            if passed:
                return dump, state
            time.sleep(.5)
        raise CaptureError('Foreground service assertion failed: '+json.dumps(state))

    def execute(self):
        for index, step in enumerate(self.config['steps']):
            if time.monotonic()-self.started > 140:
                raise CaptureError('Scenario exceeded recording budget; refusing a truncated success')
            begin = time.monotonic()-self.started
            action = step['action']
            event = {'action': action, 'caption': step['caption'], 'start': round(begin, 3)}
            print(step['caption'], flush=True)
            if action == 'launch':
                self.adb.shell('am', 'start', '-W', '-n', self.config['component'])
            elif action == 'tap':
                event['performed'] = self.tap(step)
                if not event['performed']:
                    continue
            elif action == 'notifications':
                self.adb.shell('cmd', 'statusbar', 'expand-notifications')
            elif action == 'swipe':
                self.adb.shell('input', 'swipe', *(str(x) for x in step['coordinates']))
            elif action == 'back':
                self.adb.shell('input', 'keyevent', 'KEYCODE_BACK')
            elif action == 'service':
                dump, event['service'] = self.assert_service(step['active'])
                (self.output/f'{index:02d}-service.txt').write_text(dump)
            else:
                raise CaptureError('Unsupported scenario action: '+action)
            time.sleep(step.get('hold', 2))
            self.adb.save(self.output/f'{index:02d}.png', 'exec-out', 'screencap', '-p')
            event['end'] = round(time.monotonic()-self.started, 3)
            self.events.append(event)

    def finish(self):
        if self.pid is None:
            return
        # Never signal another recorder, including one started by the phone's owner.
        command = self.adb.run('exec-out', 'cat', f'/proc/{self.pid}/cmdline').decode(errors='replace')
        if 'screenrecord' not in command or self.remote not in command:
            raise CaptureError('Owned recorder is gone; raw recording may be incomplete')
        self.adb.shell('kill', '-2', str(self.pid))
        time.sleep(2)
        self.adb.save(self.output/'raw.mp4', 'exec-out', 'cat', self.remote)
        self.adb.save(self.output/'screenrecord.log', 'exec-out', 'cat', self.remote+'.log')
        if (self.output/'raw.mp4').stat().st_size < 1024:
            raise CaptureError('Recorder produced no usable video')
        self.adb.shell('rm', '-f', self.remote, self.remote+'.log')
        self.pid = None


def timestamp(seconds):
    ms = max(0, round(seconds*1000))
    return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'


def subtitles(events, scope):
    return '\n\n'.join(f'{i+1}\n{timestamp(e["start"])} --> {timestamp(e["end"])}\n'
                        f'{scope}\n{e["caption"]}' for i, e in enumerate(events))+'\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--serial', required=True, help='explicit device serial; never selects a phone implicitly')
    p.add_argument('--adb', default=os.environ.get('ADB_BINARY') or shutil.which('adb') or str(Path.home()/'android-sdk/platform-tools/adb'))
    p.add_argument('--adb-port', type=int, default=5037)
    p.add_argument('--output', type=Path, required=True, help='new directory for this capture')
    p.add_argument('--reset-app', action='store_true', help='erase ONLY the configured app data on this test device')
    p.add_argument('--emulator-setup', action='store_true', help='enable developer options on an emulator; rejected on real phones')
    p.add_argument('--ffmpeg', default=shutil.which('ffmpeg') or str(Path.home()/'.local/share/google-play-release/video/ffmpeg'))
    a = p.parse_args()
    c = json.loads(a.config.read_text())
    adb = Adb(a.adb, a.serial, a.adb_port)
    if adb.run('get-state').decode().strip() != 'device':
        raise CaptureError('Unlock and authorize the selected device for USB debugging first')
    emulator = adb.shell('getprop', 'ro.kernel.qemu') == '1'
    c['scope'] = ('Android emulator | ' if emulator else 'Physical Android device | ') + c['scope']
    if a.emulator_setup and not emulator:
        raise CaptureError('--emulator-setup never changes a physical phone')
    package = adb.shell('dumpsys', 'package', c['package'])
    version = re.search(r'versionName=(\S+)', package)
    code = re.search(r'versionCode=(\d+)', package)
    if not version or not code:
        raise CaptureError('Install the configured real APK on the selected device first')
    if re.search(r'mShowingLockscreen=true|isStatusBarKeyguard=true', adb.shell('dumpsys', 'window', 'policy')):
        raise CaptureError('Unlock the screen before capturing; the script does not bypass the lock')
    a.output = a.output.resolve()
    a.output.mkdir(parents=True, exist_ok=False)
    report = {'scenario': c['name'], 'status': 'failed', 'emulator': emulator,
              'package': c['package'], 'version_name': version[1], 'version_code': int(code[1]),
              'device': {k: adb.shell('getprop', 'ro.product.'+k) for k in ['manufacturer', 'model']},
              'sdk': adb.shell('getprop', 'ro.build.version.sdk'), 'audio_recorded': False,
              'pairing_success_verified': False, 'manufacturer_camera_verified': False,
              'scope': c['scope'], 'remote_recording': None}
    if a.emulator_setup:
        adb.shell('settings', 'put', 'global', 'development_settings_enabled', '1')
    if a.reset_app:
        if adb.shell('pm', 'clear', c['package']) != 'Success':
            raise CaptureError('Could not reset configured test app')
    r = Recorder(adb, a.output, c)
    report['remote_recording'] = r.remote
    try:
        r.start()
        r.execute()
        report['status'] = 'passed'
    except (CaptureError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
        report['error'] = str(error)
    finally:
        try:
            r.finish()
        except (CaptureError, subprocess.TimeoutExpired) as error:
            report['status'] = 'failed'
            report['retrieval_error'] = str(error)
        report['events'] = r.events
        (a.output/'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    if (a.output/'raw.mp4').is_file():
        report['raw_sha256'] = hashlib.sha256((a.output/'raw.mp4').read_bytes()).hexdigest()
        (a.output/'captions.srt').write_text(subtitles(r.events, c['scope']))
        if Path(a.ffmpeg).is_file():
            fonts = Path.home()/'.local/share/fonts'
            subprocess.run([a.ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', 'raw.mp4',
                            '-vf', f"subtitles=captions.srt:fontsdir={fonts}:force_style='FontName=Malgun Gothic,FontSize=15,Outline=2,MarginV=15'",
                            '-c:v', 'libx264', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p',
                            '-movflags', '+faststart', 'captioned.mp4'], cwd=a.output, check=True)
            report['captioned_sha256'] = hashlib.sha256((a.output/'captioned.mp4').read_bytes()).hexdigest()
        (a.output/'evidence.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(a.output, flush=True)
    if report['status'] != 'passed':
        raise CaptureError(report.get('error') or report.get('retrieval_error') or 'Capture failed')


if __name__ == '__main__':
    try:
        main()
    except (CaptureError, OSError, ValueError, ET.ParseError, subprocess.SubprocessError) as e:
        print('Capture failed: '+str(e), file=sys.stderr)
        sys.exit(1)
