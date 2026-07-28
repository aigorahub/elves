"""Tests for the shell-heredoc Python compile gate in verify_repo.

``bash -n`` treats a quoted heredoc as an opaque string and ``compileall``
never visits ``.sh`` files, so embedded provider-runner Python previously
shipped with no syntax gate at all. These tests pin the gate that closes that
hole: valid heredocs pass, invalid ones fail with a line number mapped to the
real file, and an unterminated heredoc is reported rather than ignored.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from verify_repo import _compile_shell_heredocs  # noqa: E402


class ShellHeredocCompileTests(unittest.TestCase):
    def _write(self, body: str) -> Path:
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".sh", delete=False, encoding="utf-8"
        )
        self.addCleanup(Path(handle.name).unlink)
        handle.write(body)
        handle.close()
        return Path(handle.name)

    def test_valid_heredoc_passes(self) -> None:
        path = self._write(
            "#!/bin/bash\n"
            "exec python3 - \"$@\" <<'PY'\n"
            "import sys\n"
            "print(sys.argv)\n"
            "PY\n"
        )
        self.assertIsNone(_compile_shell_heredocs(path, "fixture.sh"))

    def test_invalid_python_fails_with_mapped_line(self) -> None:
        path = self._write(
            "#!/bin/bash\n"
            "echo preamble\n"
            "exec python3 - <<'PY'\n"
            "def broken(:\n"
            "PY\n"
        )
        error = _compile_shell_heredocs(path, "fixture.sh")
        self.assertIsNotNone(error)
        self.assertIn("embedded Python syntax failed for fixture.sh", error)
        # The bad def sits on file line 4; the padding must report it there,
        # not as heredoc-relative line 1.
        self.assertIn("line 4", error)

    def test_unterminated_heredoc_is_reported(self) -> None:
        path = self._write(
            "#!/bin/bash\n"
            "exec python3 - <<'PY'\n"
            "print('never closed')\n"
        )
        error = _compile_shell_heredocs(path, "fixture.sh")
        self.assertIsNotNone(error)
        self.assertIn("unterminated <<'PY' heredoc", error)

    def test_script_without_heredoc_passes(self) -> None:
        path = self._write("#!/bin/bash\necho no python here\n")
        self.assertIsNone(_compile_shell_heredocs(path, "fixture.sh"))

    def test_live_runner_heredocs_compile(self) -> None:
        for rel in ("scripts/run_fugu.sh", "scripts/run_grok.sh", "scripts/run_devin.sh"):
            with self.subTest(script=rel):
                self.assertIsNone(
                    _compile_shell_heredocs(REPO_ROOT / rel, rel)
                )


if __name__ == "__main__":
    unittest.main()
