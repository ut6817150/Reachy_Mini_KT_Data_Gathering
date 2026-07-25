"""Generate all study speech assets with the macOS ``say`` command."""

import json
from pathlib import Path
import shutil
import subprocess
import wave

from services.question_loader import load_questions
from services.speech import MANIFEST_PATH, expected_speech_assets, speech_file


ROOT = Path(__file__).resolve().parents[1]


def generate_wav(say: str, text: str, output: Path) -> None:
    temporary = output.with_name(f".{output.stem}.tmp.wav")
    temporary.unlink(missing_ok=True)
    result = subprocess.run(
        [
            say,
            "-o",
            str(temporary),
            "--file-format=WAVE",
            "--data-format=LEI16@24000",
            "--channels=1",
            text,
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(result.stderr.strip() or f"Could not generate {output.name}")
    try:
        with wave.open(str(temporary), "rb") as audio:
            valid = (
                audio.getnchannels() == 1
                and audio.getsampwidth() == 2
                and audio.getframerate() == 24_000
                and audio.getnframes() > 0
            )
    except (OSError, wave.Error):
        valid = False
    if not valid:
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"macOS generated an invalid WAV file for {output.name}")
    temporary.replace(output)


def main() -> None:
    say = shutil.which("say")
    if not say:
        raise RuntimeError("The macOS 'say' command is unavailable.")

    questions = load_questions(ROOT / "questions" / "questions.md")
    assets = expected_speech_assets(questions)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    for number, (filename, text) in enumerate(assets.items(), start=1):
        output = speech_file(filename)
        print(f"[{number}/{len(assets)}] Generating {filename}")
        generate_wav(say, text, output)

    MANIFEST_PATH.write_text(
        json.dumps(assets, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Prepared {len(assets)} speech files in {MANIFEST_PATH.parent}")


if __name__ == "__main__":
    main()
