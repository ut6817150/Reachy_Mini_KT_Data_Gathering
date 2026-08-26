"""Researcher configuration and participant setup pages."""

import streamlit as st

from services.experiment_controller import ExperimentController
from services.question_loader import QuestionFormatError, load_questions
from services.reachy_controller import (
    CONNECTION_MODES,
    WIRED,
    ReachyConnectionError,
    ReachyController,
)
from services.recorder import CAMERA_NAME, MICROPHONE_NAME, RecordingError
from services.speech import SPEECH_DIR, SpeechError, speech_file, validate_speech_assets
from services.storage import SessionStorage, normalize_participant_id
from ui.constants import (
    PAGE_PARTICIPANT,
    PAGE_RESEARCHER,
    PAGE_WELCOME,
    QUESTIONS_PATH,
    RECORDINGS_ROOT,
    WELCOME_EMOTION,
)
from ui.media import render_device_test
from ui.robot import queue_robot_response
from ui.state import (
    connected_reachy,
    disconnect_reachy,
    navigate_to,
    reset_participant_state,
)


def render_reachy_connection(
    mode: str,
    wireless_host: str,
) -> bool:
    signature = (mode, wireless_host.strip())
    controller = connected_reachy()
    matches = (
        controller is not None
        and st.session_state.get("reachy_connection_signature") == signature
    )

    if controller is not None and not matches:
        st.warning(
            "Connection settings changed. Disconnect and reconnect to apply them."
        )

    left, right = st.columns(2)
    with left:
        if st.button(
            "Connect to Reachy",
            type="primary",
            width="stretch",
            disabled=controller is not None,
        ):
            candidate = None
            try:
                candidate = ReachyController(mode, wireless_host)
                with st.spinner("Connecting to Reachy and preparing speech…"):
                    label = candidate.connect()
                    candidate.prepare_sounds(sorted(SPEECH_DIR.glob("*.wav")))
            except (ReachyConnectionError, ValueError) as error:
                if candidate is not None:
                    candidate.disconnect()
                st.error(str(error))
            else:
                st.session_state["reachy_controller"] = candidate
                st.session_state["reachy_connection_signature"] = signature
                st.session_state["reachy_connection_label"] = label
                st.rerun()

    with right:
        if st.button("Disconnect Reachy", width="stretch", disabled=controller is None):
            disconnect_reachy()
            st.rerun()

    if matches:
        label = st.session_state.get("reachy_connection_label", "Reachy Mini")
        st.success(f"Connected — {label}")
    else:
        st.info("Connect successfully before beginning participant sessions.")
    return matches


def render_researcher_page() -> None:
    st.title("Researcher configuration")
    st.caption(
        "Complete these checks once. The settings remain active while participants "
        "complete their sessions."
    )

    st.subheader("1. Reachy Mini")
    controller = connected_reachy()
    saved = controller.settings() if controller else {}
    saved_mode = str(saved.get("mode", WIRED))
    if saved_mode not in CONNECTION_MODES.values():
        saved_mode = WIRED
    labels = list(CONNECTION_MODES)
    saved_label = next(
        label for label in labels if CONNECTION_MODES[label] == saved_mode
    )
    selected_label = st.selectbox(
        "Connection type",
        options=labels,
        index=labels.index(saved_label),
    )
    mode = CONNECTION_MODES[selected_label]
    if mode == WIRED:
        wireless_host = "reachy-mini.local"
        st.caption("Uses the Reachy Mini Control daemon on localhost:8000.")
    else:
        wireless_host = st.text_input(
            "Wireless hostname or IP",
            value=str(saved.get("wireless_host", "reachy-mini.local")),
            help="Do not include http:// or a path.",
        )

    reachy_ready = render_reachy_connection(mode, wireless_host)
    speaker_volume = st.slider(
        "Reachy speaker volume",
        min_value=0,
        max_value=100,
        value=60,
        step=5,
        key="reachy_speaker_volume",
        disabled=not reachy_ready,
        help="Sets the robot's global output volume for speech and other sounds.",
    )
    if st.button(
        "Apply Reachy speaker volume",
        width="stretch",
        disabled=not reachy_ready,
    ):
        controller = connected_reachy()
        assert controller is not None
        try:
            controller.set_volume(speaker_volume)
        except (ReachyConnectionError, ValueError) as error:
            st.error(f"Reachy volume could not be changed: {error}")
        else:
            st.success(
                f"Volume command sent at {speaker_volume}%. "
                "Use the speaker test to confirm it."
            )

    if reachy_ready and st.button("Wake Reachy", width="stretch"):
        controller = connected_reachy()
        assert controller is not None
        try:
            with st.spinner("Waking Reachy…"):
                controller.wake_up()
        except ReachyConnectionError as error:
            st.error(f"Reachy could not wake up: {error}")
        else:
            st.success("Reachy is awake and its motors are enabled.")

    if reachy_ready and st.button("Play Reachy speaker test", width="stretch"):
        controller = connected_reachy()
        assert controller is not None
        try:
            with st.spinner("Playing test phrase through Reachy…"):
                st.session_state["robot_speaker"].play(
                    controller, speech_file("speaker_test.wav")
                )
        except (ReachyConnectionError, SpeechError, RecordingError, OSError) as error:
            st.error(f"Reachy connected, but the speaker test failed: {error}")
        else:
            st.success("Reachy speaker test played successfully.")

    st.subheader("2. MacBook recording")
    st.caption("The app always uses the built-in MacBook devices.")
    st.write(f"**Camera:** {CAMERA_NAME}")
    st.write(f"**Microphone:** {MICROPHONE_NAME}")
    test_ready = render_device_test("researcher")

    st.divider()
    researcher_ready = reachy_ready and test_ready
    if st.button(
        "Begin participant sessions",
        type="primary",
        width="stretch",
        disabled=not researcher_ready,
    ):
        st.session_state["researcher_configured"] = True
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)

    if not researcher_ready:
        missing = []
        if not reachy_ready:
            missing.append("Reachy connection")
        if not test_ready:
            missing.append("reviewed device test")
        st.caption("Required before continuing: " + ", ".join(missing) + ".")


def render_participant_page() -> None:
    if st.session_state.get("researcher_configured") is not True:
        navigate_to(PAGE_RESEARCHER)

    with st.sidebar:
        st.caption("Researcher controls")
        if st.button("Researcher settings", width="stretch"):
            navigate_to(PAGE_RESEARCHER)

    st.title("Participant setup")
    st.write("Please enter your participant ID and check the recording devices.")
    notice = st.session_state.pop("session_end_notice", None)
    if isinstance(notice, str):
        st.warning(notice)

    participant_input = st.text_input(
        "Participant ID",
        key="participant_id_input",
        placeholder="e.g. Participant 001",
    )
    participant_id = None
    if participant_input:
        try:
            participant_id = normalize_participant_id(participant_input)
        except ValueError as error:
            st.error(str(error))

    st.subheader("Recording devices")
    st.write(f"**Camera:** {CAMERA_NAME}")
    st.write(f"**Microphone:** {MICROPHONE_NAME}")
    st.subheader("Camera and microphone test")
    st.caption(
        "Record a short practice clip, move in front of the camera, and say a few "
        "words. This clip is temporary and is not saved with your responses."
    )
    render_device_test("participant")

    if st.button("Start", type="primary", width="stretch", disabled=not participant_id):
        assert participant_id is not None
        try:
            questions = load_questions(QUESTIONS_PATH)
            validate_speech_assets(questions)
            controller = connected_reachy()
            if controller is None:
                raise ReachyConnectionError(
                    "Reachy is no longer connected. Ask the researcher for help."
                )
            storage = SessionStorage.create(
                RECORDINGS_ROOT,
                participant_id,
                controller.settings(),
                questions,
            )
        except (
            QuestionFormatError,
            ReachyConnectionError,
            SpeechError,
            OSError,
            ValueError,
        ) as error:
            st.error(f"The session could not start: {error}")
        else:
            st.session_state["experiment_controller"] = ExperimentController(questions)
            st.session_state["session_storage"] = storage
            st.session_state["spoken_question_number"] = None
            queue_robot_response(
                emotion=WELCOME_EMOTION,
                audio_path=speech_file("welcome.wav"),
                status="Reachy is welcoming you…",
            )
            navigate_to(PAGE_WELCOME)
