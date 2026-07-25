"""Non-blocking Reachy speech and emotion UI."""

from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import Callable

import streamlit as st

from services.reachy_controller import ReachyConnectionError
from services.speech import RobotSpeaker, speech_file
from ui.state import connected_reachy


@st.cache_resource
def robot_action_executor() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(max_workers=1, thread_name_prefix="reachy-action")


def queue_robot_response(
    *,
    emotion: str,
    audio_path: Path,
    wake_up: bool = False,
    status: str = "Reachy is responding…",
) -> None:
    """Queue work to start after the destination page is visible."""

    st.session_state["pending_robot_response"] = {
        "emotion": emotion,
        "audio_path": audio_path,
        "wake_up": wake_up,
        "status": status,
    }


def robot_action_in_progress() -> bool:
    action = st.session_state.get("robot_action")
    return isinstance(action, dict) and isinstance(action.get("future"), Future)


def start_robot_action(
    action: Callable[[], object],
    *,
    status: str,
    error_context: str,
    question_number: int | None = None,
    skippable: bool = False,
) -> None:
    if robot_action_in_progress():
        return
    st.session_state["robot_action"] = {
        "future": robot_action_executor().submit(action),
        "status": status,
        "error_context": error_context,
        "question_number": question_number,
        "skippable": skippable,
        "skipped": False,
    }


def start_pending_robot_response() -> None:
    pending = st.session_state.pop("pending_robot_response", None)
    if not isinstance(pending, dict):
        return

    controller = connected_reachy()
    if controller is None:
        st.session_state["participant_notice"] = (
            "Reachy is no longer connected. Ask the researcher for help."
        )
        return
    speaker = st.session_state["robot_speaker"]

    def perform_response() -> None:
        if pending.get("wake_up") is True:
            controller.wake_up()
        speaker.play_during(
            controller,
            pending["audio_path"],
            lambda: controller.play_emotion(pending["emotion"]),
        )

    start_robot_action(
        perform_response,
        status=str(pending.get("status", "Reachy is responding…")),
        error_context="Reachy could not complete its response",
    )


def start_question_speech(question_number: int, *, repeat: bool = False) -> None:
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
        lambda: speaker.play(
            controller, speech_file(f"question_{question_number:02d}.wav")
        ),
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


@st.fragment(run_every=0.25)
def render_robot_progress() -> None:
    action = st.session_state.get("robot_action")
    if not isinstance(action, dict):
        st.rerun()
    future = action.get("future")
    if not isinstance(future, Future):
        st.rerun()

    if not future.done():
        st.info(f"🔊 {action.get('status', 'Reachy is responding…')}")
        if action.get("skippable") is True and st.button(
            "Skip Voiceover", width="stretch"
        ):
            controller = connected_reachy()
            speaker = st.session_state.get("robot_speaker")
            if controller is None or not isinstance(speaker, RobotSpeaker):
                st.warning(
                    "Voiceover could not be stopped because Reachy disconnected."
                )
            else:
                try:
                    stopped = speaker.stop(controller)
                except (ReachyConnectionError, OSError) as error:
                    st.warning(f"Voiceover could not be stopped: {error}")
                else:
                    cancelled = future.cancel() if not stopped else False
                    if stopped or cancelled:
                        action["skipped"] = True
                        action["status"] = "Voiceover skipped."
                    else:
                        st.warning("Voiceover is still starting. Please try again.")
        return

    error: Exception | None = None
    if action.get("skipped") is not True:
        try:
            future.result()
        except Exception as caught_error:
            error = caught_error

    question_number = action.get("question_number")
    error_context = str(action.get("error_context", "Reachy action failed"))
    st.session_state.pop("robot_action", None)
    if isinstance(question_number, int):
        st.session_state["spoken_question_number"] = question_number
    if error is not None:
        suffix = " The question is still shown on screen." if question_number else ""
        st.session_state["participant_notice"] = f"{error_context}: {error}.{suffix}"
    st.rerun()


def wait_for_robot() -> bool:
    if not robot_action_in_progress():
        start_pending_robot_response()
    if robot_action_in_progress():
        render_robot_progress()
        return True
    return False
