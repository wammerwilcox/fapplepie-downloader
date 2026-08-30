import json
from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/bump-version.yml")
RENOVATE_CONFIG = Path("renovate.json")
REQUIREMENTS_LOCK = Path("app/requirements.txt")


class RenovateVersionBumpTests(unittest.TestCase):
    def test_renovate_bumps_version_inside_dependency_prs(self) -> None:
        renovate = json.loads(RENOVATE_CONFIG.read_text())

        self.assertEqual(
            renovate["bumpVersions"],
            [
                {
                    "filePatterns": ["VERSION"],
                    "matchStrings": ["^(?<version>\\d+\\.\\d+\\.\\d+)$"],
                    "bumpType": "patch",
                }
            ],
        )

    def test_post_merge_bump_workflow_is_removed(self) -> None:
        self.assertFalse(
            WORKFLOW.exists(),
            "Renovate should bump VERSION before merge; a post-merge main push workflow conflicts with repository rules.",
        )

    def test_requirements_lock_has_renovate_supported_header(self) -> None:
        lockfile = REQUIREMENTS_LOCK.read_text()

        self.assertIn("pip-compile", lockfile)
        self.assertNotIn("--no-index", lockfile)
