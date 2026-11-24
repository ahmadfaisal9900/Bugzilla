"""About: what the assistant can and can't do, in plain language."""

from __future__ import annotations

import streamlit as st

from ..ui import components

ABOUT = """
<h2 class='section-title'>What it answers from</h2>
<p>A saved snapshot of about 3,000 Firefox bugs from Mozilla Bugzilla, not live Bugzilla.
Changes made after the snapshot aren't included.</p>

<h2 class='section-title'>How to check an answer</h2>
<p>Every answer lists the bug reports it used. Hover a link to see the evidence, or open it on
bugzilla.mozilla.org.</p>

<h2 class='section-title'>When it doesn't know</h2>
<p>If the archive doesn't hold enough evidence, it says so instead of guessing. When the free
model quota runs out, it shows the most relevant reports without a written answer.</p>

<h2 class='section-title'>Answer modes</h2>
<p><b>Recommended</b> picks a method per question. <b>Fast</b> runs a single search.
<b>Deep read</b> reads a bug's full history first and is slower. Each question is answered on its
own; earlier messages aren't sent with the next one.</p>
"""


def render() -> None:
    components.page_width(880)
    components.page_header("About", "What the assistant can do and where its answers come from.")
    with st.container(key="prose"):
        st.markdown(ABOUT, unsafe_allow_html=True)
