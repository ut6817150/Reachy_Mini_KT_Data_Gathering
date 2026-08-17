"""Load and validate Question 0 and the twelve scored study questions."""

from pathlib import Path
import re


QUESTION_HEADING = r"^##\s+Question\s+(\d+)\s*$"
FIRST_QUESTION_NUMBER = 0
LAST_QUESTION_NUMBER = 12
QUESTION_COUNT = LAST_QUESTION_NUMBER - FIRST_QUESTION_NUMBER + 1


class QuestionFormatError(ValueError):
    """Raised when the Markdown question file is incomplete or malformed."""


def parse_questions(markdown: str) -> tuple[str, ...]:
    """Return question text from sequential ``## Question N`` sections."""

    parts = re.split(QUESTION_HEADING, markdown, flags=re.IGNORECASE | re.MULTILINE)
    sections = list(zip(parts[1::2], parts[2::2]))

    if len(sections) != QUESTION_COUNT:
        raise QuestionFormatError(
            f"Expected Question 0 through Question 12 ({QUESTION_COUNT} sections), "
            f"found {len(sections)}. Use headings such as '## Question 0'."
        )

    questions: list[str] = []
    for expected_number, (number, text) in enumerate(
        sections, start=FIRST_QUESTION_NUMBER
    ):
        if int(number) != expected_number:
            raise QuestionFormatError(
                "Question headings must be sequential from 0 to 12; "
                f"expected Question {expected_number}, found Question {number}."
            )
        text = text.strip()
        if not text:
            raise QuestionFormatError(f"Question {number} has no text.")
        questions.append(text)

    return tuple(questions)


def load_questions(path: str | Path) -> tuple[str, ...]:
    question_path = Path(path).expanduser().resolve()
    try:
        return parse_questions(question_path.read_text(encoding="utf-8"))
    except OSError as error:
        raise QuestionFormatError(
            f"Could not read question file: {question_path}"
        ) from error
