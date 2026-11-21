import ast
from pathlib import Path
import runpy
import tempfile
from types import SimpleNamespace
import unittest

FIX = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/rom-fix-repo-depth.py"))
FIXTURE = """class Project:
    def depth(self, depth, is_new):
        if depth and not is_new and not self._HasShallow():
            depth = None
        return depth
"""


class RepoRetryDepthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "project.py"
        self.path.write_text(FIXTURE)

    def effective(self, depth, is_new, shallow, refs):
        FIX["patch"](self.path)
        namespace = {}
        exec(compile(self.path.read_text(), str(self.path), "exec"), namespace)
        project = namespace["Project"]()
        project._HasShallow = lambda: shallow
        project.bare_ref = SimpleNamespace(all=refs)
        return project.depth(depth, is_new)

    def test_failed_initial_fetch_keeps_depth_on_retry(self):
        self.assertEqual(1, self.effective(1, False, False, {}))

    def test_manually_unshallowed_project_stays_full(self):
        self.assertIsNone(self.effective(1, False, False, {"refs/heads/main": "abc"}))

    def test_completed_shallow_project_keeps_depth(self):
        self.assertEqual(1, self.effective(1, False, True, {"refs/tags/v1": "abc"}))

    def test_new_project_and_unlimited_fetch(self):
        self.assertEqual(1, self.effective(1, True, False, {}))
        self.assertIsNone(self.effective(None, False, False, {}))

    def test_idempotent_and_unknown_version_preserved(self):
        FIX["patch"](self.path)
        patched = self.path.read_bytes()
        self.assertEqual("already applied", FIX["patch"](self.path))
        self.assertEqual(patched, self.path.read_bytes())
        self.path.write_text("# different version\n")
        self.assertIn("unchanged", FIX["patch"](self.path))
        self.assertEqual("# different version\n", self.path.read_text())
