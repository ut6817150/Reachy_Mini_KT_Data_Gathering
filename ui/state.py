"""Streamlit session state and navigation helpers."""

import streamlit as st
import streamlit.components.v1 as components

from services.experiment_controller import ExperimentController
from services.reachy_controller import ReachyController
from services.recorder import FFmpegRecorder
from services.speech import RobotSpeaker
from services.storage import SessionStorage
from ui.constants import PAGE_PARTICIPANT, PAGE_RESEARCHER


PARTICIPANT_STATE_KEYS = (
    "experiment_controller",
    "session_storage",
    "active_recorder",
    "spoken_question_number",
    "participant_notice",
    "participant_id_input",
    "participant_device_tested",
    "participant_device_test_path",
    "pending_robot_response",
    "robot_action",
)


def initialize_state() -> None:
    st.session_state.setdefault("page", PAGE_RESEARCHER)
    st.session_state.setdefault("robot_speaker", RobotSpeaker())


def navigate_to(page: str) -> None:
    st.session_state["page"] = page
    st.session_state["scroll_to_top"] = True
    st.rerun()


def apply_scroll_reset() -> None:
    if st.session_state.pop("scroll_to_top", False) is not True:
        return
    components.html(
        """
        <script>
            const parentWindow = window.parent;
            const scrollToTop = () => {
                parentWindow.scrollTo(0, 0);
                parentWindow.document
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


def connected_reachy() -> ReachyController | None:
    controller = st.session_state.get("reachy_controller")
    if isinstance(controller, ReachyController) and controller.is_connected:
        return controller
    return None


def disconnect_reachy() -> None:
    controller = st.session_state.pop("reachy_controller", None)
    st.session_state.pop("reachy_connection_signature", None)
    st.session_state.pop("reachy_connection_label", None)
    if isinstance(controller, ReachyController):
        controller.disconnect()


def reset_participant_state() -> None:
    recorder = st.session_state.get("active_recorder")
    if isinstance(recorder, FFmpegRecorder):
        recorder.cancel()
    for key in PARTICIPANT_STATE_KEYS:
        st.session_state.pop(key, None)


def active_session() -> tuple[ExperimentController, SessionStorage]:
    experiment = st.session_state.get("experiment_controller")
    storage = st.session_state.get("session_storage")
    if not isinstance(experiment, ExperimentController) or not isinstance(
        storage, SessionStorage
    ):
        reset_participant_state()
        navigate_to(PAGE_PARTICIPANT)
    return experiment, storage


def show_participant_notice() -> None:
    notice = st.session_state.pop("participant_notice", None)
    if isinstance(notice, str) and notice:
        st.warning(notice)
