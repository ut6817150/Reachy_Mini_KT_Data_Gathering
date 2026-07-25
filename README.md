# Reachy Mini Participant Study

A local Streamlit application for conducting a ten-question participant study
with Reachy Mini. It always uses the built-in MacBook Pro camera and microphone;
participants enter their ID and the app records one synchronized MP4 response
per question.

## Project structure

- `streamlit_app.py` — Streamlit configuration and page router
- `ui/setup_pages.py` — researcher and participant setup pages
- `ui/study_pages.py` — welcome, question loop, and completion pages
- `ui/robot.py` — non-blocking Reachy speech and emotion UI
- `ui/media.py` — five-second camera and microphone test UI
- `ui/state.py` — navigation and Streamlit session state
- `services/recorder.py` — synchronized MP4 recording with FFmpeg
- `services/reachy_controller.py` — wired and wireless Reachy connection and actions
- `services/speech.py` — prepared speech paths, validation, and Reachy playback
- `services/generate_speech.py` — one-time macOS speech-file generator
- `services/experiment_controller.py` — question-loop state
- `services/question_loader.py` — Markdown question loading
- `services/storage.py` — participant folders and session metadata
- `questions/questions.md` — editable study questions
- `assets/speech/default/` — default prepared WAV files and their text manifest
- `recordings/` — participant/session folders containing MP4 recordings
- `tests/` — automated checks that do not contain participant data

## Requirements

- macOS with Python 3.11 or newer
- Reachy Mini Control with its daemon running
- FFmpeg installed on the computer running Streamlit

## Recording devices

There are no camera or microphone selectors. On macOS, FFmpeg opens
`MacBook Pro Camera` and `MacBook Pro Microphone` directly by name. This avoids
the changing numeric device indices caused by virtual cameras such as Reachy.

## Reachy Mini connection modes

The application provides two explicit Reachy Mini connection modes:

- **Wired / Reachy Mini Lite** — connect only to the daemon started by Reachy
  Mini Control on `localhost:8000`.
- **Wireless Reachy Mini** — connect to `reachy-mini.local:8000`, or a manually
  supplied hostname/IP address.

The connection port and timeout are fixed at `8000` and five seconds, so the
researcher only chooses wired or wireless and, for wireless, enters the host.

The study application always uses `spawn_daemon=False`. Keep Reachy Mini Control
open for a wired robot; a wireless robot uses its onboard daemon.

## Run the application

Install the Python requirements and FFmpeg. Then generate the speech files once
and start Streamlit from the repository root:

```bash
python -m pip install -r requirements.txt
python -m services.generate_speech
streamlit run streamlit_app.py
```

Run the speech-generation command again whenever `questions/questions.md` or a
fixed study message changes. Speech is generated before the study—not while a
participant is waiting—and the app refuses to start a session if the prepared
files no longer match the current questions.

The application starts with a researcher-only configuration screen. The
researcher connects Reachy, can play a speaker test, and records and reviews a
five-second MP4 to verify the built-in camera and microphone. Recordings use a
landscape 1920×1080 camera mode.

After setup, each participant enters their ID. They can record and play a temporary five-second clip,
with a visible countdown, to check the camera framing and microphone before
starting. A welcome screen then asks participants to explain every answer aloud,
including their reasoning and any numerical calculations, and Reachy reads the
same welcome instructions aloud. Reachy then asks each question, the participant
can select **Skip Voiceover** to stop the question audio early, starts and ends
one MP4 recording per response, and the app advances through all ten questions.
After each response is saved and Reachy finishes acknowledging
it, the participant presses **Next Question** to advance. After Question 10 this
button becomes **Finish**. Ending the session returns to a clean participant
start page while retaining the researcher configuration and Reachy connection.
On the participant setup screen, researcher settings remain available from the
collapsed sidebar rather than appearing in the participant-facing form.

Reachy wakes and plays `welcoming1` when a participant starts. It remains awake
and still during response recordings, plays `understanding1` between ordinary
questions, `enthusiastic2` before the final question, and `grateful1` when the
interaction is complete. Pressing **End session** puts Reachy to sleep before
returning to the next participant's start page.

Recordings are stored as:

```text
recordings/
└── PARTICIPANT_ID/
    └── session_YYYYMMDD_HHMMSS_.../
        ├── question_01.mp4
        ├── ...
        ├── question_10.mp4
        └── session.json
```

The application contains no transcription or LLM grading code.
