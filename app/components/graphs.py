from pathlib import Path

import streamlit as st

from app.config import HEADER_IMG


def render_header_graph() -> None:
    """
    Render the main header graph image.

    Displays the header graph if it exists, otherwise shows an informational message.
    """
    if HEADER_IMG.exists():
        st.image(str(HEADER_IMG))
    else:
        st.info(f"Header image not found at {HEADER_IMG}.")


def render_subgraph(path: Path, caption: str | None = None) -> None:
    """
    Render a workflow subgraph image.

    Args:
        path: Path to the subgraph image file
        caption: Optional caption text to display with the image
    """
    if path.exists():
        if caption:
            st.image(str(path), caption=caption)
        else:
            st.image(str(path))
    else:
        st.info(f"Subgraph not found at {path}. Generate via --render-graph.")
