import json
from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from screenshots import check, load, sha


def png():
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 1080, 1920, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress((b'\0' + b'\xff' * (1080 * 3)) * 1920)) + chunk(b'IEND', b'')


class ScreenshotChecks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'play').mkdir()
        (self.root / 'page.html').write_text('<h1>Current app UI</h1>')
        (self.root / 'play/release.json').write_text(json.dumps({'screenshot_config': 'play/screenshots.json', 'metadata_path': 'play/metadata'}))
        self.config = {'source_kind': 'html-preview', 'device': 'Ultra', 'page': 'page.html', 'locale': 'ko-KR', 'manifest': 'play/screenshot-manifest.json', 'scenes': [{'file': '01.png'}, {'file': '02.png'}]}
        self.save_config()
        self.directory = self.root / 'play/metadata/ko-KR/images/phoneScreenshots'
        self.directory.mkdir(parents=True)
        data = png()
        for name in ['01.png', '02.png']:
            (self.directory / name).write_bytes(data)
        _, sources = load(self.root)
        self.receipt = {'source_kind': 'html-preview', 'device': 'Ultra', 'sources': sources, 'images': [{'file': n, 'sha256': sha(self.directory / n)} for n in ['01.png', '02.png']]}
        self.save_receipt()

    def save_config(self):
        (self.root / 'play/screenshots.json').write_text(json.dumps(self.config))

    def save_receipt(self):
        (self.root / 'play/screenshot-manifest.json').write_text(json.dumps(self.receipt))

    def test_current_ordered_previews_pass(self):
        self.assertEqual([], check(self.root))

    def test_app_source_change_requires_regeneration(self):
        (self.root / 'page.html').write_text('<h1>Updated UI</h1>')
        self.assertTrue(any('stale' in issue for issue in check(self.root)))

    def test_replaced_image_and_extra_old_screenshot_are_rejected(self):
        (self.directory / '01.png').write_bytes(b'changed')
        (self.directory / 'old.png').write_bytes(png())
        issues = check(self.root)
        self.assertTrue(any('changed/missing' in issue for issue in issues))
        self.assertTrue(any('filenames/order' in issue for issue in issues))

    def test_wrong_receipt_order_is_rejected(self):
        self.receipt['images'].reverse()
        self.save_receipt()
        self.assertTrue(any('receipt order' in issue for issue in check(self.root)))

    def test_browser_previews_cannot_claim_device_capture(self):
        self.config['source_kind'] = 'device'
        self.save_config()
        with self.assertRaises(ValueError):
            load(self.root)

    def test_paths_cannot_leave_project(self):
        for field, value in [('page', '../outside.html'), ('locale', '../outside'), ('manifest', '../receipt.json')]:
            original = self.config[field]
            self.config[field] = value
            self.save_config()
            with self.assertRaises((ValueError, FileNotFoundError)):
                load(self.root)
            self.config[field] = original


if __name__ == '__main__':
    unittest.main()
