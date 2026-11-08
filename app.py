"""Uncharted Literature - participant app.

    streamlit run app.py --server.port 8501

Serves only participant-safe data. The organiser console is a separate app
(organiser_app.py) meant to run on localhost only.
"""
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # pragma: no cover
    pass

st.set_page_config(page_title="Uncharted Literature", page_icon="🧭", layout="wide")

from challenge.participant_view import render  # noqa: E402

render()
