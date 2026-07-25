"""Load and validate the ten study questions from Markdown."""

from pathlib import Path
import re


QUESTION_HEADING = r"^##\s+Question\s+(\d+)\s*$"


class QuestionFormatError(ValueError):
    """Raised when the Markdown question file is incomplete or malformed."""


def parse_questions(markdown: str) -> tuple[str, ...]:
    """Return question text from sequential ``## Question N`` sections."""

    parts = re.split(QUESTION_HEADING, markdown, flags=re.IGNORECASE | re.MULTILINE)
    sections = list(zip(parts[1::2], parts[2::2]))

    if len(sections) != 10:
        raise QuestionFormatError(
            f"Expected 10 questions, found {len(sections)}. "
            "Use headings such as '## Question 1'."
        )

    questions: list[str] = []
    for expected_number, (number, text) in enumerate(sections, start=1):
        if int(number) != expected_number:
            raise QuestionFormatError(
                "Question headings must be sequential from 1 to 10; "
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
