"""Shared paths, page names, and study messages."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUESTIONS_PATH = ROOT / "questions" / "questions.md"
RECORDINGS_ROOT = ROOT / "recordings"

PAGE_RESEARCHER = "researcher_setup"
PAGE_PARTICIPANT = "participant_start"
PAGE_WELCOME = "participant_welcome"
PAGE_EXPERIMENT = "experiment"
PAGE_COMPLETE = "complete"

WELCOME_EMOTION = "welcoming1"
NEXT_QUESTION_EMOTION = "understanding1"
FINAL_QUESTION_EMOTION = "enthusiastic2"
COMPLETION_EMOTION = "grateful1"
