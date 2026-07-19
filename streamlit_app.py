"""Streamlit interface for the Reachy Mini participant study."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
import html
from pathlib import Path
from typing import Any, Callable, TypeVar

import streamlit as st
import streamlit.components.v1 as components

from scripts.configuration import (
    ParticipantConfiguration,
    ResearcherConfiguration,
    VideoAspectRatio,
    normalize_participant_id,
)
from scripts.device_discovery import (
    CameraDevice,
    DeviceCatalog,
    MicrophoneDevice,
    discover_media_devices,
)
from scripts.experiment_controller import ExperimentController, ExperimentStage
from scripts.live_preview import (
    LiveCameraPreview,
    LivePreviewError,
    camera_preview_signature,
)
from scripts.question_loader import QuestionFormatError, load_questions
from scripts.reachy_controller import (
    ReachyConnectionConfig,
    ReachyConnectionError,
    ReachyController,
    RobotConnectionMode,
    connection_mode_labels,
)
from scripts.recorder import (
    FFmpegRecorder,
    RecordingError,
    record_device_test,
)
from scripts.speech import RobotSpeaker, SpeechError
from scripts.storage import SessionStorage


ROOT = Path(__file__).resolve().parent
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

WELCOME_MESSAGE = (
    "Welcome, and thank you for taking part in this study. You will be asked "
    "10 questions. For every question, please answer aloud and explain how you "
    "arrived at your answer. Include any numerical calculations you use, and "
    "say each step out loud."
)

PARTICIPANT_STATE_KEYS = (
    "participant_configuration",
    "experiment_controller",
    "session_storage",
    "active_recorder",
    "spoken_question_number",
    "participant_notice",
    "participant_id_input",
    "participant_device_test_signature",
    "participant_device_test_path",
    "pending_robot_response",
    "robot_action_future",
    "robot_action_status",
    "robot_action_error_context",
    "robot_action_question_number",
    "robot_action_skippable",
    "robot_action_skipped",
)

DeviceType = TypeVar("DeviceType", CameraDevice, MicrophoneDevice)


st.set_page_config(
    page_title="Reachy Mini Participant Study",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False, ttl=30)
def cached_media_devices() -> DeviceCatalog:
    """Avoid reopening camera devices on every normal Streamlit rerun."""

    return discover_media_devices()


@st.cache_resource
def robot_action_executor() -> ThreadPoolExecutor:
    """Run blocking robot audio and motion without blocking Streamlit rendering."""

    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="reachy-action")


def initialize_state() -> None:
    st.session_state.setdefault("page", PAGE_RESEARCHER)
    st.session_state.setdefault("robot_speaker", RobotSpeaker())


def navigate_to(page: str) -> None:
    """Change app screens and request a browser scroll reset."""

    st.session_state["page"] = page
    st.session_state["scroll_to_top"] = True
    st.rerun()


def apply_pending_scroll_reset() -> None:
    if st.session_state.pop("scroll_to_top", False) is not True:
        return
    components.html(
        """
        <script>
            const parentWindow = window.parent;
            const parentDocument = parentWindow.document;
            const scrollToTop = () => {
                parentWindow.scrollTo(0, 0);
                parentDocument
                    .querySelectorAll(
                        '[data-testid="stAppViewContainer"], '
                        + '[data-testid="stMain"], section.main, .stMain'
                    )
                    .forEach((element) => {
                        element.scrollTop = 0;
                        element.scrollTo(0, 0);
                    });
            };
            parentWindow.requestAnimationFrame(() =>
                parentWindow.requestAnimationFrame(scrollToTop)
            );
            parentWindow.setTimeout(scrollToTop, 100);
            parentWindow.setTimeout(scrollToTop, 400);
        </script>
        """,
        height=0,
        width=0,
    )


def device_signature(
    camera: CameraDevice,
    microphone: MicrophoneDevice,
    aspect_ratio: VideoAspectRatio,
) -> tuple[str, ...]:
    return (
        camera.backend,
        camera.identifier,
        microphone.backend,
        microphone.identifier,
        aspect_ratio.value,
    )


def connection_signature(config: ReachyConnectionConfig) -> tuple[str, str, int, float]:
    return (
        config.mode.value,
        config.wireless_host,
        config.port,
        config.timeout_seconds,
    )


def disconnect_reachy() -> None:
    controller = st.session_state.pop("reachy_controller", None)
    st.session_state.pop("reachy_connection_signature", None)
    st.session_state.pop("reachy_connection_label", None)
    st.session_state.pop("reachy_audio_tested", None)
    if isinstance(controller, ReachyController):
        controller.disconnect()


def connected_reachy() -> ReachyController | None:
    controller = st.session_state.get("reachy_controller")
    if isinstance(controller, ReachyController) and controller.is_connected:
        return controller
    return None


def reset_participant_state() -> None:
    recorder = st.session_state.get("active_recorder")
    if isinstance(recorder, FFmpegRecorder):
        recorder.cancel()
    for key in PARTICIPANT_STATE_KEYS:
        st.session_state.pop(key, None)


def close_live_camera_preview() -> None:
    preview = st.session_state.pop("live_camera_preview", None)
    if isinstance(preview, LiveCameraPreview):
        preview.close()
    st.session_state.pop("live_camera_preview_error", None)
    st.session_state.pop("live_camera_preview_error_signature", None)


@st.fragment(run_every=0.2)
def render_live_camera_preview(
    camera: CameraDevice,
    aspect_ratio: VideoAspectRatio,
) -> None:
    """Refresh one live frame while keeping the camera open between reruns."""

    signature = camera_preview_signature(camera)
    preview = st.session_state.get("live_camera_preview")
    if isinstance(preview, LiveCameraPreview) and preview.signature != signature:
        close_live_camera_preview()
        preview = None

    error_signature = st.session_state.get("live_camera_preview_error_signature")
    if error_signature == signature:
        st.warning(str(st.session_state.get("live_camera_preview_error")))
        if st.button("Retry live preview", width="stretch"):
            st.session_state.pop("live_camera_preview_error", None)
            st.session_state.pop("live_camera_preview_error_signature", None)
            st.rerun()
        return

    try:
        if not isinstance(preview, LiveCameraPreview):
            preview = LiveCameraPreview(camera)
            st.session_state["live_camera_preview"] = preview
        frame = preview.read(aspect_ratio)
    except LivePreviewError as error:
        close_live_camera_preview()
        st.session_state["live_camera_preview_error"] = str(error)
        st.session_state["live_camera_preview_error_signature"] = signature
        st.warning(str(error))
        return

    st.image(
        frame,
        channels="RGB",
        width="stretch",
        caption=f"Live — {camera.label} · {aspect_ratio.label}",
    )


def queue_robot_response(
    *,
    emotion: str | None = None,
    message: str | None = None,
    wake_up: bool = False,
    status: str = "Reachy is responding…",
) -> None:
    """Defer robot work until the destination page has been rendered."""

    st.session_state["pending_robot_response"] = {
        "emotion": emotion,
        "message": message,
        "wake_up": wake_up,
        "status": status,
    }


def robot_action_in_progress() -> bool:
    return isinstance(st.session_state.get("robot_action_future"), Future)


def start_robot_action(
    action: Callable[[], Any],
    *,
    status: str,
    error_context: str,
    question_number: int | None = None,
    skippable: bool = False,
) -> None:
    """Submit one robot action to the session's serialized background worker."""

    if robot_action_in_progress():
        return
    st.session_state["robot_action_future"] = robot_action_executor().submit(action)
    st.session_state["robot_action_status"] = status
    st.session_state["robot_action_error_context"] = error_context
    st.session_state["robot_action_question_number"] = question_number
    st.session_state["robot_action_skippable"] = skippable
    st.session_state["robot_action_skipped"] = False


def start_pending_robot_response() -> bool:
    """Start a queued transition response once its destination page is visible."""

    pending = st.session_state.pop("pending_robot_response", None)
    if not isinstance(pending, dict):
        return False

    controller = connected_reachy()
    if controller is None:
        st.session_state["participant_notice"] = (
            "Reachy is no longer connected. Ask the researcher for help."
        )
        return False
    speaker = st.session_state["robot_speaker"]

    def perform_response() -> None:
        if pending.get("wake_up") is True:
            controller.wake_up()
        emotion = pending.get("emotion")
        message = pending.get("message")
        has_emotion = isinstance(emotion, str) and bool(emotion)
        has_message = isinstance(message, str) and bool(message)
        if has_emotion and has_message:
            speaker.speak_during(
                controller,
                message,
                lambda: controller.play_emotion(emotion),
            )
        elif has_emotion:
            controller.play_emotion(emotion)
        elif has_message:
            speaker.speak(controller, message)

    start_robot_action(
        perform_response,
        status=str(pending.get("status", "Reachy is responding…")),
        error_context="Reachy could not complete its response",
    )
    return True


def start_question_speech(question_number: int, text: str, *, repeat: bool = False) -> None:
    """Start speaking a question and optionally mark it spoken when done."""

    controller = connected_reachy()
    if controller is None:
        st.session_state["participant_notice"] = (
            "Reachy is no longer connected. The question is shown on screen."
        )
        if not repeat:
            st.session_state["spoken_question_number"] = question_number
        return
    speaker = st.session_state["robot_speaker"]
    start_robot_action(
        lambda: speaker.speak(controller, text),
        status=(
            "Reachy is repeating the question…"
            if repeat
            else "Reachy is asking the question…"
        ),
        error_context=(
            "Reachy could not repeat the question"
            if repeat
            else "Reachy could not speak the question"
        ),
        question_number=None if repeat else question_number,
        skippable=True,
    )


def clear_robot_action() -> None:
    for key in (
        "robot_action_future",
        "robot_action_status",
        "robot_action_error_context",
        "robot_action_question_number",
        "robot_action_skippable",
        "robot_action_skipped",
    ):
        st.session_state.pop(key, None)


@st.fragment(run_every=0.25)
def render_robot_action_progress() -> None:
    """Poll a robot task without leaving the rest of the page in a stale state."""

    future = st.session_state.get("robot_action_future")
    if not isinstance(future, Future):
        st.rerun()
    if not future.done():
        st.info(f"🔊 {st.session_state.get('robot_action_status', 'Reachy is responding…')}")
        if st.session_state.get("robot_action_skippable") is True:
            if st.button("Skip Voiceover", width="stretch"):
                controller = connected_reachy()
                speaker = st.session_state.get("robot_speaker")
                if controller is None or not isinstance(speaker, RobotSpeaker):
                    st.warning("Voiceover could not be stopped because Reachy disconnected.")
                else:
                    try:
                        stopped = speaker.stop(controller)
                    except (ReachyConnectionError, OSError) as error:
                        st.warning(f"Voiceover could not be stopped: {error}")
                    else:
                        cancelled = future.cancel() if not stopped else False
                        if stopped or cancelled:
                            st.session_state["robot_action_skipped"] = True
                            st.session_state["robot_action_status"] = "Voiceover skipped."
                        else:
                            st.warning("Voiceover is still starting. Please try again.")
        return

    error: Exception | None = None
    skipped = st.session_state.get("robot_action_skipped") is True
    if not skipped:
        try:
            future.result()
        except Exception as caught_error:
            error = caught_error

    question_number = st.session_state.get("robot_action_question_number")
    error_context = str(
        st.session_state.get("robot_action_error_context", "Reachy action failed")
    )
    clear_robot_action()
    if isinstance(question_number, int):
        st.session_state["spoken_question_number"] = question_number
    if error is not None:
        suffix = " The question is still shown on screen." if question_number else ""
        st.session_state["participant_notice"] = f"{error_context}: {error}.{suffix}"
    st.rerun()


def render_question_text(text: str) -> None:
    """Display long prompts at a readable, responsive size."""

    safe_text = html.escape(text)
    st.markdown(
        f"""
        <style>
            .reachy-question {{
                font-size: clamp(1.1rem, 1.2rem + 0.35vw, 1.45rem);
                font-weight: 500;
                line-height: 1.55;
                padding: 1rem 1.15rem;
                margin: 0.35rem 0 1.25rem 0;
                border: 1px solid rgba(128, 128, 128, 0.28);
                border-radius: 0.65rem;
            }}
        </style>
        <div class="reachy-question">{safe_text}</div>
        """,
        unsafe_allow_html=True,
    )


def default_index(options: tuple[DeviceType, ...], selected: DeviceType) -> int:
    try:
        return options.index(selected)
    except ValueError:
        return 0


def render_reachy_connection(config: ReachyConnectionConfig) -> bool:
    signature = connection_signature(config)
    controller = connected_reachy()
    connected_signature = st.session_state.get("reachy_connection_signature")
    matches = controller is not None and connected_signature == signature

    if controller is not None and not matches:
        st.warning("Connection settings changed. Disconnect and reconnect to apply them.")

    left, right = st.columns(2)
    with left:
        if st.button(
            "Connect to Reachy",
            type="primary",
            width="stretch",
            disabled=controller is not None,
        ):
            candidate = ReachyController(config)
            try:
                with st.spinner("Connecting to Reachy Mini…"):
                    info = candidate.connect()
            except ReachyConnectionError as error:
                candidate.disconnect()
                st.error(str(error))
            else:
                st.session_state["reachy_controller"] = candidate
                st.session_state["reachy_connection_signature"] = signature
                st.session_state["reachy_connection_label"] = info.label
                st.rerun()

    with right:
        if st.button(
            "Disconnect Reachy",
            width="stretch",
            disabled=controller is None,
        ):
            disconnect_reachy()
            st.rerun()

    if matches:
        st.success(
            f"Connected — {st.session_state.get('reachy_connection_label', 'Reachy Mini')}"
        )
    else:
        st.info("Connect successfully before beginning participant sessions.")
    return matches


def render_researcher_page() -> None:
    saved = st.session_state.get("researcher_configuration")
    saved_researcher = saved if isinstance(saved, ResearcherConfiguration) else None

    st.title("Researcher configuration")
    st.caption(
        "Complete these checks once. The settings remain active while participants "
        "complete their sessions."
    )

    notice = st.session_state.pop("researcher_notice", None)
    if isinstance(notice, str):
        st.success(notice)

    st.subheader("1. Reachy Mini")
    labels = connection_mode_labels()
    label_options = list(labels)
    saved_mode = (
        saved_researcher.reachy.mode if saved_researcher else RobotConnectionMode.AUTO
    )
    selected_label = st.selectbox(
        "Connection type",
        options=label_options,
        index=label_options.index(saved_mode.label),
    )
    mode = labels[selected_label]
    if mode is RobotConnectionMode.WIRED:
        wireless_host = "reachy-mini.local"
        st.caption("Uses the Reachy Mini Control daemon on localhost:8000.")
    else:
        wireless_host = st.text_input(
            "Wireless hostname or IP",
            value=(
                saved_researcher.reachy.wireless_host
                if saved_researcher
                else "reachy-mini.local"
            ),
            help="Do not include http:// or a path.",
        )

    with st.expander("Advanced connection settings"):
        port = int(
            st.number_input(
                "Daemon port",
                min_value=1,
                max_value=65535,
                value=saved_researcher.reachy.port if saved_researcher else 8000,
                step=1,
            )
        )
        timeout = float(
            st.number_input(
                "Connection timeout (seconds)",
                min_value=1.0,
                max_value=30.0,
                value=(
                    saved_researcher.reachy.timeout_seconds if saved_researcher else 5.0
                ),
                step=1.0,
            )
        )

    reachy_config: ReachyConnectionConfig | None
    try:
        reachy_config = ReachyConnectionConfig(
            mode=mode,
            wireless_host=wireless_host,
            port=port,
            timeout_seconds=timeout,
        )
    except ValueError as error:
        reachy_config = None
        st.error(str(error))

    reachy_ready = render_reachy_connection(reachy_config) if reachy_config else False
    if reachy_ready:
        if st.button("Play Reachy speaker test", width="stretch"):
            controller = connected_reachy()
            assert controller is not None
            try:
                with st.spinner("Playing test phrase through Reachy…"):
                    speaker = st.session_state["robot_speaker"]
                    speaker.speak(controller, "Reachy Mini connection test successful.")
            except (SpeechError, RecordingError, OSError) as error:
                st.error(f"Reachy connected, but the speaker test failed: {error}")
            else:
                st.session_state["reachy_audio_tested"] = True
                st.success("Reachy speaker test played successfully.")

    st.subheader("2. Camera, microphone, and recording")
    header, refresh_column = st.columns([4, 1])
    with header:
        st.caption("Select the defaults participants will see first.")
    with refresh_column:
        if st.button("Refresh", help="Scan again for connected recording devices"):
            close_live_camera_preview()
            cached_media_devices.clear()
            st.session_state.pop("device_test_signature", None)
            st.session_state.pop("device_test_path", None)
            st.rerun()

    with st.spinner("Discovering recording devices…"):
        catalog = cached_media_devices()
    camera = st.selectbox(
        "Default camera",
        options=list(catalog.cameras),
        format_func=lambda device: device.label,
        index=(
            default_index(catalog.cameras, saved_researcher.default_camera)
            if catalog.cameras and saved_researcher
            else (0 if catalog.cameras else None)
        ),
        placeholder="No camera detected",
    )
    microphone = st.selectbox(
        "Default microphone",
        options=list(catalog.microphones),
        format_func=lambda device: device.label,
        index=(
            default_index(catalog.microphones, saved_researcher.default_microphone)
            if catalog.microphones and saved_researcher
            else (0 if catalog.microphones else None)
        ),
        placeholder="No microphone detected",
    )
    aspect_ratio_options = list(VideoAspectRatio)
    saved_aspect_ratio = (
        saved_researcher.video_aspect_ratio
        if saved_researcher
        else VideoAspectRatio.WIDESCREEN
    )
    aspect_ratio = st.selectbox(
        "Recording aspect ratio",
        options=aspect_ratio_options,
        index=aspect_ratio_options.index(saved_aspect_ratio),
        format_func=lambda option: option.label,
        help="Fixed ratios preserve the full camera image and add padding when needed.",
    )

    st.markdown("**Live camera preview**")
    if camera is not None:
        render_live_camera_preview(camera, aspect_ratio)
    else:
        st.info("Connect a camera to start the live preview.")

    if catalog.warnings:
        with st.expander("Device setup messages", expanded=not (camera and microphone)):
            for warning in catalog.warnings:
                st.warning(warning)

    selected_signature = (
        device_signature(camera, microphone, aspect_ratio)
        if camera is not None and microphone is not None
        else None
    )
    test_ready = st.session_state.get("device_test_signature") == selected_signature
    if st.button(
        "Record 5-second camera and microphone test",
        width="stretch",
        disabled=selected_signature is None,
    ):
        assert camera is not None
        assert microphone is not None
        close_live_camera_preview()
        countdown = st.empty()

        def update_researcher_countdown(seconds: int) -> None:
            if seconds > 0:
                unit = "seconds" if seconds != 1 else "second"
                countdown.warning(f"● Recording — {seconds} {unit} remaining")
            else:
                countdown.info("Finishing test recording…")

        try:
            with st.spinner("Recording five seconds…"):
                result = record_device_test(
                    camera,
                    microphone,
                    duration_seconds=5.0,
                    countdown_callback=update_researcher_countdown,
                    aspect_ratio=aspect_ratio,
                )
        except (RecordingError, OSError) as error:
            countdown.empty()
            st.session_state.pop("device_test_signature", None)
            st.session_state.pop("device_test_path", None)
            st.error(f"Device test failed: {error}")
        else:
            st.session_state["device_test_signature"] = selected_signature
            st.session_state["device_test_path"] = str(result.path)
            st.session_state["researcher_notice"] = (
                "Test recording contains both video and audio. Review it below."
            )
            st.rerun()

    test_path_value = st.session_state.get("device_test_path")
    if test_ready and isinstance(test_path_value, str) and Path(test_path_value).is_file():
        st.video(test_path_value)
        st.caption("Play this clip and confirm that both picture and sound are correct.")
    elif selected_signature is not None:
        st.info("Record and review a test clip with the selected devices.")

    st.divider()
    researcher_ready = bool(
        reachy_ready
        and test_ready
        and reachy_config is not None
        and camera is not None
        and microphone is not None
    )
    if st.button(
        "Begin participant sessions",
        type="primary",
        width="stretch",
        disabled=not researcher_ready,
    ):
        assert reachy_config is not None
        assert camera is not None
        assert microphone is not None
        st.session_state["researcher_configuration"] = ResearcherConfiguration(
            reachy=reachy_config,
            cameras=catalog.cameras,
            microphones=catalog.microphones,
            default_camera=camera,
            default_microphone=microphone,
            video_aspect_ratio=aspect_ratio,
        )
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)

    if not researcher_ready:
        missing: list[str] = []
        if not reachy_ready:
            missing.append("Reachy connection")
        if not test_ready:
            missing.append("reviewed device test")
        st.caption("Required before continuing: " + ", ".join(missing) + ".")


def render_participant_start_page() -> None:
    researcher = st.session_state.get("researcher_configuration")
    if not isinstance(researcher, ResearcherConfiguration):
        navigate_to(PAGE_RESEARCHER)

    with st.sidebar:
        st.caption("Researcher controls")
        if st.button("Researcher settings", width="stretch"):
            navigate_to(PAGE_RESEARCHER)

    st.title("Participant setup")
    st.write("Please enter your participant ID and check the recording devices.")

    session_end_notice = st.session_state.pop("session_end_notice", None)
    if isinstance(session_end_notice, str):
        st.warning(session_end_notice)

    participant_input = st.text_input(
        "Participant ID",
        key="participant_id_input",
        placeholder="e.g. P001",
        max_chars=30,
    )
    participant_id: str | None = None
    if participant_input:
        try:
            participant_id = normalize_participant_id(participant_input)
        except ValueError as error:
            st.error(str(error))

    camera = researcher.default_camera
    microphone = researcher.default_microphone
    st.subheader("Recording devices")
    st.write(f"**Camera:** {camera.label}")
    st.write(f"**Microphone:** {microphone.label}")
    st.write(f"**Video format:** {researcher.video_aspect_ratio.label}")
    st.caption("These devices were configured by the researcher.")

    st.subheader("Camera preview and microphone test")
    render_live_camera_preview(camera, researcher.video_aspect_ratio)
    selected_signature = device_signature(
        camera,
        microphone,
        researcher.video_aspect_ratio,
    )
    test_ready = (
        st.session_state.get("participant_device_test_signature")
        == selected_signature
    )
    st.caption(
        "Record a short practice clip, move in front of the camera, and say a few "
        "words. This clip is temporary and is not saved with your responses."
    )
    if st.button(
        "Record 5-second preview and microphone test",
        width="stretch",
    ):
        close_live_camera_preview()
        countdown = st.empty()

        def update_participant_countdown(seconds: int) -> None:
            if seconds > 0:
                unit = "seconds" if seconds != 1 else "second"
                countdown.warning(f"● Recording — {seconds} {unit} remaining")
            else:
                countdown.info("Finishing practice clip…")

        try:
            with st.spinner("Recording five seconds…"):
                result = record_device_test(
                    camera,
                    microphone,
                    duration_seconds=5.0,
                    test_kind="participant",
                    countdown_callback=update_participant_countdown,
                    aspect_ratio=researcher.video_aspect_ratio,
                )
        except (RecordingError, OSError) as error:
            countdown.empty()
            st.session_state.pop("participant_device_test_signature", None)
            st.session_state.pop("participant_device_test_path", None)
            st.error(f"Preview and microphone test failed: {error}")
        else:
            st.session_state["participant_device_test_signature"] = selected_signature
            st.session_state["participant_device_test_path"] = str(result.path)
            st.rerun()

    test_path_value = st.session_state.get("participant_device_test_path")
    if test_ready and isinstance(test_path_value, str) and Path(test_path_value).is_file():
        st.success("Practice clip recorded. Play it to check the framing and sound.")
        st.video(test_path_value)
    else:
        st.info("The device test is optional and will not be included in the study data.")

    if st.button(
        "Start",
        type="primary",
        width="stretch",
        disabled=not participant_id,
    ):
        assert participant_id is not None
        close_live_camera_preview()
        participant = ParticipantConfiguration(
            participant_id=participant_id,
            camera=camera,
            microphone=microphone,
        )
        try:
            questions = load_questions(QUESTIONS_PATH)
            controller = connected_reachy()
            if controller is None:
                raise ReachyConnectionError(
                    "Reachy is no longer connected. Ask the researcher for help."
                )
            storage = SessionStorage.create(
                RECORDINGS_ROOT,
                researcher,
                participant,
                questions,
            )
        except (
            QuestionFormatError,
            ReachyConnectionError,
            OSError,
            ValueError,
        ) as error:
            st.error(f"The session could not start: {error}")
        else:
            st.session_state["participant_configuration"] = participant
            st.session_state["experiment_controller"] = ExperimentController(questions)
            st.session_state["session_storage"] = storage
            st.session_state["spoken_question_number"] = None
            queue_robot_response(
                emotion=WELCOME_EMOTION,
                message=WELCOME_MESSAGE,
                wake_up=True,
                status="Reachy is welcoming you…",
            )
            navigate_to(PAGE_WELCOME)


def show_participant_notice() -> None:
    notice = st.session_state.pop("participant_notice", None)
    if isinstance(notice, str) and notice:
        st.warning(notice)


def render_participant_welcome_page() -> None:
    experiment = st.session_state.get("experiment_controller")
    participant = st.session_state.get("participant_configuration")
    storage = st.session_state.get("session_storage")
    if not isinstance(experiment, ExperimentController) or not isinstance(
        participant, ParticipantConfiguration
    ) or not isinstance(storage, SessionStorage):
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)

    show_participant_notice()
    st.title("Welcome")
    st.info(WELCOME_MESSAGE)
    st.write(
        "When you are ready, select **Begin Questions**. Reachy will read each "
        "question before recording begins."
    )

    if robot_action_in_progress():
        render_robot_action_progress()
        return
    if start_pending_robot_response():
        render_robot_action_progress()
        return

    if st.button("Begin Questions", type="primary", width="stretch"):
        navigate_to(PAGE_EXPERIMENT)


def render_experiment_page() -> None:
    experiment = st.session_state.get("experiment_controller")
    participant = st.session_state.get("participant_configuration")
    researcher = st.session_state.get("researcher_configuration")
    storage = st.session_state.get("session_storage")
    if not isinstance(experiment, ExperimentController) or not isinstance(
        participant, ParticipantConfiguration
    ) or not isinstance(researcher, ResearcherConfiguration) or not isinstance(
        storage, SessionStorage
    ):
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)

    show_participant_notice()
    question = experiment.current_question
    st.caption(experiment.progress_label)
    st.progress((experiment.question_index + 1) / len(experiment.questions))
    render_question_text(question.text)

    if robot_action_in_progress():
        render_robot_action_progress()
        return
    if start_pending_robot_response():
        render_robot_action_progress()
        return

    if experiment.stage is ExperimentStage.QUESTION_READY:
        if st.session_state.get("spoken_question_number") != question.number:
            start_question_speech(question.number, question.text)
            if robot_action_in_progress():
                render_robot_action_progress()
                return

        left, right = st.columns(2)
        with left:
            if st.button("Repeat question", width="stretch"):
                start_question_speech(question.number, question.text, repeat=True)
                st.rerun()
        with right:
            if st.button("Begin response", type="primary", width="stretch"):
                try:
                    output_path = storage.recording_path(question.number)
                    recorder = FFmpegRecorder(
                        participant.camera,
                        participant.microphone,
                        output_path,
                        aspect_ratio=researcher.video_aspect_ratio,
                    )
                    recorder.start()
                except (RecordingError, OSError, FileExistsError) as error:
                    st.error(f"Recording could not start: {error}")
                else:
                    storage.mark_recording_started(question.number)
                    experiment.begin_response()
                    st.session_state["active_recorder"] = recorder
                    st.rerun()

    elif experiment.stage is ExperimentStage.RECORDING:
        st.error("● Recording in progress")
        st.write("Answer the question, then press **End Response**.")
        if st.button("End Response", type="primary", width="stretch"):
            recorder = st.session_state.get("active_recorder")
            if not isinstance(recorder, FFmpegRecorder):
                experiment.abort_response()
                st.session_state["participant_notice"] = (
                    "The recorder was lost. Please record this response again."
                )
                st.rerun()
            try:
                with st.spinner("Saving your response…"):
                    result = recorder.stop()
            except (RecordingError, OSError) as error:
                recorder.cancel()
                experiment.abort_response()
                st.session_state.pop("active_recorder", None)
                st.session_state["participant_notice"] = (
                    f"The response could not be saved: {error}. Please record it again."
                )
                st.rerun()
            else:
                storage.mark_recording_complete(question.number, result)
                final_question = experiment.finish_response(result.path)
                st.session_state.pop("active_recorder", None)
                next_question_is_final = bool(
                    not final_question
                    and experiment.question_index == len(experiment.questions) - 2
                )
                if final_question:
                    emotion = COMPLETION_EMOTION
                    acknowledgement = (
                        "Thank you for participating. The interaction is now complete."
                    )
                elif next_question_is_final:
                    emotion = FINAL_QUESTION_EMOTION
                    acknowledgement = (
                        "Thank you. The next question is the final question."
                    )
                else:
                    emotion = NEXT_QUESTION_EMOTION
                    acknowledgement = "Thank you. Let us continue to the next question."
                queue_robot_response(
                    emotion=emotion,
                    message=acknowledgement,
                    status="Reachy is responding…",
                )
                st.rerun()

    elif experiment.stage is ExperimentStage.AWAITING_CONTINUE:
        final_question = experiment.question_index == len(experiment.questions) - 1
        st.success("Your response has been saved.")
        button_label = "Finish" if final_question else "Next Question"
        if st.button(button_label, type="primary", width="stretch"):
            complete = experiment.continue_after_response()
            if complete:
                navigate_to(PAGE_COMPLETE)
            else:
                st.session_state["spoken_question_number"] = None
                navigate_to(PAGE_EXPERIMENT)


def render_complete_page() -> None:
    participant = st.session_state.get("participant_configuration")
    storage = st.session_state.get("session_storage")
    if not isinstance(participant, ParticipantConfiguration) or not isinstance(
        storage, SessionStorage
    ):
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)

    show_participant_notice()
    st.title("Thank you for participating")
    if robot_action_in_progress():
        render_robot_action_progress()
        return
    if start_pending_robot_response():
        render_robot_action_progress()
        return
    st.write("Your responses have been recorded. Please press **End session**.")
    if st.button("End session", type="primary", width="stretch"):
        storage.finalize()
        sleep_error: str | None = None
        controller = connected_reachy()
        if controller is None:
            sleep_error = "Reachy disconnected before it could go to sleep."
        else:
            try:
                with st.spinner("Reachy is going to sleep…"):
                    controller.goto_sleep()
            except Exception as error:
                sleep_error = f"Reachy could not go to sleep: {error}"
        reset_participant_state()
        if sleep_error is not None:
            st.session_state["session_end_notice"] = sleep_error
        navigate_to(PAGE_PARTICIPANT)


def render_app() -> None:
    initialize_state()
    page = st.session_state["page"]
    if page not in {PAGE_RESEARCHER, PAGE_PARTICIPANT}:
        close_live_camera_preview()
    if page == PAGE_RESEARCHER:
        render_researcher_page()
    elif page == PAGE_PARTICIPANT:
        render_participant_start_page()
    elif page == PAGE_WELCOME:
        render_participant_welcome_page()
    elif page == PAGE_EXPERIMENT:
        render_experiment_page()
    elif page == PAGE_COMPLETE:
        render_complete_page()
    else:
        navigate_to(PAGE_RESEARCHER)
    apply_pending_scroll_reset()


render_app()
