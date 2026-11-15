import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from release_gate import approve, binding, review, validate_approval, digest
from release import main, matching_apk_issues, artifact_checks, validate_preparation, preparation_proof, store_issues
from doctor import inspect


class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / 'play/metadata').mkdir(parents=True)
        (self.root / 'play/metadata/title.txt').write_text('Another app')
        self.config = {'package_name': 'com.example.other', 'metadata_path': 'play/metadata',
                       'apk_path': 'test.apk', 'output_path': 'build/releases',
                       'gradle_tasks': [':app:testReleaseUnitTest', ':app:lintRelease', ':app:bundleRelease'],
                       'production_device_checks': [{'id': 'current-device', 'min_sdk': 37, 'device_pattern': 'NewPhone'}]}
        self.save_config()
        self.aab = self.root / 'app.aab'
        with zipfile.ZipFile(self.aab, 'w') as z:
            z.writestr('base/dex/classes.dex', b'Play code')
            z.writestr('base/lib/arm64-v8a/lib.so', b'Play library')
        with zipfile.ZipFile(self.root / 'test.apk', 'w') as z:
            z.writestr('classes.dex', b'Play code')
            z.writestr('lib/arm64-v8a/lib.so', b'Play library')
        self.audit = {'package_name': 'com.example.other', 'version_code': 12, 'version_name': '1.2.0',
                      'aab_sha256': digest(self.aab), 'technical_issues': [], 'store_issues': []}
        self.evidence = self.root / 'evidence.json'
        self.approval = self.root / 'approval.json'

    def save_config(self):
        (self.root / 'play/release.json').write_text(json.dumps(self.config))

    def observed(self):
        review(self.root, self.config, self.aab, self.audit, self.evidence)
        data = json.loads(self.evidence.read_text())
        data['device_checks'][0].update(status='passed', device='NewPhone model X', os='Android 17', sdk=37,
             installation='play-variant-apk', tested_apk_sha256=digest(self.root / 'test.apk'),
             evidence='Physical test: launch, use the main action, verify actual resulting behavior.')
        self.evidence.write_text(json.dumps(data))

    def authorize(self):
        approve(self.root, self.config, self.aab, self.audit, self.evidence,
                'Release this reviewed 1.2.0 to production at 10%', '0.1', self.approval)

    def verify(self, rollout='0.1'):
        return validate_approval(self.root, self.config, self.aab, self.audit,
                                 self.approval, self.evidence, rollout)

    def test_approved_other_app_works_without_shit_configuration(self):
        self.observed(); self.authorize()
        self.assertEqual('com.example.other', self.verify()['artifact']['package_name'])

    def test_pending_device_check_cannot_be_approved(self):
        review(self.root, self.config, self.aab, self.audit, self.evidence)
        with self.assertRaisesRegex(ValueError, 'not passed'):
            self.authorize()
        self.assertFalse(self.approval.exists())

    def test_wrong_device_old_os_debug_apk_and_missing_observation_are_rejected(self):
        for field, value in [('sdk', 30), ('device', 'OldPhone'), ('installation', 'sideload'),
                             ('tested_apk_sha256', 'different'), ('evidence', '')]:
            with self.subTest(field=field):
                self.observed()
                data = json.loads(self.evidence.read_text()); data['device_checks'][0][field] = value
                self.evidence.write_text(json.dumps(data))
                with self.assertRaises(ValueError): self.authorize()

    def test_identity_metadata_config_apk_and_rollout_changes_invalidate_approval(self):
        self.observed(); self.authorize()
        for path in [self.root / 'play/metadata/title.txt', self.root / 'play/release.json', self.root / 'test.apk']:
            old = path.read_bytes(); path.write_bytes(old + b'changed')
            with self.subTest(path=path), self.assertRaises(ValueError): self.verify()
            path.write_bytes(old)
        with self.assertRaisesRegex(ValueError, 'rollout'): self.verify('1.0')
        self.config['package_name'] = 'com.example.different'
        self.audit['package_name'] = 'com.example.different'
        with self.assertRaises(ValueError): self.verify()

    def test_rebuilt_aab_and_edited_observations_invalidate_approval(self):
        self.observed(); self.authorize()
        self.evidence.write_text(self.evidence.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'observations'): self.verify()
        self.aab.write_bytes(self.aab.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'Audit'): self.verify()

    def test_review_is_idempotent_and_never_overwrites_observations(self):
        self.observed(); original = self.evidence.read_text()
        review(self.root, self.config, self.aab, self.audit, self.evidence)
        self.assertEqual(original, self.evidence.read_text())
        (self.root / 'test.apk').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Existing review'):
            review(self.root, self.config, self.aab, self.audit, self.evidence)
        self.assertEqual(original, self.evidence.read_text())

    def test_missing_approval_blocks_before_audit_or_network(self):
        with patch('sys.argv', ['release.py', '--project', str(self.root), 'production-check', '--aab', str(self.aab)]), \
             patch('release.audit', side_effect=AssertionError('audit/network must not run')):
            with self.assertRaisesRegex(ValueError, 'Production blocked'): main()

    def test_wrong_validation_apk_is_caught(self):
        self.assertEqual([], matching_apk_issues(self.aab, self.root / 'test.apk'))
        with zipfile.ZipFile(self.root / 'test.apk', 'w') as z: z.writestr('classes.dex', b'Debug/sideload code')
        self.assertTrue(matching_apk_issues(self.aab, self.root / 'test.apk'))

    def test_app_artifact_hook_failure_is_not_ignored(self):
        with patch('release.run', side_effect=RuntimeError('validator rejected APK')):
            self.config['artifact_checks'] = [['validator', '{apk}', '{package_name}', '{version_name}']]
            with self.assertRaisesRegex(RuntimeError, 'validator rejected'): artifact_checks(self.root, self.config, self.aab, self.audit)

    def test_old_prepare_or_changed_build_tasks_cannot_approve(self):
        path = preparation_proof(self.root, self.config, self.audit);path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'status': 'passed', 'aab_sha256': digest(self.aab),
            'apk_sha256': digest(self.root / 'test.apk'), 'gradle_tasks': self.config['gradle_tasks'], 'compilation_policy': 'fresh-nonincremental'}))
        validate_preparation(self.root, self.config, self.audit)
        self.config['gradle_tasks'].append(':app:extraCheck')
        with self.assertRaisesRegex(ValueError, 'prepare'): validate_preparation(self.root, self.config, self.audit)

    def test_preserved_images_do_not_require_regeneration_or_change_owner_selection(self):
        self.config['screenshot_config'] = 'play/screenshots.json'
        self.config['sync_store_images'] = False
        with patch('screenshots.check', side_effect=AssertionError('must preserve existing assets')):
            store_issues(self.root, self.config, 12)

    def test_new_app_without_config_gets_setup_report_instead_of_traceback(self):
        (self.root / 'play/release.json').unlink()
        output = io.StringIO()
        with patch('sys.argv', ['release.py', '--project', str(self.root), 'doctor']), contextlib.redirect_stdout(output):
            self.assertEqual(1, main())
        report = json.loads(output.getvalue())
        self.assertFalse(report['ready'])
        self.assertIsNone(report['package_name'])

    def test_doctor_is_read_only_and_reports_missing_setup_without_secrets(self):
        (self.root / 'gradlew').write_text('test'); (self.root / 'gradlew').chmod(0o755)
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = inspect(self.root, self.config)
        self.assertFalse(result['ready'])
        self.assertIn('bundle_path', [c['name'] for c in result['checks'] if not c['ok']])
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))


    def prior_observation(self):
        self.observed()
        data = json.loads(self.evidence.read_text())
        data['device_checks'][0].update(status='accepted_prior_validation', installation='sideload',
            tested_apk_sha256='a' * 64, prior_artifact={'package_name': 'com.example.beta',
                'version_name': '1.2.0-beta.1', 'apk_sha256': 'a' * 64, 'status': 'passed'},
            user_acceptance={'source': 'user', 'authorization': 'Use completed phone APK validation without repeating the Play-file test.',
                'reason': 'User accepts prior physical validation for this release; current-file coverage remains limited.'})
        self.evidence.write_text(json.dumps(data))

    def test_explicit_prior_acceptance_remains_an_exception_in_the_bound_record(self):
        self.prior_observation(); self.authorize(); self.verify()
        data = json.loads(self.evidence.read_text())
        self.assertEqual('accepted_prior_validation', data['device_checks'][0]['status'])
        self.assertNotEqual(data['device_checks'][0]['tested_apk_sha256'], data['artifact']['apk_sha256'])

    def test_prior_validation_cannot_be_inferred_or_use_a_failed_or_unidentified_artifact(self):
        for target, key, value in [('user_acceptance', 'source', 'code'), ('user_acceptance', 'authorization', ''),
                                  ('prior_artifact', 'status', 'failed'), ('prior_artifact', 'apk_sha256', 'b' * 64)]:
            with self.subTest(target=target, key=key):
                self.prior_observation(); data = json.loads(self.evidence.read_text())
                data['device_checks'][0][target][key] = value;self.evidence.write_text(json.dumps(data))
                with self.assertRaises(ValueError): self.authorize()

    def test_prior_acceptance_does_not_waive_device_or_os_requirements(self):
        self.prior_observation(); data = json.loads(self.evidence.read_text())
        data['device_checks'][0]['sdk'] = 30;self.evidence.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'compatibility range'): self.authorize()


if __name__ == '__main__': unittest.main()
