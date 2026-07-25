"""Streamlit entry point for the Reachy Mini participant study."""

import streamlit as st


st.set_page_config(
    page_title="Reachy Mini Participant Study",
    page_icon="🤖",
    layout="centered",
    initial_sidebar_state="collapsed",
)


from ui.constants import (  # noqa: E402
    PAGE_COMPLETE,
    PAGE_EXPERIMENT,
    PAGE_PARTICIPANT,
    PAGE_RESEARCHER,
    PAGE_WELCOME,
)
from ui.setup_pages import render_participant_page, render_researcher_page  # noqa: E402
from ui.state import (  # noqa: E402
    apply_scroll_reset,
    initialize_state,
    navigate_to,
)
from ui.study_pages import (  # noqa: E402
    render_complete_page,
    render_experiment_page,
    render_welcome_page,
)


PAGES = {
    PAGE_RESEARCHER: render_researcher_page,
    PAGE_PARTICIPANT: render_participant_page,
    PAGE_WELCOME: render_welcome_page,
    PAGE_EXPERIMENT: render_experiment_page,
    PAGE_COMPLETE: render_complete_page,
}


def render_app() -> None:
    initialize_state()
    page = st.session_state["page"]
    renderer = PAGES.get(page)
    if renderer is None:
        navigate_to(PAGE_RESEARCHER)
    renderer()
    apply_scroll_reset()


render_app()
