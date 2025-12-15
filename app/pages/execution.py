import streamlit as st

from app.config import (
    CUSTOM_CSS,
    PAGE_TITLE,
    LAYOUT,
    EXECUTOR_GRAPH_PATH,
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
    Execution results page

    Displays the query execution results including metrics, data, and errors.
    """
    st.set_page_config(
        page_title=f"{PAGE_TITLE} - Execution",
        layout=LAYOUT,
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    initialize_session_state()

    st.header("Execution Results")

    if not has_workflow_results():
        st.info("No execution result yet. Run a query first from the Home page.")
        return

    state = get_last_workflow_state()
    query_result = state.get("query_result")

    if not query_result:
        st.info("No execution result yet. Run a query first.")
        return

    result_dict = safe_dump(query_result)

    col_img, col_metrics = st.columns([1, 1])
    with col_img:
        render_subgraph(EXECUTOR_GRAPH_PATH)
    with col_metrics:
        cols = st.columns(3)
        cols[0].metric("Rows", result_dict.get("row_count", 0))
        cols[1].metric("Time (ms)", round(result_dict.get("execution_time_ms") or 0, 2))
        cols[2].metric("Success", str(result_dict.get("success")))

    if result_dict.get("error_message"):
        st.error(result_dict.get("error_message"))

    rows = result_dict.get("rows") or []
    if rows:
        st.dataframe(rows, use_container_width=True)
    else:
        st.info("No rows returned.")

    run_id = state.get("run_id")
    if run_id is not None:
        st.caption(f"Run ID: {run_id}")


if __name__ == "__main__":
    main()
