"""Tests for the participant question-loop state machine."""

import unittest

from services.experiment_controller import (
    AWAITING_CONTINUE,
    QUESTION_READY,
    ExperimentController,
)

QUESTIONS = tuple(f"Question {number}" for number in range(13))


class ExperimentControllerTests(unittest.TestCase):
    def test_runs_practice_and_twelve_questions_then_completes(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        for number in range(13):
            self.assertEqual(experiment.question_number, number)
            experiment.begin_response()
            final_question = experiment.finish_response()
            self.assertEqual(final_question, number == 12)
            self.assertEqual(experiment.stage, AWAITING_CONTINUE)
            complete = experiment.continue_after_response()
            self.assertEqual(complete, number == 12)

    def test_does_not_advance_until_participant_continues(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        experiment.begin_response()

        experiment.finish_response()

        self.assertEqual(experiment.question_number, 0)
        self.assertEqual(experiment.stage, AWAITING_CONTINUE)
        experiment.continue_after_response()
        self.assertEqual(experiment.question_number, 1)
        self.assertEqual(experiment.stage, QUESTION_READY)

    def test_rejects_stop_before_begin(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        with self.assertRaises(RuntimeError):
            experiment.finish_response()

    def test_rejects_continue_before_response_is_complete(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        with self.assertRaises(RuntimeError):
            experiment.continue_after_response()

    def test_failed_recording_can_be_retried(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        experiment.begin_response()
        experiment.abort_response()
        self.assertEqual(experiment.stage, QUESTION_READY)
        self.assertEqual(experiment.question_number, 0)


if __name__ == "__main__":
    unittest.main()
