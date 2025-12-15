import streamlit as st

from typing import Iterable

from sql_query_assistant.domain import (
    IntentCard,
    SelectedAssumption,
    AvailableOption,
)

from app.config import PRIMARY_BLUE


def _render_chip(option: AvailableOption, accent: str) -> str:
    """
    Render a single option chip as HTML.

    Args:
        option: The available option to render
        accent: Hex color code for the chip accent color

    Returns:
        HTML string for the chip
    """
    bg = f"{accent}1a"  # light tint
    font_weight = "700" if option.selected else "500"
    return (
        f"<span style='display:inline-block;padding:4px 10px;border-radius:12px;"
        f"background:{bg};color:{accent};font-weight:{font_weight};margin:2px;'>"
        f"{option.label or option.value}"
        f"</span>"
    )


def _chips(options: Iterable[AvailableOption] | None, accent: str) -> str:
    """
    Render multiple option chips as HTML.

    Args:
        options: Iterable of available options to render, or None
        accent: Hex color code for the chip accent color

    Returns:
        Concatenated HTML string of all chips, or empty string if no options
    """
    if not options:
        return ""
    return "".join(_render_chip(opt, accent) for opt in options)


def _render_assumption(assumption: SelectedAssumption, accent: str) -> None:
    """
    Render a single assumption choice card.

    Args:
        assumption: The selected assumption to display
        accent: Hex color code for highlights and accent elements
    """
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


def render_intent_card(intent_card: IntentCard, *, accent: str = PRIMARY_BLUE) -> None:
    """
    Render the intent card with task summary and selected assumptions.

    Args:
        intent_card: The LLM-produced intent card containing task and assumptions
        accent: Hex color code used for highlights and styling (default: PRIMARY_BLUE)
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
