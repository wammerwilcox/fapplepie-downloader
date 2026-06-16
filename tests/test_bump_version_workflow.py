from pathlib import Path
import unittest


WORKFLOW = Path(".github/workflows/bump-version.yml")


class BumpVersionWorkflowTests(unittest.TestCase):
    def test_pushes_directly_to_main_without_pr_cli(self) -> None:
        workflow = WORKFLOW.read_text()

        self.assertNotIn("gh pr ", workflow)
        self.assertNotIn("chore/bump-version-after-deps", workflow)
        self.assertIn(
            'git push "https://x-access-token:${GH_TOKEN}@github.com/${GITHUB_REPOSITORY}.git" HEAD:main',
            workflow,
        )
        self.assertNotIn("--force", workflow)
