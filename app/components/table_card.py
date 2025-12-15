import streamlit as st

from sql_query_assistant.domain import TableCard

from app.config import PRIMARY_BLUE


def render_table_cards(table_cards: list[TableCard], *, accent: str = PRIMARY_BLUE) -> None:
    """
    Render visual summary of table cards with metadata and column information.

    Args:
        table_cards: List of TableCard objects to display
        accent: Hex color code for highlights (default: PRIMARY_BLUE)
    """
    if not table_cards:
        st.info("No table cards loaded.")
        return

    for card in table_cards:
        cols = ", ".join(card.table_metadata.primary_key) or "—"
        column_summaries = ", ".join(f"{c.name} ({c.type})" for c in card.columns[:6])
        if len(card.columns) > 6:
            column_summaries += " …"

        st.markdown(
            f"""
            <div style="border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:12px;
                        background-color:#fff;">
                <div style="font-size:14px;font-weight:700;color:{accent};">{card.table_metadata.name}</div>
                <div style="font-size:12px;color:#475569;margin-top:4px;">{card.table_metadata.description}</div>
                <div style="font-size:12px;color:#111827;margin-top:6px;"><strong>Primary key:</strong> {cols}</div>
                <div style="font-size:12px;color:#111827;margin-top:2px;"><strong>Columns:</strong> {column_summaries}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
