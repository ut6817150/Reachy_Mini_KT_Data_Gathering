"""Tests for strict Markdown question parsing."""

from pathlib import Path
import tempfile
import unittest

from services.question_loader import (
    QuestionFormatError,
    load_questions,
    parse_questions,
)


def markdown_questions(first: int = 0, last: int = 12) -> str:
    return "# Questions\n\n" + "\n\n".join(
        f"## Question {number}\n\nQuestion text {number}."
        for number in range(first, last + 1)
    )


class QuestionParserTests(unittest.TestCase):
    def test_parses_practice_and_twelve_scored_questions(self) -> None:
        questions = parse_questions(markdown_questions())
        self.assertEqual(len(questions), 13)
        self.assertEqual(questions[0], "Question text 0.")
        self.assertEqual(questions[-1], "Question text 12.")

    def test_rejects_wrong_count(self) -> None:
        with self.assertRaisesRegex(QuestionFormatError, "Expected Question 0"):
            parse_questions(markdown_questions(last=11))

    def test_rejects_out_of_order_headings(self) -> None:
        content = markdown_questions().replace("## Question 5", "## Question 6", 1)
        with self.assertRaisesRegex(QuestionFormatError, "sequential"):
            parse_questions(content)

    def test_loads_utf8_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "questions.md"
            path.write_text(
                markdown_questions().replace("text 0", "text café 0"), encoding="utf-8"
            )
            self.assertIn("café", load_questions(path)[0])


if __name__ == "__main__":
    unittest.main()
