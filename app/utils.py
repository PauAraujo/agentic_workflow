import json

import streamlit as st

from typing import Any
from pathlib import Path

from app.config import STATE_DUMPS_DIR


def safe_dump(model: Any) -> dict:
    """
    Convert pydantic models or plain objects to dict for display.

    Args:
        model: A pydantic model, dict, or other object to convert

    Returns:
        dict: Dictionary representation of the model
    """
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    if isinstance(model, dict):
        return model
    return {"value": model}


def select_state_dump() -> Path | None:
    """
    Render a Streamlit selector for choosing a previous state dump.

    Displays available state dump files from the state dumps directory and
    returns the selected file path.

    Returns:
        Path or None: Path to the selected state dump JSON file, or None if no dumps available
    """
    dumps = sorted(STATE_DUMPS_DIR.glob("run_*.json"))
    if not dumps:
        st.info("No state dumps found yet. Run a query to create one.")
        return None

    labels = [f"{p.name}" for p in dumps]
    choice = st.selectbox("Load a previous run", labels)
    if not choice:
        return None
    return dumps[labels.index(choice)]


def render_state_dump(path: Path) -> None:
    """
    Display a state dump file as formatted JSON in Streamlit.

    Args:
        path: Path to the state dump JSON file to display
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    st.subheader(f"State dump: {path.name}")
    st.json(data)
