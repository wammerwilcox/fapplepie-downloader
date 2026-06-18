import json
from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/bump-version.yml")
RENOVATE_CONFIG = Path("renovate.json")


class RenovateVersionBumpTests(unittest.TestCase):
    def test_renovate_bumps_version_inside_dependency_prs(self) -> None:
        renovate = json.loads(RENOVATE_CONFIG.read_text())

        self.assertEqual(
            renovate["bumpVersions"],
            [
                {
                    "filePatterns": ["VERSION"],
                    "bumpType": "patch",
                }
            ],
        )

    def test_post_merge_bump_workflow_is_removed(self) -> None:
        self.assertFalse(
            WORKFLOW.exists(),
            "Renovate should bump VERSION before merge; a post-merge main push workflow conflicts with repository rules.",
        )
