import sys

import streamlit as st

from typing import Any
from pathlib import Path

from main import run_workflow

sys.path.insert(0, str(Path(__file__).parent))  # ensure app/ is importable

from app.config import (
    MAIN_GRAPH_PATH,
    INTERPRETER_GRAPH_PATH,
    SQL_DRAFTER_GRAPH_PATH,
    EXECUTOR_GRAPH_PATH,
    PRIMARY_BLUE,
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


def _render_generated_sql(state: dict[str, Any]):
    """Render the generated SQL"""
    sql_draft = state.get("sql_draft")
    if not sql_draft:
        return

    draft_dict = safe_dump(sql_draft)
    sql = draft_dict.get("sql")
    if sql:
        st.subheader("Generated SQL")
        st.code(sql, language="sql")


def _render_execution_results(state: dict[str, Any]):
    """Render query execution results"""
    query_result = state.get("query_result")
    if not query_result:
        st.info("No execution result available.")
        return

    result_dict = safe_dump(query_result)

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


def _render_interpreter_details(state: dict[str, Any]):
    """Render interpreter stage details"""
    intent_card = state.get("intent_card")
    if not intent_card:
        st.info("No intent card available.")
        return

    col_img, col_intent = st.columns([1, 1])
    with col_img:
        render_subgraph(INTERPRETER_GRAPH_PATH)
    with col_intent:
        render_intent_card(intent_card, accent=PRIMARY_BLUE)


def _render_workflow_graphs():
    """Render workflow subgraphs"""
    col1, col2, col3 = st.columns(3)
    with col1:
        render_subgraph(INTERPRETER_GRAPH_PATH, caption="Interpreter")
    with col2:
        render_subgraph(SQL_DRAFTER_GRAPH_PATH, caption="SQL Drafter")
    with col3:
        render_subgraph(EXECUTOR_GRAPH_PATH, caption="Executor")


def _render_history():
    """Render previous runs section"""
    col_img, col_content = st.columns([1, 1])
    with col_img:
        render_subgraph(MAIN_GRAPH_PATH, caption="Main graph")
    with col_content:
        dump_path = select_state_dump()
        if dump_path:
            render_state_dump(dump_path)


def main():
    """Main application entry point."""
    initialize_session_state()

    st.set_page_config(page_title=PAGE_TITLE, layout=LAYOUT)
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    settings = get_settings()
    load_metadata(settings)
    table_cards = get_table_cards()
    assumption_catalog = get_assumption_catalog()

    render_header_graph()

    # Query input section
    st.markdown("---")
    query = st.text_input("Natural language query", placeholder="Show me all patients")
    col_opts, col_btn = st.columns([3, 1])
    with col_opts:
        enable_persistence = st.checkbox("Persist outputs", value=True)
    with col_btn:
        run_btn = st.button("Run", type="primary", use_container_width=True)

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
                    st.rerun()
                except Exception as exc:  # pragma: no cover
                    st.error(f"Workflow failed: {exc}")

    # Results section
    state = get_last_workflow_state()
    if state:
        st.markdown("---")
        _render_generated_sql(state)
        _render_execution_results(state)

        # Details tabs
        st.markdown("---")
        tab_interpreter, tab_graphs, tab_context, tab_history = st.tabs(
            ["Interpreter", "Workflow Graphs", "Input Context", "History"]
        )

        with tab_interpreter:
            _render_interpreter_details(state)

        with tab_graphs:
            _render_workflow_graphs()

        with tab_context:
            col_tables, col_assumptions = st.columns([1, 1])
            with col_tables:
                st.caption("Table cards")
                render_table_cards(table_cards, accent=PRIMARY_BLUE)
            with col_assumptions:
                st.caption("Assumptions catalog")
                render_assumptions_catalog(assumption_catalog, accent=PRIMARY_BLUE)

        with tab_history:
            _render_history()
    else:
        # Show input context when no results yet
        st.markdown("---")
        st.markdown("#### Input context")
        col_tables, col_assumptions = st.columns([1, 1])
        with col_tables:
            st.caption("Table cards")
            render_table_cards(table_cards, accent=PRIMARY_BLUE)
        with col_assumptions:
            st.caption("Assumptions catalog")
            render_assumptions_catalog(assumption_catalog, accent=PRIMARY_BLUE)


if __name__ == "__main__":
    main()
