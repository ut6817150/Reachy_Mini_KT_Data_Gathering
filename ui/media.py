"""Five-second camera and microphone test UI."""

from pathlib import Path

import streamlit as st

from services.recorder import RecordingError, record_device_test


def render_device_test(kind: str) -> bool:
    participant_test = kind == "participant"
    tested_key = f"{kind}_device_tested"
    path_key = f"{kind}_device_test_path"
    button_label = (
        "Record 5-second practice clip"
        if participant_test
        else "Record 5-second camera and microphone test"
    )

    if st.button(button_label, width="stretch"):
        countdown = st.empty()

        def update_countdown(seconds: int) -> None:
            if seconds:
                unit = "seconds" if seconds != 1 else "second"
                countdown.warning(f"● Recording — {seconds} {unit} remaining")
            else:
                countdown.info("Finishing practice clip…")

        try:
            with st.spinner("Recording five seconds…"):
                path = record_device_test(
                    test_kind=kind,
                    countdown_callback=update_countdown,
                )
        except (RecordingError, OSError) as error:
            countdown.empty()
            st.session_state.pop(tested_key, None)
            st.session_state.pop(path_key, None)
            st.error(f"Device test failed: {error}")
        else:
            st.session_state[tested_key] = True
            st.session_state[path_key] = str(path)
            st.rerun()

    tested = st.session_state.get(tested_key) is True
    path = st.session_state.get(path_key)
    if tested and isinstance(path, str) and Path(path).is_file():
        if participant_test:
            st.success(
                "Practice clip recorded. Play it to check the framing and sound."
            )
        st.video(path)
        st.caption(
            "Play this clip and confirm that both picture and sound are correct."
        )
    elif participant_test:
        st.info(
            "The device test is optional and will not be included in the study data."
        )
    else:
        st.info("Record and review a test clip with the built-in MacBook devices.")
    return tested
