"""Safe participant/session paths and durable JSON metadata."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from scripts.configuration import (
    ParticipantConfiguration,
    ResearcherConfiguration,
    normalize_participant_id,
)
from scripts.question_loader import Question
from scripts.recorder import RecordingResult


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class SessionStorage:
    """Own the directory and metadata for one participant session."""

    root: Path
    session_dir: Path
    metadata_path: Path
    metadata: dict[str, Any]
    clock: Clock = _utc_now

    @classmethod
    def create(
        cls,
        root: str | Path,
        researcher: ResearcherConfiguration,
        participant: ParticipantConfiguration,
        questions: tuple[Question, ...],
        *,
        clock: Clock = _utc_now,
    ) -> "SessionStorage":
        participant_id = normalize_participant_id(participant.participant_id)
        root_path = Path(root).expanduser().resolve()
        participant_dir = root_path / participant_id
        now = clock()
        session_id = now.strftime("session_%Y%m%d_%H%M%S_%f") + f"_{uuid4().hex[:6]}"
        session_dir = participant_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=False)

        # Assert the resolved session remains under the configured recordings root.
        session_dir.resolve().relative_to(root_path)
        metadata = {
            "schema_version": 1,
            "participant_id": participant_id,
            "session_id": session_id,
            "started_at": _iso_timestamp(now),
            "completed_at": None,
            "completed": False,
            "researcher_configuration": researcher.to_dict(),
            "participant_configuration": participant.to_dict(),
            "questions": [
                {
                    "number": question.number,
                    "text": question.text,
                    "recording": None,
                    "recording_started_at": None,
                    "recording_completed_at": None,
                    "duration_seconds": None,
                }
                for question in questions
            ],
        }
        storage = cls(
            root=root_path,
            session_dir=session_dir,
            metadata_path=session_dir / "session.json",
            metadata=metadata,
            clock=clock,
        )
        storage._write_metadata()
        return storage

    def recording_path(self, question_number: int) -> Path:
        if question_number <= 0:
            raise ValueError("question_number must be greater than zero")
        path = self.session_dir / f"question_{question_number:02d}.mp4"
        path.resolve().relative_to(self.session_dir.resolve())
        if path.exists():
            raise FileExistsError(f"Recording already exists: {path}")
        return path

    def mark_recording_started(self, question_number: int) -> None:
        entry = self._question_entry(question_number)
        entry["recording_started_at"] = _iso_timestamp(self.clock())
        self._write_metadata()

    def mark_recording_complete(
        self, question_number: int, result: RecordingResult
    ) -> None:
        entry = self._question_entry(question_number)
        entry["recording"] = result.path.name
        entry["recording_completed_at"] = _iso_timestamp(self.clock())
        entry["duration_seconds"] = round(result.duration_seconds, 3)
        self._write_metadata()

    def finalize(self) -> None:
        self.metadata["completed"] = True
        self.metadata["completed_at"] = _iso_timestamp(self.clock())
        self._write_metadata()

    def _question_entry(self, question_number: int) -> dict[str, Any]:
        entries = self.metadata["questions"]
        try:
            entry = entries[question_number - 1]
        except (IndexError, TypeError) as error:
            raise ValueError(f"Unknown question number: {question_number}") from error
        if entry["number"] != question_number:
            raise ValueError(f"Unknown question number: {question_number}")
        return entry

    def _write_metadata(self) -> None:
        temporary_path = self.metadata_path.with_suffix(".json.tmp")
        temporary_path.write_text(
            json.dumps(self.metadata, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self.metadata_path)
