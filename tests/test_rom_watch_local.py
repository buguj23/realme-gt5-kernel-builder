import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("watch", Path(__file__).resolve().parents[1] / "scripts/rom-watch-local.py")
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


class LocalWatchTests(unittest.TestCase):
    def test_only_verified_delivery_reports_success(self):
        svc = {"InvocationID": "a" * 32, "ActiveState": "inactive", "Result": "success", "ExecMainStatus": "0"}
        self.assertEqual(watch.outcome(svc, {"state": "completed", "phase": "official_source_sync"}, "a" * 32, True), "failure")
        self.assertEqual(watch.outcome(svc, {"state": "completed", "phase": "delivery_verified"}, "a" * 32, True), "success")
        svc["ExecMainStatus"] = "1"
        self.assertEqual(watch.outcome(svc, {"state": "completed", "phase": "delivery_verified"}, "a" * 32, True), "failure")

    def test_replaced_build_is_not_misreported(self):
        self.assertEqual(watch.outcome({"InvocationID": "b" * 32, "ActiveState": "active"}, {}, "a" * 32, True), "replaced")
        self.assertEqual(watch.outcome({}, {"state": "completed", "phase": "delivery_verified"}, "a" * 32, False), "missing")

    def test_collected_success_after_observed_build(self):
        state = {"state": "completed", "phase": "delivery_verified"}
        self.assertEqual(watch.outcome({"ActiveState": "inactive"}, state, "a" * 32, True), "success")

    def test_redacts_credential_forms_and_local_path(self):
        text = "/local/build/log https://user:secret@example.org/path?token=example ghp_EXAMPLE auth Authorization: Bearer abc"
        value = watch.sanitize(text, Path("/local/build"))
        self.assertNotIn("user:secret", value)
        self.assertNotIn("token=example", value)
        self.assertNotIn("ghp_EXAMPLE", value)
        self.assertNotIn("Bearer abc", value)
        self.assertIn("$BIANYI/log", value)


if __name__ == "__main__":
    unittest.main()
