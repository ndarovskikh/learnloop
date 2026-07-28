import tempfile
import unittest
from pathlib import Path

from learnloop.models import StudentProgress
from learnloop.repository import ProgressRepository


class ProgressRepositoryTests(unittest.TestCase):
    def test_progress_survives_a_new_repository_instance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = ProgressRepository(root)
            progress = StudentProgress(user_id="student-1", topic_depth=3)
            repository.save(progress)

            reloaded = ProgressRepository(root).load("student-1")

            self.assertEqual(reloaded.topic_depth, 3)

    def test_corrupted_progress_is_an_explicit_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "student-1.json").write_text("{broken", encoding="utf-8")
            repository = ProgressRepository(root)

            with self.assertRaisesRegex(ValueError, "CORRUPTED_PROGRESS"):
                repository.load("student-1")

    def test_unsafe_user_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ProgressRepository(Path(directory))
            with self.assertRaisesRegex(ValueError, "unsupported"):
                repository.load("../other-user")


if __name__ == "__main__":
    unittest.main()

