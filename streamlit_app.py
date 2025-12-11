# TODO: cleanup this whole code
import json

import streamlit as st

from pathlib import Path
from typing import Any
from main import run_workflow

from sql_query_assistant import Settings
from sql_query_assistant.utils.table_mapper import TableMapper
from sql_query_assistant.utils import load_table_cards, load_assumption_catalog
from streamlit_ui import (
    render_intent_card,
    render_table_cards,
    render_assumptions_catalog,
)

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output"
STATE_DUMPS_DIR = OUTPUT_DIR / "state_dumps"
MAIN_GRAPH_PATH = OUTPUT_DIR / "graphs" / "main_graph.png"
HEADER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "header.jpg"
INTERPRETER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "interpreter_subgraph.png"
SQL_DRAFTER_GRAPH_PATH = OUTPUT_DIR / "graphs" / "sql_drafter_subgraph.png"
EXECUTOR_GRAPH_PATH = OUTPUT_DIR / "graphs" / "executor_subgraph.png"
PRIMARY_BLUE = "#0b2d59"
MAX_STEP = 4


def _safe_dump(model: Any) -> dict:
    """Convert pydantic models or plain objects to dict for display."""
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    if isinstance(model, dict):
        return model
    return {"value": model}


def _render_graph():
    if HEADER_GRAPH_PATH.exists():
        st.image(str(HEADER_GRAPH_PATH))
    else:
        st.info("Graph not found. Run python main.py --render-graph to generate output/main_graph.png.")


def _render_state_dump_selector():
    if not STATE_DUMPS_DIR.exists():
        st.info("No state dumps found yet. Run a query to create one.")
        return None

    dumps = sorted(STATE_DUMPS_DIR.glob("run_*.json"))
    if not dumps:
        st.info("No state dumps found yet. Run a query to create one.")
        return None

    labels = [f"{p.name}" for p in dumps]
    choice = st.selectbox("Load a previous run", labels)
    if not choice:
        return None
    return dumps[labels.index(choice)]


def _render_state_dump(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    st.subheader(f"State dump: {path.name}")
    st.json(data)


def _load_metadata(settings: Settings):
    """
    Load table cards and assumption catalog once and cache in session state.
    """
    if "table_cards" not in st.session_state or st.session_state.get("table_cards") is None:
        st.session_state["table_cards"] = load_table_cards(settings=settings, base_path=None)
    if "assumption_catalog" not in st.session_state or st.session_state.get("assumption_catalog") is None:
        st.session_state["assumption_catalog"] = load_assumption_catalog(settings=settings, catalog_path=None)


def _render_interpreter_section(state: dict[str, Any]):
    intent_card = state.get("intent_card")
    if not intent_card:
        st.info("No intent card available. Run a query first.")
        return

    st.subheader("Interpreter stage")
    col_img, col_intent = st.columns([1, 1])
    with col_img:
        if INTERPRETER_GRAPH_PATH.exists():
            st.image(str(INTERPRETER_GRAPH_PATH)) #, caption="Interpreter subgraph"
        else:
            st.info("Interpreter subgraph not found. Generate via --render-graph.")
    with col_intent:
        render_intent_card(intent_card, accent=PRIMARY_BLUE)


def _render_sql_section(state: dict[str, Any]):
    sql_draft = state.get("sql_draft")
    if not sql_draft:
        st.info("No SQL draft yet. Run a query first.")
        return

    draft_dict = _safe_dump(sql_draft)
    oracle_sql = draft_dict.get("sql")
    st.subheader("Draft SQL")
    col_img, col_sql = st.columns([1, 1])
    with col_img:
        if SQL_DRAFTER_GRAPH_PATH.exists():
            st.image(str(SQL_DRAFTER_GRAPH_PATH))
        else:
            st.info("SQL drafter subgraph not found. Generate via --render-graph.")
    with col_sql:
        st.code(oracle_sql or "", language="sql")

    # mapped_sql = TableMapper.convert_sql_to_sqlite(oracle_sql or "")
    # st.subheader("Mapped SQL (SQLite)")
    # st.code(mapped_sql, language="sql")


def _render_execution_section(state: dict[str, Any]):
    query_result = state.get("query_result")
    if not query_result:
        st.info("No execution result yet. Run a query first.")
        return

    result_dict = _safe_dump(query_result)
    st.subheader("Execution summary")
    col_img, col_metrics = st.columns([1, 1])
    with col_img:
        if EXECUTOR_GRAPH_PATH.exists():
            st.image(str(EXECUTOR_GRAPH_PATH))
        else:
            st.info("Executor subgraph not found. Generate via --render-graph.")
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
    #st.subheader("Previous runs")
    col_img, col_content = st.columns([1, 1])
    with col_img:
        if MAIN_GRAPH_PATH.exists():
            st.image(str(MAIN_GRAPH_PATH), caption="Main graph")
        else:
            st.info("Main graph not found. Generate via --render-graph.")
    with col_content:
        dump_path = _render_state_dump_selector()
        if dump_path:
            _render_state_dump(dump_path)


def _nav_controls():
    step = st.session_state.get("wizard_step", 0)
    col_back, col_next = st.columns(2)
    if col_back.button("Back", key=f"back_{step}", disabled=step <= 0):
        st.session_state["wizard_step"] = max(step - 1, 0)
        st.rerun()

    disable_next = step >= MAX_STEP or (st.session_state.get("last_state") is None and step < MAX_STEP)
    if col_next.button("Next", key=f"next_{step}", disabled=disable_next):
        st.session_state["wizard_step"] = min(step + 1, MAX_STEP)
        st.rerun()


def main():
    if "wizard_step" not in st.session_state:
        st.session_state["wizard_step"] = 0
    if "last_state" not in st.session_state:
        st.session_state["last_state"] = None

    st.set_page_config(page_title="SQL Query Assistant", layout="wide")
    st.markdown(
        f"""
        <style>
        div.stButton > button:first-child {{
            background-color: {PRIMARY_BLUE};
            color: #ffffff;
            border: 1px solid {PRIMARY_BLUE};
        }}
        div.stButton > button:first-child:hover {{
            background-color: #0d3568;
            border-color: #0d3568;
        }}
        div.stCheckbox input[type="checkbox"] {{
            accent-color: {PRIMARY_BLUE};
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )

    settings = Settings()
    _load_metadata(settings)
    table_cards = st.session_state.get("table_cards") or []
    assumption_catalog = st.session_state.get("assumption_catalog") or []

    # st.title("SQL Query Assistant (LangGraph)")
    # st.caption("Minimal demo: run a query, see the graph, inspect results/state.")

    _render_graph()

    step = st.session_state["wizard_step"]

    # Step 0: Run a query
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
                        st.session_state["last_state"] = state
                        st.session_state["wizard_step"] = 1
                        st.rerun()
                    except Exception as exc:  # pragma: no cover - UI guard
                        st.error(f"Workflow failed: {exc}")
    # Step 1: Interpreter stage
    if step == 1:
        st.markdown("---")
        _render_interpreter_section(st.session_state.get("last_state") or {})
        _nav_controls()

    # Step 2: SQL draft
    if step == 2:
        st.markdown("---")
        _render_sql_section(st.session_state.get("last_state") or {})
        _nav_controls()

    # Step 3: Execution summary
    if step == 3:
        st.markdown("---")
        _render_execution_section(st.session_state.get("last_state") or {})
        _nav_controls()

    # Step 4: Previous runs
    if step == 4:
        st.markdown("---")
        st.header("Previous runs")
        _render_previous_runs_section()
        _nav_controls()


if __name__ == "__main__":
    main()
