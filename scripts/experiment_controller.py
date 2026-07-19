"""State machine for one participant's ten-question interaction."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from scripts.question_loader import Question


class ExperimentStage(str, Enum):
    QUESTION_READY = "question_ready"
    RECORDING = "recording"
    AWAITING_CONTINUE = "awaiting_continue"
    COMPLETE = "complete"


class InvalidExperimentTransition(RuntimeError):
    """Raised when UI actions arrive in an invalid order."""


@dataclass(slots=True)
class ExperimentController:
    questions: tuple[Question, ...]
    question_index: int = 0
    stage: ExperimentStage = ExperimentStage.QUESTION_READY
    completed_recordings: list[Path] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.questions:
            raise ValueError("At least one question is required")
        if not 0 <= self.question_index < len(self.questions):
            raise ValueError("question_index is out of range")

    @property
    def current_question(self) -> Question:
        return self.questions[self.question_index]

    @property
    def progress_label(self) -> str:
        return f"Question {self.question_index + 1} of {len(self.questions)}"

    def begin_response(self) -> None:
        if self.stage is not ExperimentStage.QUESTION_READY:
            raise InvalidExperimentTransition("A response can only begin when a question is ready")
        self.stage = ExperimentStage.RECORDING

    def finish_response(self, recording_path: str | Path) -> bool:
        """Save the response and return whether it belongs to the final question."""

        if self.stage is not ExperimentStage.RECORDING:
            raise InvalidExperimentTransition("No response is currently being recorded")
        self.completed_recordings.append(Path(recording_path))
        self.stage = ExperimentStage.AWAITING_CONTINUE
        return self.question_index == len(self.questions) - 1

    def continue_after_response(self) -> bool:
        """Advance after acknowledgement and return whether the study is complete."""

        if self.stage is not ExperimentStage.AWAITING_CONTINUE:
            raise InvalidExperimentTransition(
                "The experiment can only continue after a completed response"
            )
        if self.question_index == len(self.questions) - 1:
            self.stage = ExperimentStage.COMPLETE
            return True
        self.question_index += 1
        self.stage = ExperimentStage.QUESTION_READY
        return False

    def abort_response(self) -> None:
        """Return to the current question after a failed/cancelled recording."""

        if self.stage is not ExperimentStage.RECORDING:
            raise InvalidExperimentTransition("No response is currently being recorded")
        self.stage = ExperimentStage.QUESTION_READY
