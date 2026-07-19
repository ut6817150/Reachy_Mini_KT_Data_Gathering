"""Load and validate the ten study questions from Markdown."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


QUESTION_HEADING = re.compile(r"^##\s+Question\s+(\d+)\s*$", re.IGNORECASE)
EXPECTED_QUESTION_COUNT = 10


class QuestionFormatError(ValueError):
    """Raised when the Markdown question file is incomplete or malformed."""


@dataclass(frozen=True, slots=True)
class Question:
    number: int
    text: str


def parse_questions(markdown: str, expected_count: int = EXPECTED_QUESTION_COUNT) -> tuple[Question, ...]:
    """Parse ``## Question N`` sections and enforce sequential numbering."""

    if expected_count <= 0:
        raise ValueError("expected_count must be greater than zero")

    sections: list[tuple[int, list[str]]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    def finish_section() -> None:
        if current_number is not None:
            sections.append((current_number, list(current_lines)))

    for line in markdown.splitlines():
        match = QUESTION_HEADING.match(line.strip())
        if match:
            finish_section()
            current_number = int(match.group(1))
            current_lines = []
        elif current_number is not None:
            current_lines.append(line)
    finish_section()

    if len(sections) != expected_count:
        raise QuestionFormatError(
            f"Expected {expected_count} questions, found {len(sections)}. "
            "Use headings such as '## Question 1'."
        )

    questions: list[Question] = []
    for expected_number, (number, lines) in enumerate(sections, start=1):
        if number != expected_number:
            raise QuestionFormatError(
                f"Question headings must be sequential from 1 to {expected_count}; "
                f"expected Question {expected_number}, found Question {number}."
            )
        text = "\n".join(lines).strip()
        if not text:
            raise QuestionFormatError(f"Question {number} has no text.")
        questions.append(Question(number=number, text=text))

    return tuple(questions)


def load_questions(path: str | Path) -> tuple[Question, ...]:
    """Read and parse a UTF-8 Markdown question file."""

    question_path = Path(path).expanduser().resolve()
    try:
        markdown = question_path.read_text(encoding="utf-8")
    except OSError as error:
        raise QuestionFormatError(f"Could not read question file: {question_path}") from error
    return parse_questions(markdown)
