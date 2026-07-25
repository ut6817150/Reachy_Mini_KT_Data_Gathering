"""Safe participant/session paths and durable JSON metadata."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Callable
from uuid import uuid4

from services.recorder import CAMERA_NAME, MICROPHONE_NAME


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def normalize_participant_id(value: str) -> str:
    """Clean a participant ID for use as a recording-folder name."""

    participant_id = re.sub(r"\s+", "_", value.strip())
    participant_id = participant_id.replace("/", "_").replace("\\", "_")
    if participant_id in {"", ".", ".."}:
        raise ValueError("Please enter a participant ID.")
    return participant_id


class SessionStorage:
    """Own the directory and metadata for one participant session."""

    def __init__(
        self,
        session_dir: Path,
        metadata: dict[str, Any],
        clock: Clock,
    ) -> None:
        self.session_dir = session_dir
        self.metadata_path = session_dir / "session.json"
        self.metadata = metadata
        self.clock = clock

    @classmethod
    def create(
        cls,
        root: str | Path,
        participant_id: str,
        reachy_settings: dict[str, object],
        questions: tuple[str, ...],
        *,
        clock: Clock = _utc_now,
    ) -> "SessionStorage":
        participant_id = normalize_participant_id(participant_id)
        root_path = Path(root).expanduser().resolve()
        now = clock()
        session_id = now.strftime("session_%Y%m%d_%H%M%S_%f") + f"_{uuid4().hex[:6]}"
        session_dir = root_path / participant_id / session_id
        session_dir.mkdir(parents=True, exist_ok=False)
        session_dir.resolve().relative_to(root_path)

        metadata = {
            "schema_version": 1,
            "participant_id": participant_id,
            "session_id": session_id,
            "started_at": _iso_timestamp(now),
            "completed_at": None,
            "completed": False,
            "researcher_configuration": {
                "reachy": reachy_settings,
                "camera": CAMERA_NAME,
                "microphone": MICROPHONE_NAME,
            },
            "questions": [
                {
                    "number": number,
                    "text": text,
                    "recording": None,
                    "recording_started_at": None,
                    "recording_completed_at": None,
                    "duration_seconds": None,
                }
                for number, text in enumerate(questions, start=1)
            ],
        }
        storage = cls(session_dir, metadata, clock)
        storage._write_metadata()
        return storage

    def recording_path(self, question_number: int) -> Path:
        if question_number <= 0:
            raise ValueError("question_number must be greater than zero")
        path = self.session_dir / f"question_{question_number:02d}.mp4"
        if path.exists():
            raise FileExistsError(f"Recording already exists: {path}")
        return path

    def mark_recording_started(self, question_number: int) -> None:
        self._question_entry(question_number)["recording_started_at"] = _iso_timestamp(
            self.clock()
        )
        self._write_metadata()

    def mark_recording_complete(
        self,
        question_number: int,
        path: Path,
        duration_seconds: float,
    ) -> None:
        entry = self._question_entry(question_number)
        entry["recording"] = path.name
        entry["recording_completed_at"] = _iso_timestamp(self.clock())
        entry["duration_seconds"] = round(duration_seconds, 3)
        self._write_metadata()

    def finalize(self) -> None:
        self.metadata["completed"] = True
        self.metadata["completed_at"] = _iso_timestamp(self.clock())
        self._write_metadata()

    def _question_entry(self, question_number: int) -> dict[str, Any]:
        try:
            entry = self.metadata["questions"][question_number - 1]
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
