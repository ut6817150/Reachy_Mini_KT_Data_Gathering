"""Tests for the participant question-loop state machine."""

import unittest

from scripts.experiment_controller import (
    ExperimentController,
    ExperimentStage,
    InvalidExperimentTransition,
)
from scripts.question_loader import Question


QUESTIONS = tuple(Question(number, f"Question {number}") for number in range(1, 11))


class ExperimentControllerTests(unittest.TestCase):
    def test_runs_all_ten_questions_then_completes(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        for number in range(1, 11):
            self.assertEqual(experiment.current_question.number, number)
            experiment.begin_response()
            final_question = experiment.finish_response(f"question_{number:02d}.mp4")
            self.assertEqual(final_question, number == 10)
            self.assertIs(experiment.stage, ExperimentStage.AWAITING_CONTINUE)
            complete = experiment.continue_after_response()
            self.assertEqual(complete, number == 10)

        self.assertIs(experiment.stage, ExperimentStage.COMPLETE)
        self.assertEqual(len(experiment.completed_recordings), 10)

    def test_does_not_advance_until_participant_continues(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        experiment.begin_response()

        experiment.finish_response("question_01.mp4")

        self.assertEqual(experiment.current_question.number, 1)
        self.assertIs(experiment.stage, ExperimentStage.AWAITING_CONTINUE)
        experiment.continue_after_response()
        self.assertEqual(experiment.current_question.number, 2)
        self.assertIs(experiment.stage, ExperimentStage.QUESTION_READY)

    def test_rejects_stop_before_begin(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        with self.assertRaises(InvalidExperimentTransition):
            experiment.finish_response("question_01.mp4")

    def test_rejects_continue_before_response_is_complete(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        with self.assertRaises(InvalidExperimentTransition):
            experiment.continue_after_response()

    def test_failed_recording_can_be_retried(self) -> None:
        experiment = ExperimentController(QUESTIONS)
        experiment.begin_response()
        experiment.abort_response()
        self.assertIs(experiment.stage, ExperimentStage.QUESTION_READY)
        self.assertEqual(experiment.current_question.number, 1)


if __name__ == "__main__":
    unittest.main()
