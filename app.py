import sys

import streamlit as st

from typing import Any
from pathlib import Path

from main import run_workflow

sys.path.insert(0, str(Path(__file__).parent)) # ensure app/ is importable

from app.config import (
    MAIN_GRAPH_PATH,
    INTERPRETER_GRAPH_PATH,
    SQL_DRAFTER_GRAPH_PATH,
    EXECUTOR_GRAPH_PATH,
    PRIMARY_BLUE,
    MAX_STEP,
    PAGE_TITLE,
    LAYOUT,
    CUSTOM_CSS,
)
from app.state import (
    initialize_session_state,
    load_metadata,
    get_settings,
    get_last_workflow_state,
    set_last_workflow_state,
    has_workflow_results,
    get_table_cards,
    get_assumption_catalog,
)
from app.utils import safe_dump, select_state_dump, render_state_dump
from app.components import (
    render_intent_card,
    render_table_cards,
    render_assumptions_catalog,
    render_header_graph,
    render_subgraph,
)


def _render_interpreter_section(state: dict[str, Any]):
    """
    Render the interpreter stage section with intent card and subgraph.

    Args:
        state: Workflow state dictionary containing intent_card
    """
    intent_card = state.get("intent_card")
    if not intent_card:
        st.info("No intent card available. Run a query first.")
        return

    st.subheader("Interpreter stage")
    col_img, col_intent = st.columns([1, 1])
    with col_img:
        render_subgraph(INTERPRETER_GRAPH_PATH)
    with col_intent:
        render_intent_card(intent_card, accent=PRIMARY_BLUE)


def _render_sql_section(state: dict[str, Any]):
    """
    Render the SQL draft section with generated SQL and subgraph.

    Args:
        state: Workflow state dictionary containing sql_draft
    """
    sql_draft = state.get("sql_draft")
    if not sql_draft:
        st.info("No SQL draft yet. Run a query first.")
        return

    draft_dict = safe_dump(sql_draft)
    oracle_sql = draft_dict.get("sql")
    st.subheader("Draft SQL")
    col_img, col_sql = st.columns([1, 1])
    with col_img:
        render_subgraph(SQL_DRAFTER_GRAPH_PATH)
    with col_sql:
        st.code(oracle_sql or "", language="sql")



def _render_execution_section(state: dict[str, Any]):
    """
    Render the execution results section with metrics and data.

    Args:
        state: Workflow state dictionary containing query_result
    """
    query_result = state.get("query_result")
    if not query_result:
        st.info("No execution result yet. Run a query first.")
        return

    result_dict = safe_dump(query_result)
    st.subheader("Execution summary")
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


def _render_previous_runs_section():
    """
    Render the previous runs section with main graph and state dump selector.
    """
    col_img, col_content = st.columns([1, 1])
    with col_img:
        render_subgraph(MAIN_GRAPH_PATH, caption="Main graph")
    with col_content:
        dump_path = select_state_dump()
        if dump_path:
            render_state_dump(dump_path)


def _nav_controls():
    """
    Render wizard navigation controls (Back/Next buttons).

    Manages wizard step state and enables/disables buttons based on
    current step and workflow completion status.
    """
    step = st.session_state.get("wizard_step", 0)
    col_back, col_next = st.columns(2)
    if col_back.button("Back", key=f"back_{step}", disabled=step <= 0):
        st.session_state["wizard_step"] = max(step - 1, 0)
        st.rerun()

    disable_next = step >= MAX_STEP or (not has_workflow_results() and step < MAX_STEP)
    if col_next.button("Next", key=f"next_{step}", disabled=disable_next):
        st.session_state["wizard_step"] = min(step + 1, MAX_STEP)
        st.rerun()


def main():
    """
    Main application entry point

    Sets up the Streamlit page configuration, initializes state, and renders
    the appropriate wizard step based on user navigation.
    """
    initialize_session_state()

    st.set_page_config(page_title=PAGE_TITLE, layout=LAYOUT)
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    settings = get_settings()
    load_metadata(settings)
    table_cards = get_table_cards()
    assumption_catalog = get_assumption_catalog()

    render_header_graph()

    step = st.session_state["wizard_step"]

    # Run a query
    if step == 0:
        st.markdown("---")
        st.header("Run a query")

        query = st.text_input("Natural language query", placeholder="Show me all patients")
        enable_persistence = st.checkbox("Persist outputs (CSV + state dump)", value=True)
        run_btn = st.button("Run", type="primary")

        st.markdown("#### Input context")
        col_tables, col_assumptions = st.columns([1, 1])
        with col_tables:
            st.caption("Table cards")
            render_table_cards(table_cards, accent=PRIMARY_BLUE)
        with col_assumptions:
            st.caption("Assumptions catalog")
            render_assumptions_catalog(assumption_catalog, accent=PRIMARY_BLUE)

        if run_btn:
            if not query.strip():
                st.warning("Please enter a query.")
            else:
                with st.spinner("Running workflow..."):
                    try:
                        state = run_workflow(
                            user_query=query.strip(),
                            settings=settings,
                            table_cards_path=None,
                            assumptions_path=None,
                            enable_persistence=enable_persistence,
                        )
                        set_last_workflow_state(state)
                        st.session_state["wizard_step"] = 1
                        st.rerun()
                    except Exception as exc:  # pragma: no cover - UI guard
                        st.error(f"Workflow failed: {exc}")
    # Interpreter stage
    if step == 1:
        st.markdown("---")
        _render_interpreter_section(get_last_workflow_state() or {})
        _nav_controls()

    # SQL draft
    if step == 2:
        st.markdown("---")
        _render_sql_section(get_last_workflow_state() or {})
        _nav_controls()

    # Execution summary
    if step == 3:
        st.markdown("---")
        _render_execution_section(get_last_workflow_state() or {})
        _nav_controls()

    # Show previous runs
    if step == 4:
        st.markdown("---")
        st.header("Previous runs")
        _render_previous_runs_section()
        _nav_controls()


if __name__ == "__main__":
    main()
