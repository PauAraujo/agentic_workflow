import streamlit as st

from typing import Any
from dotenv import load_dotenv

from app.config import (
    COMPACT_FLOW_DIGRAM_IMG,
    FLOW_DIGRAM_IMG,
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
)
from app.utils import safe_dump, select_state_dump, render_state_dump
from app.components import (
    render_table_cards,
    render_header_graph,
    render_subgraph,
)

from sql_query_assistant import __version__
from sql_query_assistant.workflow import WorkflowRunner, NodeEvent

load_dotenv(override=True)


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


def _render_workflow_graphs():
    """Render workflow graph"""
    render_subgraph(FLOW_DIGRAM_IMG, caption="Workflow")


def _render_history():
    """Render previous runs section"""
    col_img, col_content = st.columns([1, 1])
    with col_img:
        render_subgraph(COMPACT_FLOW_DIGRAM_IMG, caption="Main graph")
    with col_content:
        dump_path = select_state_dump()
        if dump_path:
            render_state_dump(dump_path)


def _render_footer():
    """Render application footer with version and copyright."""
    footer_html = f"""
    <div class="app-footer">
        <span>v{__version__}</span> |
        <span>EMA Copyright 2025</span>
    </div>
    """
    st.markdown(footer_html, unsafe_allow_html=True)


def main():
    """Main application entry point."""
    initialize_session_state()

    st.set_page_config(page_title=PAGE_TITLE, layout=LAYOUT)
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    settings = get_settings()
    load_metadata(settings)
    table_cards = get_table_cards()

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
        st.session_state["workflow_steps"] = None  # Clear previous steps
        if not query.strip():
            st.warning("Please enter a query.")
        else:
            try:
                # Define workflow steps for display
                all_steps = [
                    ("table_card_retriever", "Retrieving relevant tables"),
                    ("table_selector", "Selecting tables for query"),
                    ("sql_drafter", "Generating SQL query"),
                    ("sql_validator", "Validating SQL syntax"),
                    ("sql_executor", "Executing SQL query"),
                    ("persistence", "Saving results"),
                ]

                with st.status("Starting workflow...", expanded=True) as status:
                    completed_nodes: set[str] = set()
                    accumulated_state: dict[str, Any] = {"user_query": query.strip()}
                    steps_placeholder = st.empty()

                    def handle_progress(event: NodeEvent):
                        """Update UI when a workflow node completes."""
                        completed_nodes.add(event.node_name)

                        if isinstance(event.state_update, dict):
                            accumulated_state.update(event.state_update)

                        status.update(label=f"{event.description}...", state="running")

                        # Build the steps display as markdown
                        steps_md = []
                        for step_node, step_desc in all_steps:
                            if step_node in completed_nodes:
                                detail = ""
                                if (
                                    step_node == "table_selector"
                                    and accumulated_state.get(
                                        "table_cards_with_selection"
                                    )
                                ):
                                    detail = f" ({len(accumulated_state['table_cards_with_selection'])} tables)"
                                elif (
                                    step_node == "sql_validator"
                                    and accumulated_state.get("validation_result")
                                ):
                                    vr = accumulated_state["validation_result"]
                                    detail = " ✓" if vr.is_valid else " (needs repair)"
                                elif (
                                    step_node == "sql_executor"
                                    and accumulated_state.get("query_result")
                                ):
                                    qr = accumulated_state["query_result"]
                                    detail = (
                                        f" ({qr.row_count} rows)"
                                        if qr.success
                                        else " (failed)"
                                    )
                                steps_md.append(f"✅ {step_desc}{detail}")
                            else:
                                steps_md.append(f"⬜ {step_desc}")

                        steps_placeholder.markdown("  \n".join(steps_md))

                    settings.persist_enabled = enable_persistence

                    runner = WorkflowRunner(settings)
                    final_state = runner.run(
                        query=query.strip(),
                        on_progress=handle_progress,
                    )

                    status.update(
                        label="Workflow complete!", state="complete", expanded=False
                    )

                    # Store final steps for display after rerun
                    final_steps_md = []
                    for step_node, step_desc in all_steps:
                        if step_node in completed_nodes:
                            detail = ""
                            if step_node == "table_selector" and accumulated_state.get(
                                "table_cards_with_selection"
                            ):
                                detail = f" ({len(accumulated_state['table_cards_with_selection'])} tables)"
                            elif step_node == "sql_validator" and accumulated_state.get(
                                "validation_result"
                            ):
                                vr = accumulated_state["validation_result"]
                                detail = " ✓" if vr.is_valid else " (needs repair)"
                            elif step_node == "sql_executor" and accumulated_state.get(
                                "query_result"
                            ):
                                qr = accumulated_state["query_result"]
                                detail = (
                                    f" ({qr.row_count} rows)"
                                    if qr.success
                                    else " (failed)"
                                )
                            final_steps_md.append(f"✅ {step_desc}{detail}")
                        else:
                            final_steps_md.append(f"⬜ {step_desc}")
                    st.session_state["workflow_steps"] = "  \n".join(final_steps_md)

                if final_state:
                    set_last_workflow_state(final_state)
                st.rerun()

            except Exception as exc:
                import traceback

                st.error(f"Workflow failed: {exc}")
                st.code(traceback.format_exc(), language="python")

    # Results section
    state = get_last_workflow_state()
    if state:
        st.markdown("---")

        # Show workflow steps if available
        if st.session_state.get("workflow_steps"):
            with st.expander("Workflow Steps", expanded=False):
                st.markdown(st.session_state["workflow_steps"])

        _render_generated_sql(state)
        _render_execution_results(state)

        # Details tabs
        st.markdown("---")
        tab_graphs, tab_context, tab_history = st.tabs(
            ["Workflow Graphs", "Input Context", "History"]
        )

        with tab_graphs:
            _render_workflow_graphs()

        with tab_context:
            st.caption("Table cards")
            render_table_cards(table_cards, accent=PRIMARY_BLUE)

        with tab_history:
            _render_history()
    else:
        # Show input context when no results yet
        st.markdown("---")
        st.markdown("#### Input context")
        st.caption("Table cards")
        render_table_cards(table_cards, accent=PRIMARY_BLUE)

    _render_footer()


if __name__ == "__main__":
    main()
