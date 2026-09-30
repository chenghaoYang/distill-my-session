"""Synthetic-only privacy regressions; never discover or read real sessions/config."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(os.environ.get("DISTILL_TEST_SCRIPTS", Path(__file__).resolve().parents[1] / "scripts"))
spec = importlib.util.spec_from_file_location("redact_under_test", SCRIPTS / "redact.py")
redact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(redact)
TOKEN = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2"  # fabricated, never a real credential


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.public = self.root / "public"
        self.public.mkdir()
        self.deny = self.root / "deny.txt"
        self.allow = self.root / "allow.txt"
        self.deny.write_text("")
        self.allow.write_text("")
        self.identities = patch.object(redact, "identity_variants", return_value=[])
        self.identities.start()

    def tearDown(self):
        self.identities.stop()
        self.temp.cleanup()

    def find(self, text):
        (self.public / "example.md").write_text(text)
        return redact.leakcheck(self.public, self.deny, None, self.allow)

    def redactor(self):
        return redact.Redactor(denylist=self.deny, allowlist=self.allow)

    def cli(self, path):
        config = self.root / "config"
        config.mkdir(exist_ok=True)
        gitconfig = self.root / "gitconfig"
        gitconfig.write_text("")
        env = dict(os.environ, HOME=str(self.root), USER="fixture", DISTILL_CONFIG_DIR=str(config),
                   XDG_CONFIG_HOME=str(config), GIT_CONFIG_GLOBAL=str(gitconfig), GIT_CONFIG_NOSYSTEM="1")
        return subprocess.run([sys.executable, str(SCRIPTS / "distill.py"), "leakcheck", str(path),
                               "--denylist", str(self.deny)], capture_output=True, text=True, env=env)

    def test_password_assignment_is_found_without_revealing_value(self):
        findings = self.find("password=synthetic-demo-pass\n")
        self.assertTrue(any(x[2] == "assignment" for x in findings))
        self.assertNotIn("synthetic-demo-pass", repr(findings))

    def test_json_key_assignment_is_masked_and_found(self):
        text = '{"password": "synthetic-demo-pass"}'
        self.assertNotIn("synthetic-demo-pass", self.redactor()(text))
        self.assertTrue(any(x[2] == "assignment" for x in self.find(text)))

    def test_allowlist_cannot_restore_detected_token(self):
        self.allow.write_text(TOKEN + "\n")
        self.assertEqual(self.redactor()(TOKEN), "[SECRET]")

    def test_allowlist_cannot_hide_detected_token_from_scan(self):
        self.allow.write_text(TOKEN + "\n")
        self.assertTrue(any(x[2] == "token" for x in self.find(TOKEN)))

    def test_allowlist_still_preserves_ordinary_project_name(self):
        self.deny.write_text("PublicWidget => [PROJECT]\n")
        self.allow.write_text("PublicWidget\n")
        self.assertEqual(self.redactor()("PublicWidget"), "PublicWidget")
        self.assertEqual(self.find("PublicWidget"), [])

    def test_known_redaction_placeholders_do_not_fail_assignment_check(self):
        self.assertEqual(self.find('password=[SECRET]\ntoken="[REDACTED]"\n'), [])

    def test_missing_target_is_not_clean(self):
        with self.assertRaises(FileNotFoundError):
            redact.leakcheck(self.root / "missing", self.deny, None, self.allow)

    def test_undecodable_text_is_not_silently_skipped(self):
        (self.public / "broken.md").write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            redact.leakcheck(self.public, self.deny, None, self.allow)

    def test_markdown_escaped_token_is_detected(self):
        self.assertTrue(any(x[2] == "token" for x in self.find(TOKEN.replace("-", "\\-"))))

    def test_cli_missing_target_exits_incomplete(self):
        result = self.cli(self.root / "missing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("incomplete", result.stderr)
        self.assertNotIn("0 blocking", result.stdout)

    def test_cli_assignment_exits_blocking(self):
        (self.public / "example.md").write_text("password=synthetic-demo-pass\n")
        result = self.cli(self.public)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("synthetic-demo-pass", result.stdout + result.stderr)

    def test_cli_clean_text_exits_zero(self):
        (self.public / "example.md").write_text("A generic workflow description.\n")
        result = self.cli(self.public)
        self.assertEqual(result.returncode, 0)
        self.assertIn("0 blocking", result.stdout)


if __name__ == "__main__":
    unittest.main()
