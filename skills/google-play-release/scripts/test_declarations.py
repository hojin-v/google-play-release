import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from declarations import apply_answers, interview, load_state, main, pending, report, save_state


class DeclarationInterview(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "play").mkdir()
        (self.root / "play/release.json").write_text(json.dumps({"package_name": "com.example.app"}))
        self.state = load_state(self.root)

    def keys(self):
        return {q["id"] for q in pending(self.state)}

    def test_new_app_has_no_assumed_answers_and_does_not_copy_preferences(self):
        (self.root / "play/release.json").write_text(json.dumps({
            "package_name": "com.example.app", "distribution_preferences": {"pricing": "free"}}))
        self.assertEqual({}, load_state(self.root)["answers"])
        self.assertIn("pricing", self.keys())
        self.assertFalse(report(self.state)["facts_complete"])
        self.assertFalse((self.root / "play/declarations.json").exists())

    def test_conditional_questions_follow_facts_in_both_directions(self):
        self.assertNotIn("fgs_video_url", self.keys())
        apply_answers(self.state, {"foreground_service": "yes", "health": "yes", "accounts": "yes"}, "code")
        self.assertTrue({"fgs_video_url", "fgs_details", "health_details", "account_deletion_url"} <= self.keys())
        apply_answers(self.state, {"foreground_service": "no", "health": "no", "accounts": "no"}, "console")
        self.assertNotIn("fgs_video_url", self.keys())
        self.assertNotIn("health_details", self.keys())

    def test_invalid_batch_does_not_partially_mutate_or_save(self):
        with self.assertRaises(ValueError):
            apply_answers(self.state, {"ads": "no", "health": "maybe"}, "operator")
        self.assertEqual({}, self.state["answers"])
        with self.assertRaises(ValueError):
            apply_answers(self.state, {"ads": "no", "pricing": "free"}, "code")
        self.assertEqual({}, self.state["answers"])

    def test_resume_and_cross_package_protection(self):
        apply_answers(self.state, {"countries": "kr,US,KR", "pricing": "paid"}, "user")
        save_state(self.root, self.state)
        state = load_state(self.root)
        self.assertEqual(["KR", "US"], state["answers"]["countries"]["value"])
        self.assertNotIn("pricing", {q["id"] for q in pending(state)})
        (self.root / "play/release.json").write_text(json.dumps({"package_name": "com.other.app"}))
        with self.assertRaises(ValueError):
            load_state(self.root)

    def test_urls_ages_and_required_answers_are_validated(self):
        for key, value in [("privacy_policy_url", "http://example.com"),
                           ("privacy_policy_url", "https://user:password@example.com"),
                           ("target_audience", "adult"), ("countries", ""), ("ads", "")]:
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                apply_answers(self.state, {key: value}, "operator")
        self.assertEqual({}, self.state["answers"])

    def test_interview_reprompts_empty_input_and_retains_skipped_questions(self):
        responses = iter(["", "KR", "s", "q"])
        output = []
        result = interview(self.root, self.state, input_fn=lambda _: next(responses), output_fn=output.append)
        self.assertEqual(["KR"], self.state["answers"]["countries"]["value"])
        self.assertIn("pricing", {q["id"] for q in result["pending_questions"]})
        self.assertEqual("operator", load_state(self.root)["answers"]["countries"]["source"])
        self.assertTrue(any("비어" in line for line in output))

    def test_detailed_data_and_accounts_are_not_treated_as_no_data(self):
        apply_answers(self.state, {"data": "both", "access": "restricted", "finance": "yes"}, "user")
        self.assertTrue({"data_details", "access_instructions", "finance_details"} <= self.keys())

    def test_production_fact_gate_fails_without_answers_and_passes_only_when_complete(self):
        def status():
            with contextlib.redirect_stdout(io.StringIO()):
                return main(["--project", str(self.root), "status", "--json", "--require-complete"])
        self.assertEqual(2, status())
        self.assertFalse((self.root / "play/declarations.json").exists())
        apply_answers(self.state, {
            "countries": ["US"], "pricing": "paid", "target_audience": ["18+"],
            "app_type": "utility", "ads": "no", "ad_id": "no", "purchases": "no",
            "accounts": "no", "access": "open", "data": "none", "sensitive_content": "no",
            "health": "no", "finance": "no", "government": "no", "foreground_service": "no",
            "privacy_policy_url": "https://example.com/privacy"}, "operator")
        save_state(self.root, self.state)
        self.assertEqual(0, status())
        apply_answers(self.state, {"health": "yes"}, "operator")
        save_state(self.root, self.state)
        self.assertEqual(2, status())


if __name__ == "__main__":
    unittest.main()
