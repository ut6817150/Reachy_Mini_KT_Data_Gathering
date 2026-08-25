# Reachy Mini Participant Study

A local Streamlit application for conducting one unscored practice question and
twelve scored study questions with Reachy Mini. It always uses the built-in
MacBook Pro camera and microphone; participants enter their ID and the app
records one synchronized MP4 response per question.

## Study workflow

1. The researcher selects a wired or wireless Reachy Mini connection.
2. The researcher connects and wakes Reachy, runs its speaker test, and records
   a mandatory five-second camera and microphone test.
3. The participant enters an ID. Leading and trailing spaces are removed, and
   spaces within the ID become underscores for the participant folder name.
4. The participant may record an optional five-second device-check clip. This is
   separate from the recorded Question 0 warm-up.
5. Reachy welcomes the participant and explains how to answer.
6. Reachy presents unscored Question 0 as a warm-up, followed by scored Questions
   1–12. The participant may repeat or skip each prepared voiceover.
7. The participant selects **Begin response**, answers aloud, and selects
   **End Response** to save the MP4.
8. Reachy acknowledges the response while emoting, then returns to neutral.
   The participant selects **Next Question** when ready.
9. After Question 12, **Finish** opens the completion page. **End session**
   finalizes the metadata, puts Reachy to sleep, and returns to participant setup.

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
- `services/experiment_controller.py` — question-loop state
- `services/question_loader.py` — Markdown question loading
- `services/storage.py` — participant folders and session metadata
- `questions/questions.md` — editable study questions
- `assets/speech/Qwen3-TTS-Aiden/` — active prepared Aiden WAV files
- `assets/speech/default/` — legacy prepared macOS voice files
- `extraction/generate_aiden_speech.ipynb` — local Aiden speech generator
- `extraction/generate_macos_speech.ipynb` — legacy macOS speech generator
- `recordings/` — participant/session folders containing MP4 recordings
- `tests/` — automated checks that do not contain participant data

## Requirements

- macOS with Python 3.11 or newer
- Reachy Mini Control for a wired connection or wireless robot setup
- FFmpeg installed on the computer running Streamlit
- A physical Reachy Mini running a compatible daemon

## Recording devices

There are no camera or microphone selectors. On macOS, FFmpeg opens
`MacBook Pro Camera` and `MacBook Pro Microphone` directly by name. This avoids
the changing numeric device indices caused by virtual cameras such as Reachy.

FFmpeg requests an exact `1920x1080` landscape input at 30 fps, then creates an
H.264/AAC MP4. Video timestamps and asynchronous audio resampling are used to
limit camera/microphone drift. macOS must grant camera and microphone permission
to the terminal or application that starts Streamlit.

## Reachy Mini connection modes

The application provides two explicit Reachy Mini connection modes:

- **Wired / Reachy Mini Lite** — connect only to the daemon started by Reachy
  Mini Control on `localhost:8000`.
- **Wireless Reachy Mini** — connect to `reachy-mini.local:8000`, or a manually
  supplied hostname/IP address.

The connection port and timeout are fixed at `8000` and five seconds, so the
researcher only chooses wired or wireless and, for wireless, enters the host.

The study application always uses `spawn_daemon=False`. Keep Reachy Mini Control
open for a wired robot; a wireless robot uses its onboard daemon. The computer
and a wireless robot must be on the same network. If `reachy-mini.local` does not
resolve, enter the robot's IP address shown by Reachy Mini Control.

The connection remains active across participant sessions. Reachy speech and
recorded emotions use the same connection. During researcher connection, wired
Reachy uses the speech files directly from the laptop. Wireless Reachy receives
each prepared WAV once and reuses the robot-side copy for low-latency playback
throughout subsequent participant sessions. Reconnecting after a robot restart
uploads the files again.

## Prepared speech

Participant sessions do not generate speech live. The active Aiden voice set contains
18 prepared files:

- one speaker test;
- one welcome message;
- three acknowledgement/completion messages;
- one practice-question voiceover and twelve scored-question voiceovers.

The files are stored in `assets/speech/Qwen3-TTS-Aiden/` as mono, 16-bit, 24 kHz
WAV audio. `manifest.json` records the exact source text for every file, while
`generation.json` records the Qwen3-TTS model, Aiden speaker, and generation
settings. When a participant starts, the application verifies that all files
exist and that the manifest still matches `questions/questions.md`.

Regenerate the active Aiden files by running all cells in:

```text
extraction/generate_aiden_speech.ipynb
```

Run the notebook again whenever a question or fixed study message changes. The
older macOS `say` generator remains available in
`extraction/generate_macos_speech.ipynb`. It writes only to
`assets/speech/default/` and does not replace the active Aiden files.

## Run the application

From the repository root, create or activate a Python environment, install the
requirements, prepare the speech files, and start Streamlit:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run streamlit_app.py
```

Open the local URL printed by Streamlit, normally:

```text
http://localhost:8501
```

Install FFmpeg first if it is unavailable:

```bash
brew install ffmpeg
```

## Researcher configuration

The application starts with a researcher-only configuration screen. The
researcher connects Reachy, can play a speaker test, and records and reviews a
five-second MP4 to verify the built-in camera and microphone. Recordings use a
landscape 1920×1080 camera mode.

Both the Reachy connection and reviewed researcher recording test are required
before **Begin participant sessions** is enabled. On participant setup,
researcher settings remain available in the collapsed sidebar.

## Participant interaction

The optional participant device-check clip has a visible five-second countdown
and is stored only in the system temporary directory. It is not copied into
study data and is separate from the recorded Question 0 warm-up.

The welcome page asks participants to explain every answer aloud, including
their reasoning and numerical calculations. Reachy reads the same instructions.
Each question remains visible while Reachy speaks it. Recording starts only
after **Begin response** is selected and stops when **End Response** is selected.

After the practice response is saved, **Begin Question 1** starts the scored
sequence. For scored responses, Reachy speaks and emotes at the same time and
**Next Question** is shown only after that response finishes. After Question 12
the button becomes **Finish**.

The researcher wakes Reachy from the researcher configuration page. Starting a
participant session does not send another wake command. Reachy remains awake and
still during response recordings, plays `understanding1` between ordinary
questions, `enthusiastic2` before Question 12, and `grateful1` when the
interaction is complete. Emotion sounds are disabled because the prepared study
speech plays separately. After every emotion, Reachy smoothly returns its head,
antennas, and body yaw to neutral over 0.5 seconds. Pressing **End session** puts
Reachy to sleep before returning to the next participant's start page.

## Study data

Recordings are stored as:

```text
recordings/
└── PARTICIPANT_ID/
    └── session_YYYYMMDD_HHMMSS_.../
        ├── question_00.mp4  # unscored practice response
        ├── question_01.mp4
        ├── ...
        ├── question_12.mp4
        └── session.json
```

`session.json` stores the normalized participant ID, timestamps, Reachy
configuration, question text, scoring status, recording filenames, and response
durations. Question 0 has `"scored": false`; Questions 1–12 have
`"scored": true`.

The application contains no transcription, live TTS, or LLM grading code.

## Tests

Run the hardware-independent test suite with:

```bash
python -m pytest -q
```
