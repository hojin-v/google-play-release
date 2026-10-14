"""Submission-critical validator checks. Run: python3 -m unittest discover -s .../scripts."""
import struct
import unittest
import xml.etree.ElementTree as ET
from release import elf_issues, manifest_issues


def elf(alignment, relro_end=0x8000):
    data = bytearray(256)
    data[:6] = b"\x7fELF\x02\x01"
    struct.pack_into("<Q", data, 32, 64)
    struct.pack_into("<HH", data, 54, 56, 2)
    struct.pack_into("<IIQQQQQQ", data, 64, 1, 5, 0, 0, 0, 128, 128, alignment)
    struct.pack_into("<IIQQQQQQ", data, 120, 0x6474E552, 4, 0, 0x4000, 0, relro_end - 0x4000, relro_end - 0x4000, 1)
    return bytes(data)


class SubmissionValidation(unittest.TestCase):
    def test_rejects_4kb_native_library_and_bad_relro(self):
        self.assertTrue(elf_issues(elf(4096)))
        self.assertTrue(elf_issues(elf(16384, 0x9000)))
        self.assertEqual([], elf_issues(elf(16384)))

    def test_rejects_wrong_app_and_external_installer(self):
        doc = ET.fromstring('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.other.app">
          <uses-sdk android:targetSdkVersion="34"/>
          <uses-permission android:name="android.permission.REQUEST_INSTALL_PACKAGES"/>
          <application android:debuggable="true"><service android:name="com.other.app.Updater"/></application>
        </manifest>''')
        config = {"package_name": "com.test.app", "min_target_sdk": 36,
                  "forbidden_permissions": ["android.permission.REQUEST_INSTALL_PACKAGES"]}
        self.assertEqual(4, len(manifest_issues(doc, config)))

    def test_requires_foreground_service_declaration(self):
        doc = ET.fromstring('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.test.app">
          <uses-sdk android:targetSdkVersion="36"/>
          <application><service android:name="com.test.app.Pairing"/></application>
        </manifest>''')
        config = {"package_name": "com.test.app", "min_target_sdk": 36,
                  "required_foreground_services": [".Pairing"]}
        self.assertTrue(manifest_issues(doc, config))

    def test_bundletool_numeric_special_use_flags(self):
        doc = ET.fromstring('''<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.test.app">
          <uses-sdk android:targetSdkVersion="36"/>
          <uses-permission android:name="android.permission.FOREGROUND_SERVICE_SPECIAL_USE"/>
          <application><service android:name="com.test.app.Pairing" android:foregroundServiceType="0x40000000">
          <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" android:value="User initiated pairing"/>
          </service></application>
        </manifest>''')
        config = {"package_name": "com.test.app", "min_target_sdk": 36,
                  "required_foreground_services": [".Pairing"]}
        self.assertEqual([], manifest_issues(doc, config))


if __name__ == "__main__":
    unittest.main()
