import unittest
from release_identity import version_issues, launcher_classes

class ProductionIdentityTests(unittest.TestCase):
    def test_beta_manifest_is_not_production(self):
        for value in ['2.2.3-beta.1', '1.0.0-RC2', '3.0-preview', '4.1-debug']:
            self.assertTrue(version_issues(value, ''))
        self.assertEqual([], version_issues('2.2.4', ''))

    def test_correct_manifest_does_not_hide_inlined_beta(self):
        code = 'const-string v3, "2.2.3-beta.1"'
        self.assertTrue(version_issues('2.2.3', code))

    def test_old_stable_inline_version_and_jumbo_are_detected(self):
        self.assertTrue(version_issues('2.2.4', 'const-string/jumbo v1, "2.2.3"'))
        self.assertEqual([], version_issues('2.2.4', 'const-string v1, "2.2.4"'))

    def test_runtime_metadata_and_unrelated_strings_are_accepted(self):
        self.assertEqual([], version_issues('2.2.4', 'invoke-virtual {v0}, Landroid/content/pm/PackageManager;->getPackageInfo()\nconst-string v2, "127.0.0.1"'))

    def test_unrelated_smali_escape_does_not_abort_the_audit(self):
        self.assertEqual([], version_issues('2.2.4', r'''const-string v0, "don\'t"'''))

    def test_explicit_non_version_literal_allowlist_is_supported(self):
        self.assertEqual([], version_issues('2.2.4', 'const-string v0, "1.2.840"', ['1.2.840']))

    def test_launcher_namespace_can_differ_from_application_id(self):
        xml = '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.example.app"><application><activity android:name="com.example.ui.Home"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'
        self.assertEqual(['com.example.ui.Home'], launcher_classes(xml))

if __name__ == '__main__': unittest.main()
