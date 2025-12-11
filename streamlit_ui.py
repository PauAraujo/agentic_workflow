# TODO: cleanup this whole code

from __future__ import annotations

from typing import Iterable

import streamlit as st

from sql_query_assistant.domain import (
    IntentCard,
    SelectedAssumption,
    AvailableOption,
    TableCard,
    AssumptionCatalogEntry,
)


def _render_chip(option: AvailableOption, accent: str) -> str:
    """Render a single option chip as HTML."""
    bg = f"{accent}1a"  # light tint
    font_weight = "700" if option.selected else "500"
    return (
        f"<span style='display:inline-block;padding:4px 10px;border-radius:12px;"
        f"background:{bg};color:{accent};font-weight:{font_weight};margin:2px;'>"
        f"{option.label or option.value}"
        f"</span>"
    )


def _chips(options: Iterable[AvailableOption] | None, accent: str) -> str:
    if not options:
        return ""
    return "".join(_render_chip(opt, accent) for opt in options)


def render_intent_card(intent_card: IntentCard, *, accent: str = "#0b2d59") -> None:
    """
    Nicely render the intent card: task summary and selected assumptions.

    Args:
        intent_card: The LLM-produced intent card.
        accent: Hex color used for highlights.
    """
    st.markdown(
        f"""
        <div style="border:1px solid {accent};border-radius:10px;padding:12px 14px;margin-bottom:10px;
                   background-color:#f8fafc;">
            <div style="font-size:13px;font-weight:700;color:{accent};letter-spacing:0.5px;">User Query</div>
            <div style="font-size:16px;font-weight:700;margin-top:4px;">{intent_card.task}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("**Selected assumptions**")

    for assumption in intent_card.assumption_response.assumption_choices:
        _render_assumption(assumption, accent)


def _render_assumption(assumption: SelectedAssumption, accent: str) -> None:
    """Render a single assumption choice card."""
    title = assumption.assumption_label or assumption.assumption_id
    value_label = assumption.selected_label or assumption.selected_value
    description = assumption.option_description or ""
    rationale = assumption.rationale
    chips_html = _chips(assumption.available_options, accent)

    st.markdown(
        f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:12px 14px;margin-bottom:10px;
                    background-color:#fff;">
            <div style="font-size:15px;font-weight:700;margin-bottom:4px;">{title}</div>
            <div style="font-size:14px;color:{accent};font-weight:700;">{value_label}</div>
            <div style="font-size:12px;color:#475569;margin-top:4px;">{description}</div>
            <div style="font-size:12px;color:#111827;margin-top:8px;"><strong>Rationale:</strong> {rationale}</div>
            {'<div style=\"margin-top:8px;\">'+chips_html+'</div>' if chips_html else ''}
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_table_cards(table_cards: list[TableCard], *, accent: str = "#0b2d59") -> None:
    """Visual summary of table cards (name, description, primary key, sample columns)."""
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


def render_assumptions_catalog(
    catalog: list[AssumptionCatalogEntry], *, accent: str = "#0b2d59"
) -> None:
    """Visual summary of assumption catalog entries and their options."""
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
