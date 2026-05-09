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

"""Supplemental CSS for the THON Streamlit dashboard.

Native theming is handled by .streamlit/config.toml (colors, fonts, radii).
This module provides only component-level polish that config.toml cannot express.
"""

import streamlit as st

_SUPPLEMENTAL_CSS = """
<style>
.stMetric {
    padding: 16px !important;
}

.stMetric label {
    font-size: 12px !important;
    text-transform: uppercase !important;
    letter-spacing: 0.5px !important;
}

.stMetric [data-testid="stMetricValue"] {
    font-size: 18px !important;
    font-weight: 700 !important;
}

.stAlert p {
    font-size: 13px !important;
    word-break: break-word !important;
}

.stAlert code {
    font-size: 12px !important;
    word-break: break-all !important;
}
</style>
"""


def inject_custom_styles() -> None:
    st.markdown(_SUPPLEMENTAL_CSS, unsafe_allow_html=True)
