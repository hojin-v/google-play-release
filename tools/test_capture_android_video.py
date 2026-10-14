import unittest

from capture_android_video import CaptureError, Recorder, service_state, subtitles, tap_target


class CaptureTests(unittest.TestCase):
    def test_disabled_and_zero_size_nodes_cannot_be_tapped(self):
        xml = '<hierarchy><node text="Cancel" enabled="false" bounds="[0,0][20,40]"/><node text="Cancel" enabled="true" bounds="[0,0][0,0]"/><node text="Cancel" enabled="true" bounds="[10,20][30,60]"/></hierarchy>'
        self.assertEqual(tap_target(xml, {'text': 'Cancel'}), (20, 40))
        self.assertIsNone(tap_target(xml, {'text': 'Success'}))

    def test_ambiguous_controls_fail_instead_of_tapping_arbitrary_node(self):
        xml = '<hierarchy><node text="Allow" enabled="true" bounds="[0,0][10,10]"/><node text="Allow" enabled="true" bounds="[10,10][20,20]"/></hierarchy>'
        with self.assertRaises(CaptureError):
            tap_target(xml, {'text': 'Allow'})

    def test_foreground_type_must_belong_to_the_requested_service(self):
        dump = '''* ServiceRecord{11 u0 com.example.app/.OtherService c:com.example.app}
 isForeground=true types=0x40000000
* ServiceRecord{12 u0 com.example.app/.PairingService c:com.example.app}
 isForeground=false types=0x0
'''
        self.assertEqual(service_state(dump, 'com.example.app.PairingService'),
                         {'present': True, 'foreground': False, 'type': 0})
        self.assertFalse(service_state(dump, 'com.example.app.MissingService')['present'])

    def test_android_16_dump_and_decimal_type(self):
        for kind in ['types=0x40000000', 'foregroundServiceType=1073741824']:
            dump = '* ServiceRecord{22 u0 com.example.app/.PairingService c:com.example.app}\n isForeground=true '+kind
            self.assertEqual(service_state(dump, 'com.example.app.PairingService')['type'], 1073741824)

    def test_cleanup_never_signals_a_foreign_recorder(self):
        class ForeignAdb:
            def run(self, *args):
                return b'screenrecord\x00/sdcard/someone-elses.mp4'
            def shell(self, *args):
                raise AssertionError('Must not signal the foreign process')
        recorder = Recorder(ForeignAdb(), None, {})
        recorder.pid = 123
        with self.assertRaises(CaptureError):
            recorder.finish()

    def test_captions_use_recorded_timing_and_device_scope(self):
        result = subtitles([{'start': 1.5, 'end': 12.005, 'caption': 'Cancel setup'}], 'Android emulator')
        self.assertIn('00:00:01,500 --> 00:00:12,005', result)
        self.assertIn('Android emulator\nCancel setup', result)


if __name__ == '__main__':
    unittest.main()
