"""Welcome, question loop, and completion pages."""

import html

import streamlit as st

from services.experiment_controller import AWAITING_CONTINUE, QUESTION_READY, RECORDING
from services.recorder import FFmpegRecorder, RecordingError
from services.speech import WELCOME_MESSAGE, speech_file
from ui.constants import (
    COMPLETION_EMOTION,
    FINAL_QUESTION_EMOTION,
    NEXT_QUESTION_EMOTION,
    PAGE_COMPLETE,
    PAGE_EXPERIMENT,
    PAGE_PARTICIPANT,
)
from ui.robot import (
    queue_robot_response,
    render_robot_progress,
    robot_action_in_progress,
    start_question_speech,
    wait_for_robot,
)
from ui.state import (
    active_session,
    connected_reachy,
    navigate_to,
    reset_participant_state,
    show_participant_notice,
)


def render_question_text(text: str) -> None:
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
        <div class="reachy-question">{html.escape(text)}</div>
        """,
        unsafe_allow_html=True,
    )


def acknowledgement(
    question_index: int, question_count: int
) -> tuple[str, str]:
    if question_index == question_count - 1:
        return COMPLETION_EMOTION, "completion.wav"
    if question_index == question_count - 2:
        return FINAL_QUESTION_EMOTION, "final_question.wav"
    return NEXT_QUESTION_EMOTION, "next_question.wav"


def render_welcome_page() -> None:
    active_session()
    show_participant_notice()
    st.title("Welcome")
    st.info(WELCOME_MESSAGE)
    st.write(
        "When you are ready, select **Begin Questions**. Reachy will read each "
        "question before recording begins."
    )
    if wait_for_robot():
        return
    if st.button("Begin Questions", type="primary", width="stretch"):
        navigate_to(PAGE_EXPERIMENT)


def render_experiment_page() -> None:
    experiment, storage = active_session()
    show_participant_notice()
    question = experiment.current_question
    question_number = experiment.question_number
    st.caption(f"Question {question_number} of {len(experiment.questions)}")
    st.progress(question_number / len(experiment.questions))
    render_question_text(question)

    if wait_for_robot():
        return

    if experiment.stage == QUESTION_READY:
        if st.session_state.get("spoken_question_number") != question_number:
            start_question_speech(question_number)
            if robot_action_in_progress():
                render_robot_progress()
                return

        left, right = st.columns(2)
        with left:
            if st.button("Repeat question", width="stretch"):
                start_question_speech(question_number, repeat=True)
                st.rerun()
        with right:
            if st.button("Begin response", type="primary", width="stretch"):
                try:
                    recorder = FFmpegRecorder(storage.recording_path(question_number))
                    recorder.start()
                except (RecordingError, OSError, FileExistsError) as error:
                    st.error(f"Recording could not start: {error}")
                else:
                    storage.mark_recording_started(question_number)
                    experiment.begin_response()
                    st.session_state["active_recorder"] = recorder
                    st.rerun()

    elif experiment.stage == RECORDING:
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
                    recording_path, duration = recorder.stop()
            except (RecordingError, OSError) as error:
                recorder.cancel()
                experiment.abort_response()
                st.session_state.pop("active_recorder", None)
                st.session_state["participant_notice"] = (
                    f"The response could not be saved: {error}. Please record it again."
                )
                st.rerun()
            else:
                storage.mark_recording_complete(
                    question_number, recording_path, duration
                )
                experiment.finish_response()
                st.session_state.pop("active_recorder", None)
                emotion, audio_filename = acknowledgement(
                    experiment.question_index, len(experiment.questions)
                )
                queue_robot_response(
                    emotion=emotion,
                    audio_path=speech_file(audio_filename),
                )
                st.rerun()

    elif experiment.stage == AWAITING_CONTINUE:
        final_question = experiment.question_index == len(experiment.questions) - 1
        st.success("Your response has been saved.")
        button_label = "Finish" if final_question else "Next Question"
        if st.button(button_label, type="primary", width="stretch"):
            if experiment.continue_after_response():
                navigate_to(PAGE_COMPLETE)
            else:
                st.session_state["spoken_question_number"] = None
                navigate_to(PAGE_EXPERIMENT)


def render_complete_page() -> None:
    _, storage = active_session()
    show_participant_notice()
    st.title("Thank you for participating")
    if wait_for_robot():
        return
    st.write("Your responses have been recorded. Please press **End session**.")
    if st.button("End session", type="primary", width="stretch"):
        storage.finalize()
        sleep_error = None
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
        if sleep_error:
            st.session_state["session_end_notice"] = sleep_error
        navigate_to(PAGE_PARTICIPANT)
