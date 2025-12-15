import streamlit as st

from app.config import (
    CUSTOM_CSS,
    PAGE_TITLE,
    LAYOUT,
    INTERPRETER_GRAPH_PATH,
    PRIMARY_BLUE,
)
from app.state import (
    initialize_session_state,
    get_last_workflow_state,
    has_workflow_results,
)
from app.components import render_intent_card, render_subgraph


def main():
    """
    Interpreter page

    Displays the intent card and interpreter subgraph from the workflow execution.
    """
    st.set_page_config(
        page_title=f"{PAGE_TITLE} - Interpreter",
        layout=LAYOUT,
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    initialize_session_state()

    st.header("Interpreter Stage")

    if not has_workflow_results():
        st.info("No intent card available. Run a query first from the Home page.")
        return

    state = get_last_workflow_state()
    intent_card = state.get("intent_card")

    col_img, col_intent = st.columns([1, 1])
    with col_img:
        render_subgraph(INTERPRETER_GRAPH_PATH)
    with col_intent:
        render_intent_card(intent_card, accent=PRIMARY_BLUE)


if __name__ == "__main__":
    main()
