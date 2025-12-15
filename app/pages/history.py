import streamlit as st

from app.config import (
    CUSTOM_CSS,
    PAGE_TITLE,
    LAYOUT,
    MAIN_GRAPH_PATH,
)
from app.state import initialize_session_state
from app.components import render_subgraph
from app.utils import select_state_dump, render_state_dump


def main():
    """
    History page

    Displays the main workflow graph and allows browsing previous query runs.
    """
    st.set_page_config(
        page_title=f"{PAGE_TITLE} - History",
        layout=LAYOUT,
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    initialize_session_state()

    st.header("Previous Runs")

    col_img, col_content = st.columns([1, 1])
    with col_img:
        render_subgraph(MAIN_GRAPH_PATH, caption="Main graph")
    with col_content:
        dump_path = select_state_dump()
        if dump_path:
            render_state_dump(dump_path)


if __name__ == "__main__":
    main()
