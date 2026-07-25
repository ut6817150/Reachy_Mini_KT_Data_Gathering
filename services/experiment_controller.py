"""State machine for one participant's ten-question interaction."""

QUESTION_READY = "question_ready"
RECORDING = "recording"
AWAITING_CONTINUE = "awaiting_continue"


class ExperimentController:
    def __init__(self, questions: tuple[str, ...]) -> None:
        if not questions:
            raise ValueError("At least one question is required")
        self.questions = questions
        self.question_index = 0
        self.stage = QUESTION_READY

    @property
    def current_question(self) -> str:
        return self.questions[self.question_index]

    @property
    def question_number(self) -> int:
        return self.question_index + 1

    def begin_response(self) -> None:
        if self.stage != QUESTION_READY:
            raise RuntimeError("A response can only begin when a question is ready")
        self.stage = RECORDING

    def finish_response(self) -> bool:
        if self.stage != RECORDING:
            raise RuntimeError("No response is currently being recorded")
        self.stage = AWAITING_CONTINUE
        return self.question_index == len(self.questions) - 1

    def continue_after_response(self) -> bool:
        if self.stage != AWAITING_CONTINUE:
            raise RuntimeError(
                "The experiment can only continue after a completed response"
            )
        if self.question_index == len(self.questions) - 1:
            return True
        self.question_index += 1
        self.stage = QUESTION_READY
        return False

    def abort_response(self) -> None:
        if self.stage != RECORDING:
            raise RuntimeError("No response is currently being recorded")
        self.stage = QUESTION_READY
