# Reachy Mini Participant Study

A local Streamlit application for conducting a ten-question participant study
with Reachy Mini. The researcher selects an external camera and microphone,
participants enter their ID, and the app records one synchronized MP4 response
per question.

## Project structure

- `streamlit_app.py` — Streamlit entry point
- `scripts/` — experiment, robot, recording, device, question, and storage logic
- `questions/questions.md` — editable study questions
- `recordings/` — participant/session folders containing MP4 recordings
- `tests/` — automated checks that do not contain participant data

## Requirements

- Python 3.11 or newer
- Reachy Mini Control with its daemon running
- FFmpeg installed on the computer running Streamlit

Development setup and usage instructions will be added as the application is
implemented.

## Device discovery diagnostic

Once the requirements are installed, list the cameras and microphones visible
to the application with:

```bash
python -m scripts.device_discovery
```

The command prints JSON containing recording identifiers, display names,
backends, and any non-fatal setup warnings. FFmpeg-native identifiers are used
when possible so the selected devices can later be passed directly to the
recorder.

## Reachy Mini connection modes

The application supports the same three routes as the Reachy Mini SDK:

- **Automatic** — try the daemon on `localhost:8000`, then fall back to the
  wireless host.
- **Wired / Reachy Mini Lite** — connect only to the daemon started by Reachy
  Mini Control on `localhost:8000`.
- **Wireless Reachy Mini** — connect to `reachy-mini.local:8000`, or a manually
  supplied hostname/IP address.

The study application always uses `spawn_daemon=False`. Keep Reachy Mini Control
open for a wired robot; a wireless robot uses its onboard daemon.

## Run the application

Install the Python requirements and FFmpeg, then start Streamlit from the
repository root:

```bash
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

The application starts with a researcher-only configuration screen. The
researcher connects Reachy, can play a speaker test, selects default recording
devices and a native, 16:9, or 4:3 video format, reviews a live camera preview,
and records a five-second MP4 to verify camera and microphone input. Fixed
ratios preserve the complete camera image by adding padding rather than cropping.

After setup, each participant enters their ID and uses the camera and microphone
chosen by the researcher. They can record and play a temporary five-second clip,
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
