import streamlit as st

from sql_query_assistant.domain import AssumptionCatalogEntry

from app.config import PRIMARY_BLUE


def render_assumptions_catalog(
    catalog: list[AssumptionCatalogEntry], *, accent: str = PRIMARY_BLUE
) -> None:
    """
    Render visual summary of assumption catalog entries with their options.

    Args:
        catalog: List of AssumptionCatalogEntry objects to display
        accent: Hex color code for highlights (default: PRIMARY_BLUE)
    """
    if not catalog:
        st.info("No assumptions catalog loaded.")
        return

    for entry in catalog:
        chips = "".join(
            f"<span style='display:inline-block;padding:4px 10px;border-radius:12px;"
            f"background:{accent}1a;color:{accent};font-weight:600;margin:2px;'>"
            f"{opt.label or opt.value}"
            f"</span>"
            for opt in entry.options
        )
        st.markdown(
            f"""
            <div style="border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:12px;
                        background-color:#fff;">
                <div style="font-size:14px;font-weight:700;color:{accent};">{entry.label or entry.id}</div>
                <div style="font-size:12px;color:#475569;margin-top:4px;">{entry.description}</div>
                <div style="font-size:12px;color:#111827;margin-top:6px;"><strong>Options:</strong></div>
                <div style="margin-top:4px;">{chips}</div>
                <div style="font-size:12px;color:#111827;margin-top:6px;"><strong>Default:</strong> {entry.default or '—'}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
