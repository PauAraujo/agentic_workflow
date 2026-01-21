import streamlit as st

from app.config import (
    CUSTOM_CSS,
    PAGE_TITLE,
    LAYOUT,
    FLOW_DIGRAM_IMG,
)
from app.state import (
    initialize_session_state,
    get_last_workflow_state,
    has_workflow_results,
)
from app.components import render_subgraph
from app.utils import safe_dump


def main():
    """
    SQL Draft Page

    Displays the generated SQL draft and SQL drafter subgraph from the workflow execution.
    """
    st.set_page_config(
        page_title=f"{PAGE_TITLE} - SQL Draft",
        layout=LAYOUT,
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    initialize_session_state()

    st.header("SQL Draft")

    if not has_workflow_results():
        st.info("No SQL draft yet. Run a query first from the Home page.")
        return

    state = get_last_workflow_state()
    sql_draft = state.get("sql_draft")

    draft_dict = safe_dump(sql_draft)
    oracle_sql = draft_dict.get("sql")

    col_img, col_sql = st.columns([1, 1])
    with col_img:
        render_subgraph(FLOW_DIGRAM_IMG)
    with col_sql:
        st.code(oracle_sql or "", language="sql")


if __name__ == "__main__":
    main()
