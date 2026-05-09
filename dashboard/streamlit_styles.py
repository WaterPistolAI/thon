# Copyright 2025 Alibaba Group Holding Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Custom dark-theme CSS injection for the THON Streamlit dashboard."""

import streamlit as st

_DARK_CSS = """
<style>
:root {
    --bg-primary: #0f1117;
    --bg-secondary: #1a1d27;
    --bg-card: #1e2130;
    --bg-hover: #252838;
    --border: #2d3148;
    --text-primary: #e4e6f0;
    --text-secondary: #8b8fa3;
    --accent: #6366f1;
    --accent-hover: #818cf8;
    --success: #22c55e;
    --warning: #f59e0b;
    --danger: #ef4444;
    --info: #3b82f6;
}

.stApp {
    background-color: var(--bg-primary) !important;
    color: var(--text-primary) !important;
}

section[data-testid="stSidebar"] {
    background-color: var(--bg-secondary) !important;
    border-right: 1px solid var(--border) !important;
}

section[data-testid="stSidebar"] .stRadio > label {
    color: var(--text-secondary) !important;
}

section[data-testid="stSidebar"] .stRadio > label[data-checked="true"] {
    color: white !important;
    background-color: var(--accent) !important;
    border-radius: 8px;
}

.stMetric {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 16px !important;
}

.stMetric label {
    color: var(--text-secondary) !important;
    font-size: 12px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}

.stMetric [data-testid="stMetricValue"] {
    color: var(--text-primary) !important;
    font-size: 18px !important;
    font-weight: 700 !important;
}

.stDataFrame {
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}

.stExpander {
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    background-color: var(--bg-card) !important;
}

.stExpander > details > summary {
    color: var(--text-primary) !important;
}

.stButton > button {
    border-radius: 8px !important;
}

.stButton > button[kind="primary"] {
    background-color: var(--accent) !important;
    border-color: var(--accent) !important;
    color: white !important;
}

.stButton > button[kind="primary"]:hover {
    background-color: var(--accent-hover) !important;
    border-color: var(--accent-hover) !important;
}

.stTextInput > div > div > input {
    background-color: var(--bg-secondary) !important;
    border-color: var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
}

.stTextInput > div > div > input:focus {
    border-color: var(--accent) !important;
}

.stSelectbox > div > div > div {
    background-color: var(--bg-secondary) !important;
    border-color: var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
}

.stNumberInput > div > div > input {
    background-color: var(--bg-secondary) !important;
    border-color: var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 8px !important;
}

.stCheckbox > label {
    color: var(--text-primary) !important;
}

h1, h2, h3 {
    color: var(--text-primary) !important;
}

.stDivider {
    border-color: var(--border) !important;
}

.stAlert {
    border-radius: 8px !important;
}

.stAlert p {
    font-size: 13px !important;
    word-break: break-word !important;
}

.stAlert code {
    font-size: 12px !important;
    word-break: break-all !important;
}

.stModal {
    background-color: var(--bg-card) !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
}

.stModal h2, .stModal h3 {
    color: var(--text-primary) !important;
}

[data-testid="stToast"] {
    border-radius: 8px !important;
}
</style>
"""


def inject_dark_theme() -> None:
    st.markdown(_DARK_CSS, unsafe_allow_html=True)
