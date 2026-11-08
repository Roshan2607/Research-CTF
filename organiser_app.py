"""Uncharted Literature - organiser console (protected).

    streamlit run organiser_app.py --server.address 127.0.0.1 --server.port 8502

Bind to 127.0.0.1 so participants on the LAN cannot reach it. Access additionally
requires ORGANISER_PASSWORD from .env.
"""
from pathlib import Path

import streamlit as st

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:  # pragma: no cover
    pass

st.set_page_config(page_title="Uncharted Literature · Organiser", page_icon="🔒", layout="wide")

from challenge.organiser_view import render  # noqa: E402

render()
