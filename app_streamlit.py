"""Minimal Streamlit UI for the reusable HO definition retrieval module.

Install and run manually with:
    pip install streamlit
    streamlit run app_streamlit.py
"""

import streamlit as st

from src.definitions.search import answer_definition_question

st.title("HO Definitiezoeker")

query = st.text_input("Stel een vraag over de HO-documentatie:")

if query:
    answer = answer_definition_question(query)
    st.markdown(answer)
