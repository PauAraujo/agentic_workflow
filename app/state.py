import streamlit as st

from typing import Any

from sql_query_assistant import Settings
from sql_query_assistant.utils import load_table_cards


def initialize_session_state() -> None:
    """
    Initialize all session state keys with default values.

    Sets up last_state (default None) if not present.
    """
    if "last_state" not in st.session_state:
        st.session_state["last_state"] = None
    if "workflow_steps" not in st.session_state:
        st.session_state["workflow_steps"] = None


def load_metadata(settings: Settings) -> None:
    """
    Load table cards and cache them in session state.

    Loads the data only once on first call, subsequent calls use cached values.

    Args:
        settings: Application settings containing paths to metadata files
    """
    if "table_cards" not in st.session_state or st.session_state.get("table_cards") is None:
        st.session_state["table_cards"] = load_table_cards(settings=settings, base_path=None)


def get_settings() -> Settings:
    """
    Get or create the Settings object from session state.

    Creates a new Settings instance on first call and caches it in session state.

    Returns:
        Settings: Application settings object
    """
    if "settings" not in st.session_state:
        st.session_state["settings"] = Settings()
    return st.session_state["settings"]


def get_last_workflow_state() -> dict[str, Any] | None:
    """
    Get the last workflow execution state from session state.

    Returns:
        dict or None: Workflow state dictionary containing results, or None if no workflow has been run
    """
    return st.session_state.get("last_state")


def set_last_workflow_state(state: dict[str, Any]) -> None:
    """
    Store the workflow execution state in session state.

    Args:
        state: Workflow state dictionary containing execution results
    """
    st.session_state["last_state"] = state


def get_table_cards() -> list:
    """
    Get loaded table cards from session state.

    Returns:
        list: List of TableCard objects, or empty list if not loaded
    """
    return st.session_state.get("table_cards", [])


def has_workflow_results() -> bool:
    """
    Check if workflow results are available in session state.

    Returns:
        bool: True if last_state exists and is not None
    """
    return st.session_state.get("last_state") is not None
