import threading
import unittest

from learnloop.answer_queue import AnswerDraftQueue


class AnswerDraftQueueTests(unittest.TestCase):
    def test_chunks_combine_in_seq_order_even_if_appended_out_of_order(self):
        queue = AnswerDraftQueue()

        queue.append("student-1", "q-1", chunk_id="b", seq=1, text="second half")
        combined = queue.append("student-1", "q-1", chunk_id="a", seq=0, text="first half")

        self.assertEqual(combined, "first half\nsecond half")

    def test_duplicate_chunk_id_is_a_no_op(self):
        queue = AnswerDraftQueue()

        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="hello")
        combined = queue.append("student-1", "q-1", chunk_id="a", seq=0, text="hello")

        self.assertEqual(combined, "hello")

    def test_blank_chunk_is_ignored(self):
        queue = AnswerDraftQueue()

        combined = queue.append("student-1", "q-1", chunk_id="a", seq=0, text="   ")

        self.assertEqual(combined, "")

    def test_switching_question_starts_a_fresh_draft(self):
        queue = AnswerDraftQueue()
        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="about q1")

        combined = queue.append("student-1", "q-2", chunk_id="b", seq=0, text="about q2")

        self.assertEqual(combined, "about q2")

    def test_begin_finalize_returns_combined_text_once(self):
        queue = AnswerDraftQueue()
        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="part one")
        queue.append("student-1", "q-1", chunk_id="b", seq=1, text="part two")

        combined = queue.begin_finalize("student-1", "q-1")

        self.assertEqual(combined, "part one\npart two")

    def test_begin_finalize_is_none_with_nothing_drafted(self):
        queue = AnswerDraftQueue()

        self.assertIsNone(queue.begin_finalize("student-1", "q-1"))

    def test_concurrent_finalize_only_one_caller_wins(self):
        queue = AnswerDraftQueue()
        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="my answer")

        results = []
        barrier = threading.Barrier(2)

        def race():
            barrier.wait()
            results.append(queue.begin_finalize("student-1", "q-1"))

        threads = [threading.Thread(target=race) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        winners = [item for item in results if item is not None]
        losers = [item for item in results if item is None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(len(losers), 1)
        self.assertEqual(winners[0], "my answer")

    def test_cancel_finalize_allows_a_retry_after_a_failed_grading_attempt(self):
        queue = AnswerDraftQueue()
        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="my answer")
        self.assertIsNotNone(queue.begin_finalize("student-1", "q-1"))
        self.assertIsNone(queue.begin_finalize("student-1", "q-1"))

        queue.cancel_finalize("student-1", "q-1")

        self.assertEqual(queue.begin_finalize("student-1", "q-1"), "my answer")

    def test_clear_drops_the_draft_after_successful_grading(self):
        queue = AnswerDraftQueue()
        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="my answer")
        queue.begin_finalize("student-1", "q-1")

        queue.clear("student-1", "q-1")

        self.assertEqual(queue.peek("student-1", "q-1"), "")
        # A fresh chunk after clearing starts a new draft, not appended to
        # the graded one.
        combined = queue.append("student-1", "q-1", chunk_id="c", seq=0, text="next answer")
        self.assertEqual(combined, "next answer")

    def test_two_students_do_not_interfere(self):
        queue = AnswerDraftQueue()

        queue.append("student-1", "q-1", chunk_id="a", seq=0, text="alice's answer")
        queue.append("student-2", "q-1", chunk_id="a", seq=0, text="bob's answer")

        self.assertEqual(queue.peek("student-1", "q-1"), "alice's answer")
        self.assertEqual(queue.peek("student-2", "q-1"), "bob's answer")


if __name__ == "__main__":
    unittest.main()
