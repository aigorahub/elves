"""Parity tests for the secret-redaction corpora.

Two boundaries redact secrets: the Python corpus in ``cobbler_runtime.context``
(run artifacts, release scanning) and the sed pipeline shared by ``notify.sh``
and ``preflight.sh`` (operator-facing output). These tests pin every named
Python pattern to a synthetic sample and assert the two boundaries cover the
same shape families, so a pattern added on one side without the other fails
here instead of drifting silently. All sample values are synthetic.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from cobbler_runtime.context import (  # noqa: E402
    SECRET_VALUE_PATTERNS,
    is_secret_env_name,
    redact_text,
)

# One synthetic sample per named pattern. The equality assertion below forces
# every future pattern addition to register a sample here.
PATTERN_SAMPLES: dict[str, tuple[str, str]] = {
    # name: (sample text, secret substring that must not survive)
    "uri_userinfo": (
        "clone https://user:hunter2secret@example.com/repo.git",
        "hunter2secret",
    ),
    "uri_userinfo_bare": (
        "clone https://faketoken12345@example.com/repo.git",
        "faketoken12345",
    ),
    "slack_webhook": (
        "post https://hooks.slack.example/services/T0000000/B0000000/fakefakefakefake0000",
        "fakefakefakefake0000",
    ),
    "secret_assignment": (
        'api_key = "fakeassignedvalue123"',
        "fakeassignedvalue123",
    ),
    "bearer_token": (
        "header Bearer fakebearer12345",
        "fakebearer12345",
    ),
    "sk_token": ("key sk-fakefakefake123456", "sk-fakefakefake123456"),
    "xai_token": ("key xai-fakefakefake123", "xai-fakefakefake123"),
    "github_pat": ("token ghp_" + "a" * 20, "ghp_" + "a" * 20),
    "github_oauth": ("token gho_" + "b" * 20, "gho_" + "b" * 20),
    "github_token": ("token ghu_" + "c" * 20, "ghu_" + "c" * 20),
    "github_fine_grained_pat": (
        "token github_pat_" + "d" * 20,
        "github_pat_" + "d" * 20,
    ),
    "aws_access_key": ("key AKIA" + "A" * 16, "AKIA" + "A" * 16),
    "pem_block": (
        "-----BEGIN PRIVATE KEY-----\nfakepembody\n-----END PRIVATE KEY-----",
        "fakepembody",
    ),
}

# Shape families that must exist on BOTH boundaries. The shell needle is a
# stable fragment of the sed rule in notify.sh/preflight.sh; the Python name
# must be a key of SECRET_VALUE_PATTERNS.
SHARED_SHAPES: dict[str, str] = {
    # python pattern name: shell rule fragment
    "uri_userinfo_bare": "[^/@[:space:]]+@",
    "slack_webhook": "hooks\\.slack",
    "secret_assignment": "(api[_-]?key",
    "bearer_token": "Bearer[[:space:]]",
    "sk_token": "sk-(proj-|svcacct-)?",
}


class PythonCorpusTests(unittest.TestCase):
    def test_every_named_pattern_has_a_sample_and_redacts_it(self) -> None:
        names = {name for name, _pattern in SECRET_VALUE_PATTERNS}
        self.assertEqual(
            names,
            set(PATTERN_SAMPLES),
            "every SECRET_VALUE_PATTERNS entry needs a sample here (and vice versa)",
        )
        for name, (sample, secret) in PATTERN_SAMPLES.items():
            with self.subTest(pattern=name):
                result = redact_text(sample)
                self.assertIn(name, result.redacted_patterns)
                self.assertNotIn(secret, result.text)
                self.assertIn("[REDACTED:", result.text)

    def test_slack_webhook_and_bare_userinfo_regression(self) -> None:
        # The two shapes that historically passed the Python boundary while the
        # shell boundary caught them.
        webhook = "https://hooks.slack.example/services/T111/B222/fakefakefakefake1111"
        bare = "https://gltoken9876543@gitlab.example/group/project.git"
        for sample in (webhook, bare):
            with self.subTest(sample=sample):
                result = redact_text(sample)
                self.assertNotEqual(result.text, sample)
                self.assertTrue(result.redacted_patterns)

    def test_ordinary_urls_are_untouched(self) -> None:
        for text in (
            "see https://example.com/path and http://docs.example.org/a/b",
            "short userinfo https://user@example.com stays (below token floor)",
            "plain prose with no secrets at all",
        ):
            with self.subTest(text=text):
                result = redact_text(text)
                self.assertEqual(result.text, text)
                self.assertEqual(result.redacted_patterns, ())

    def test_webhook_env_names_are_classified_secret(self) -> None:
        self.assertTrue(is_secret_env_name("ELVES_SLACK_WEBHOOK"))
        self.assertTrue(is_secret_env_name("MY_SERVICE_WEBHOOK"))


class ShellParityTests(unittest.TestCase):
    def _script_text(self, name: str) -> str:
        return (SCRIPTS_DIR / name).read_text(encoding="utf-8")

    def test_shared_shapes_exist_on_both_boundaries(self) -> None:
        notify = self._script_text("notify.sh")
        preflight = self._script_text("preflight.sh")
        python_names = {name for name, _pattern in SECRET_VALUE_PATTERNS}
        for python_name, shell_needle in SHARED_SHAPES.items():
            with self.subTest(shape=python_name):
                self.assertIn(python_name, python_names)
                self.assertIn(shell_needle, notify)
                self.assertIn(shell_needle, preflight)

    def test_shell_redaction_blocks_stay_identical(self) -> None:
        # The two scripts deliberately share one redaction block; a divergence
        # means a rule landed in one and not the other.
        notify = self._script_text("notify.sh")
        preflight = self._script_text("preflight.sh")
        for fragment in SHARED_SHAPES.values():
            self.assertEqual(
                notify.count(fragment),
                preflight.count(fragment),
                f"rule fragment {fragment!r} count differs between notify.sh and preflight.sh",
            )


if __name__ == "__main__":
    unittest.main()
