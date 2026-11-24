"""Cached access to the API for the Streamlit layer.

The client is one shared resource per server process; catalog data changes rarely,
quota and readiness are refreshed every few seconds.
"""

from __future__ import annotations

import streamlit as st

from ..api import ApiClient, ApiError, Catalog, QuotaStatus
from ..config import Settings


@st.cache_resource
def get_client() -> ApiClient:
    return ApiClient(Settings.from_env())


@st.cache_data(ttl=300, show_spinner=False)
def get_catalog() -> Catalog:
    return get_client().catalog()


@st.cache_data(ttl=10, show_spinner=False)
def api_ready() -> bool:
    return get_client().is_ready()


@st.cache_data(ttl=15, show_spinner=False)
def get_quota() -> QuotaStatus | None:
    try:
        return get_client().quota()
    except ApiError:  # quota is informational; never block the page on it
        return None
