"""
==============================================================================
GeoAI Final Project - Interactive Streamlit Frontend Application
==============================================================================
This application serves as the interactive frontend for the GeoAI spatial
intelligence system. It connects a conversational chat interface with an
interactive Folium map centered over Ukraine, demonstrating bi-directional
synchronization between map clicks, point selection/removal, and RAG agent queries.

Key Features:
    1. Self-bootstrapping dependency verification for cross-system portability.
    2. Dynamic, adjustable split-screen layout (Chat & Map).
    3. Multi-modal RAG routing via `query_geo_agent` (text only, point only, both).
    4. Decoupled point selection & state management:
       - Map click -> selects coordinate(s) and updates `selected_points` WITHOUT immediate backend calls.
       - Point removal -> remove individual selected points or clear all via UI controls.
       - Chat prompt -> pairs user inquiry with selected coordinate(s).
    5. Real-time Folium visualization of tactical markers, circles, and buffers.
    6. Palantir Defense C2 Tactical Protocol Styling (electric cyan & dark slate HUD).

Team & Deployment Notice:
    This file is completely self-contained and runnable on any OS (Windows, macOS,
    Linux). Running `streamlit run app.py` or double-clicking `run_app.bat` will
    launch the app. Direct execution via `python app.py` will automatically forward
    to the Streamlit runtime.
==============================================================================
"""

import sys
import subprocess
import importlib.util
from typing import Optional, Tuple, List, Dict, Any

# ==============================================================================
# 0. In-Code Environment & Dependency Bootstrap
# ==============================================================================
# Ensures that any coworker cloning this repository on any operating system has
# the necessary libraries installed without manual intervention.

REQUIRED_DEPENDENCIES = {
    "streamlit": "streamlit>=1.30.0",
    "folium": "folium>=0.15.0",
    "streamlit_folium": "streamlit-folium>=0.18.0",
    "streamlit_adjustable_columns": "streamlit-adjustable-columns>=0.2.0",
    "pytest": "pytest>=7.0.0",
}

def verify_and_install_dependencies():
    """Verify presence of core packages; automatically install missing ones."""
    missing_packages = []
    for module_name, pip_spec in REQUIRED_DEPENDENCIES.items():
        if importlib.util.find_spec(module_name) is None:
            missing_packages.append(pip_spec)

    if missing_packages:
        print(f"[GeoAI Bootstrap] Missing dependencies detected: {missing_packages}")
        print("[GeoAI Bootstrap] Installing required packages across system environment...")
        try:
            subprocess.check_call([
                sys.executable, "-m", "pip", "install", *missing_packages
            ])
            print("[GeoAI Bootstrap] All dependencies installed successfully.")
        except Exception as exc:
            print(f"[GeoAI Bootstrap] Warning: Automated dependency installation encountered: {exc}")

# Execute environment check before importing third-party modules
verify_and_install_dependencies()

# Core Streamlit and mapping imports
import streamlit as st
import folium
from streamlit_folium import st_folium

# Layout import with graceful fallback
try:
    from streamlit_adjustable_columns import adjustable_columns
except ImportError:
    # Fallback to standard st.columns if adjustable component fails to compile on any OS
    def adjustable_columns(spec, **kwargs):
        return st.columns(spec)

# Import backend contracts, mock routing engine, and bounding box utility
from geo_agent import MapLayer, AgentResponse, query_geo_agent, to_bounding_box


# ==============================================================================
# 1. Visual Theme Configurations & Page Setup (Palantir Defense C2)
# ==============================================================================
THEME_CONFIG = {
    "name": "PALANTIR DEFENSE C2",
    "protocol_code": "SEC-OP // C2-GOTHAM",
    "primary": "#00e5ff",          # Electric Cyan
    "secondary": "#0ea5e9",        # Tactical Sky Blue
    "glow": "rgba(0, 229, 255, 0.4)",
    "bg_card": "rgba(14, 22, 32, 0.88)",
    "border_card": "rgba(0, 229, 255, 0.28)",
    "text_main": "#e2e8f0",
    "text_dim": "#7dd3fc",
    "badge_bg": "rgba(0, 229, 255, 0.12)",
    "badge_color": "#00e5ff",
    "badge_border": "rgba(0, 229, 255, 0.35)",
    "status_bg": "rgba(0, 229, 255, 0.08)",
    "status_border": "#00e5ff",
    "operator_tag": "[OPERATOR // C2-CMD]",
    "ai_tag": "[GEO-AI // SYNTHESIS]",
    "user_avatar": "🎯",
    "ai_avatar": "🛰️",
    "folium_marker_color": "red",
    "folium_marker_icon": "star",
}
t_cfg = THEME_CONFIG

# Configure Streamlit page properties to use a responsive wide layout
st.set_page_config(
    page_title=f"GeoAI Intelligence Hub [{t_cfg['name']}]",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for tactical HUD interface styling
st.markdown(f"""
<style>
    /* Global Typography */
    html, body, [class*="css"], font, span, p, div, button, input {{
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    }}

    /* Lock Viewport to Chrome Window - Zero Main Window Scrollbar */
    html, body {{
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
        margin: 0 !important;
        padding: 0 !important;
    }}

    /* Suppress outer window scrollbars in Chrome/Edge/Firefox */
    html::-webkit-scrollbar, body::-webkit-scrollbar, [data-testid="stAppViewContainer"]::-webkit-scrollbar {{
        display: none !important;
        width: 0 !important;
        height: 0 !important;
    }}

    [data-testid="stAppViewContainer"] {{
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
    }}

    section[data-testid="stMain"] {{
        height: 100vh !important;
        max-height: 100vh !important;
        overflow: hidden !important;
        padding: 0 !important;
    }}

    div[data-testid="stMainBlockContainer"],
    .main .block-container {{
        height: 100vh !important;
        max-height: 100vh !important;
        padding-top: 2.2rem !important;
        padding-bottom: 0.3rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 100% !important;
        box-sizing: border-box !important;
        overflow: hidden !important;
    }}

    /* Header & Side Ribbon (Sidebar Toggle Controls) */
    header[data-testid="stHeader"] {{
        background: transparent !important;
        height: 2.2rem !important;
        min-height: 2.2rem !important;
        z-index: 100 !important;
        display: flex !important;
        align-items: center !important;
    }}

    /* Restore and style the side ribbon (sidebar collapsed control) */
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"] {{
        display: flex !important;
        visibility: visible !important;
        opacity: 1 !important;
        z-index: 1000 !important;
    }}

    [data-testid="stSidebarCollapsedControl"] button,
    [data-testid="stSidebarCollapseButton"] button {{
        color: {t_cfg['primary']} !important;
        background: {t_cfg['bg_card']} !important;
        border: 1px solid {t_cfg['border_card']} !important;
        border-radius: 4px !important;
        transition: all 0.2s ease-in-out !important;
    }}

    [data-testid="stSidebarCollapsedControl"] button:hover,
    [data-testid="stSidebarCollapseButton"] button:hover {{
        border-color: {t_cfg['primary']} !important;
        box-shadow: 0 0 10px {t_cfg['glow']} !important;
        color: #ffffff !important;
    }}

    footer {{
        display: none !important;
    }}

    /* Compact resizer handles iframe from adjustable_columns */
    iframe[title="streamlit_adjustable_columns.streamlit_adjustable_columns"] {{
        height: 38px !important;
        min-height: 38px !important;
        max-height: 38px !important;
        margin-top: 2px !important;
        margin-bottom: 6px !important;
        border-radius: 4px !important;
    }}

    /* Independent vertical scrolling for sidebar controls */
    section[data-testid="stSidebar"] {{
        height: 100vh !important;
        overflow-y: auto !important;
    }}

    /* Dedicated Tactical Scrollbars for scrollable sub-panels (Chat & Sidebar) */
    *::-webkit-scrollbar {{
        width: 6px;
        height: 6px;
    }}
    *::-webkit-scrollbar-track {{
        background: rgba(0, 0, 0, 0.4);
        border-radius: 3px;
    }}
    *::-webkit-scrollbar-thumb {{
        background: {t_cfg['border_card']};
        border-radius: 3px;
        border: 1px solid {t_cfg['primary']};
        box-shadow: 0 0 6px {t_cfg['glow']};
    }}
    *::-webkit-scrollbar-thumb:hover {{
        background: {t_cfg['primary']};
        box-shadow: 0 0 10px {t_cfg['glow']};
    }}

    /* Metric & Badge styling */
    .geo-badge {{
        display: inline-block;
        padding: 5px 12px;
        border-radius: 4px;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        background-color: {t_cfg['badge_bg']};
        color: {t_cfg['badge_color']};
        border: 1px solid {t_cfg['badge_border']};
        margin-bottom: 8px;
        box-shadow: 0 0 8px {t_cfg['glow']};
    }}
    .geo-status-box {{
        background-color: {t_cfg['status_bg']};
        border-left: 3px solid {t_cfg['status_border']};
        border-top: 1px solid {t_cfg['border_card']};
        border-right: 1px solid {t_cfg['border_card']};
        border-bottom: 1px solid {t_cfg['border_card']};
        padding: 10px 14px;
        border-radius: 4px;
        margin-bottom: 10px;
        font-size: 0.85rem;
        color: {t_cfg['text_main']};
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.3);
    }}
    .column-header {{
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 12px;
        background: {t_cfg['bg_card']};
        border-left: 3px solid {t_cfg['primary']};
        border-top: 1px solid {t_cfg['border_card']};
        border-right: 1px solid {t_cfg['border_card']};
        border-bottom: 1px solid {t_cfg['border_card']};
        border-radius: 4px;
        font-size: 0.88rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        margin-bottom: 0.45rem;
        color: {t_cfg['primary']};
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
        text-shadow: 0 0 8px {t_cfg['glow']};
    }}

    /* Chat Messages HUD */
    div[data-testid="stChatMessage"] {{
        background-color: {t_cfg['bg_card']} !important;
        border: 1px solid {t_cfg['border_card']} !important;
        border-radius: 4px !important;
        margin-bottom: 0.65rem !important;
        padding: 0.75rem !important;
        box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4) !important;
    }}
    .chat-role-tag {{
        font-size: 0.72rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        margin-bottom: 4px;
        color: {t_cfg['primary']};
        opacity: 0.88;
    }}

    /* HUD Buttons */
    div.stButton > button {{
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
        text-transform: uppercase !important;
        letter-spacing: 0.07em !important;
        font-weight: 600 !important;
        border-radius: 3px !important;
        border: 1px solid {t_cfg['border_card']} !important;
        background: {t_cfg['bg_card']} !important;
        color: {t_cfg['text_main']} !important;
        transition: all 0.2s ease-in-out !important;
    }}
    div.stButton > button:hover {{
        border-color: {t_cfg['primary']} !important;
        color: {t_cfg['primary']} !important;
        box-shadow: 0 0 12px {t_cfg['glow']} !important;
        background: rgba(0, 0, 0, 0.5) !important;
    }}

    /* Telemetry Metrics */
    div[data-testid="stMetricValue"] {{
        font-family: 'JetBrains Mono', monospace !important;
        color: {t_cfg['primary']} !important;
        text-shadow: 0 0 10px {t_cfg['glow']} !important;
        font-size: 1.4rem !important;
    }}
    div[data-testid="stMetricLabel"] {{
        font-family: 'JetBrains Mono', monospace !important;
        text-transform: uppercase !important;
        letter-spacing: 0.08em !important;
        color: {t_cfg['text_dim']} !important;
        font-size: 0.8rem !important;
    }}

    /* Chat Input */
    div[data-testid="stChatInput"] {{
        border: 1px solid {t_cfg['border_card']} !important;
        border-radius: 4px !important;
        background: {t_cfg['bg_card']} !important;
        margin-top: 6px !important;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.4) !important;
    }}
    div[data-testid="stChatInput"]:focus-within {{
        border-color: {t_cfg['primary']} !important;
        box-shadow: 0 0 12px {t_cfg['glow']} !important;
    }}
    div[data-testid="stChatInput"] textarea {{
        color: {t_cfg['text_main']} !important;
        font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace !important;
        font-size: 0.85rem !important;
    }}
    div[data-testid="stChatInput"] textarea::placeholder {{
        color: {t_cfg['text_dim']} !important;
        opacity: 0.75 !important;
    }}

    /* Sidebar Title */
    .sidebar-title {{
        font-size: 1.15rem;
        font-weight: 800;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: {t_cfg['primary']};
        text-shadow: 0 0 10px {t_cfg['glow']};
        margin-bottom: 2px;
    }}
</style>
""", unsafe_allow_html=True)


# ==============================================================================
# 2. Session State Initialization
# ==============================================================================
# Maintain conversational history, spatial layers, click tracking, and selected points.
if "messages" not in st.session_state:
    # Initialize chat history with an introductory greeting
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "👋 **Welcome to the GeoAI Spatial Intelligence Hub.**\n\n"
                "I am your geospatial intelligence assistant. You can:\n"
                "1. **Click coordinates on the map** to select locations of interest (without triggering automatic calls).\n"
                "2. **Manage selected points** in the sidebar (remove individual points or clear all).\n"
                "3. **Type a targeted query** in the chat (e.g. *\"What units are stationed here?\"*) to analyze your selected points.\n"
                "4. **Ask general questions** (e.g. *\"Show key logistics nodes\"*) to explore strategic regional hubs."
            )
        }
    ]

if "map_layers" not in st.session_state:
    # List of MapLayer dataclass objects dynamically rendered on Folium
    st.session_state.map_layers = []

if "last_clicked" not in st.session_state:
    # Keeps track of the most recently processed click coordinates (lat, lng) to prevent infinite loops
    st.session_state.last_clicked = None

if "selected_points" not in st.session_state:
    # List of coordinate tuples [(lat, lng), ...] representing all currently selected points
    st.session_state.selected_points = []

if "bounding_box" not in st.session_state:
    # Standard two-point bounding box tuple ((min_lat, min_lng), (max_lat, max_lng)) [lower-left, upper-right]
    st.session_state.bounding_box = None

if "active_point" not in st.session_state:
    # Most recently selected coordinate tuple (lat, lng) for backward compatibility
    st.session_state.active_point = None

if "selection_mode" not in st.session_state or st.session_state.selection_mode not in ["Bounding Box", "Point Selection"]:
    # Point selection mode: 'Bounding Box' (default) or 'Point Selection'
    st.session_state.selection_mode = "Bounding Box"

if "keep_points" not in st.session_state:
    # Whether to keep selected points after sending a chat prompt
    st.session_state.keep_points = False


# ==============================================================================
# 3. Sidebar Utility Controls & Intelligence Dashboard
# ==============================================================================
with st.sidebar:
    st.markdown("<div class='sidebar-title'>🌍 GEO-AI COMMAND</div>", unsafe_allow_html=True)
    st.caption("Multimodal Geocoded RAG Intelligence")
    st.markdown("---")



    # Display active spatial targeting status and management
    st.subheader("🎯 Selected Points")

    selection_modes = ["Bounding Box", "Point Selection"]
    current_sel_mode = st.session_state.get("selection_mode", "Bounding Box")
    if current_sel_mode not in selection_modes:
        current_sel_mode = "Bounding Box"
        st.session_state.selection_mode = "Bounding Box"
    sel_index = selection_modes.index(current_sel_mode)

    sel_mode = st.radio(
        "Selection Mode:",
        options=selection_modes,
        index=sel_index,
        help="Bounding Box (Default): Click 2 points to define lower-left and upper-right. Point Selection: Click a point on the map; clicking again cancels the previous selection and selects the new point.",
        horizontal=True,
        key="selection_mode_radio"
    )
    if sel_mode != st.session_state.selection_mode:
        st.session_state.selection_mode = sel_mode
        if sel_mode == "Point Selection" and len(st.session_state.selected_points) > 1:
            st.session_state.selected_points = [st.session_state.selected_points[-1]]
            st.session_state.bounding_box = None
            st.session_state.active_point = st.session_state.selected_points[0]
        elif sel_mode == "Bounding Box" and len(st.session_state.selected_points) == 2:
            st.session_state.bounding_box = to_bounding_box(
                st.session_state.selected_points[0], st.session_state.selected_points[1]
            )
            st.session_state.selected_points = [st.session_state.bounding_box[0], st.session_state.bounding_box[1]]
        st.rerun()

    # Bounding Box Mode UI
    if st.session_state.selection_mode == "Bounding Box":
        if st.session_state.bounding_box:
            ll, ur = st.session_state.bounding_box
            st.markdown(
                f"<div class='geo-badge'>📦 Bounding Box Selected (2 Points)</div>",
                unsafe_allow_html=True
            )
            # Display Lower-Left and Upper-Right with individual remove buttons
            col_ll1, col_ll2 = st.columns([3, 1])
            with col_ll1:
                st.markdown(f"**Lower-Left (SW):** `{ll[0]:.4f}°, {ll[1]:.4f}°`")
            with col_ll2:
                if st.button("❌", key="btn_remove_ll", help="Remove Lower-Left corner"):
                    st.session_state.selected_points = [ur]
                    st.session_state.bounding_box = None
                    st.session_state.active_point = ur
                    st.session_state.last_clicked = None
                    st.rerun()

            col_ur1, col_ur2 = st.columns([3, 1])
            with col_ur1:
                st.markdown(f"**Upper-Right (NE):** `{ur[0]:.4f}°, {ur[1]:.4f}°`")
            with col_ur2:
                if st.button("❌", key="btn_remove_ur", help="Remove Upper-Right corner"):
                    st.session_state.selected_points = [ll]
                    st.session_state.bounding_box = None
                    st.session_state.active_point = ll
                    st.session_state.last_clicked = None
                    st.rerun()

            lat_span = abs(ur[0] - ll[0])
            lng_span = abs(ur[1] - ll[1])
            st.caption(f"Area Span: ΔLat: `{lat_span:.4f}°` | ΔLng: `{lng_span:.4f}°`")
            st.caption("Type a prompt in the chat to analyze this bounded area.")

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("🗑️ Clear Box", use_container_width=True, help="Remove bounding box selection"):
                    st.session_state.selected_points = []
                    st.session_state.bounding_box = None
                    st.session_state.active_point = None
                    st.session_state.last_clicked = None
                    st.rerun()
            with col_b2:
                if st.button("🔍 Recon Scan", use_container_width=True, help="Run reconnaissance scan on bounding box"):
                    recon_response: AgentResponse = query_geo_agent(
                        text_prompt=None,
                        selected_point=None,
                        bounding_box=st.session_state.bounding_box,
                        chat_history=st.session_state.messages
                    )
                    st.session_state.messages.append({
                        "role": "user",
                        "content": f"Reconnaissance requested for bounding box: Lower-Left ({ll[0]:.4f}°, {ll[1]:.4f}°), Upper-Right ({ur[0]:.4f}°, {ur[1]:.4f}°)"
                    })
                    st.session_state.messages.append({"role": "assistant", "content": recon_response.answer})
                    st.session_state.map_layers.extend(recon_response.layers)
                    if not st.session_state.get("keep_points", False):
                        st.session_state.selected_points = []
                        st.session_state.bounding_box = None
                        st.session_state.active_point = None
                    st.rerun()

            st.checkbox("Keep points selected after sending prompt", key="keep_points")

        elif len(st.session_state.selected_points) == 1:
            p1 = st.session_state.selected_points[0]
            st.markdown(
                f"<div class='geo-badge'>⏳ Corner 1 (Waiting for Corner 2)</div>",
                unsafe_allow_html=True
            )
            col_p1, col_p2 = st.columns([3, 1])
            with col_p1:
                st.markdown(f"**Corner 1:** `{p1[0]:.4f}°, {p1[1]:.4f}°`")
            with col_p2:
                if st.button("❌", key="btn_remove_c1", help="Cancel Corner 1"):
                    st.session_state.selected_points = []
                    st.session_state.bounding_box = None
                    st.session_state.active_point = None
                    st.session_state.last_clicked = None
                    st.rerun()
            st.info("Click a second point on the map to complete the bounding box.")
        else:
            st.info("No bounding box selected. Click two points on the map to define a bounding box (lower-left, upper-right).")

    # Point Selection Mode UI
    else:
        if st.session_state.selected_points:
            plat, plng = st.session_state.selected_points[0]
            st.markdown(
                f"<div class='geo-badge'>📍 1 Point Selected</div>",
                unsafe_allow_html=True
            )
            col_p1, col_p2 = st.columns([3, 1])
            with col_p1:
                st.markdown(f"**Point:** `{plat:.4f}°, {plng:.4f}°`")
            with col_p2:
                if st.button("❌", key="btn_remove_single_pt", help="Remove selected point"):
                    st.session_state.selected_points = []
                    st.session_state.bounding_box = None
                    st.session_state.active_point = None
                    st.session_state.last_clicked = None
                    st.rerun()

            st.caption("Click another location on the map to replace this selection, or enter a prompt below to analyze it.")

            col_b1, col_b2 = st.columns(2)
            with col_b1:
                if st.button("🗑️ Clear Point", use_container_width=True, help="Remove selected point"):
                    st.session_state.selected_points = []
                    st.session_state.bounding_box = None
                    st.session_state.active_point = None
                    st.session_state.last_clicked = None
                    st.rerun()
            with col_b2:
                if st.button("🔍 Recon Scan", use_container_width=True, help="Run reconnaissance scan on selected point"):
                    pt = st.session_state.selected_points[0] if st.session_state.selected_points else None
                    recon_response: AgentResponse = query_geo_agent(
                        text_prompt=None,
                        selected_point=pt,
                        bounding_box=None,
                        chat_history=st.session_state.messages
                    )
                    st.session_state.messages.append({
                        "role": "user",
                        "content": f"Reconnaissance requested for coordinate: {plat:.4f}°, {plng:.4f}°"
                    })
                    st.session_state.messages.append({"role": "assistant", "content": recon_response.answer})
                    st.session_state.map_layers.extend(recon_response.layers)
                    if not st.session_state.get("keep_points", False):
                        st.session_state.selected_points = []
                        st.session_state.bounding_box = None
                        st.session_state.active_point = None
                    st.rerun()

            st.checkbox("Keep point selected after sending prompt", key="keep_points")
        else:
            st.info("No coordinate currently selected. Click on the map to select a point.")

    st.markdown("---")

    # Session metrics
    st.subheader("📊 Session Telemetry")
    col_m1, col_m2 = st.columns(2)
    with col_m1:
        st.metric("Chat Messages", len(st.session_state.messages))
    with col_m2:
        st.metric("Active Layers", len(st.session_state.map_layers))

    st.markdown("---")

    # Utility control buttons
    st.subheader("🛠️ Operations")
    if st.button("🗑️ Clear Chat History", use_container_width=True, help="Reset conversation messages"):
        st.session_state.messages = []
        st.rerun()

    if st.button("🗺️ Reset Map Layers", use_container_width=True, help="Clear all tactical map overlays and selection"):
        st.session_state.map_layers = []
        st.session_state.selected_points = []
        st.session_state.bounding_box = None
        st.session_state.active_point = None
        st.session_state.last_clicked = None
        st.rerun()

    if st.session_state.map_layers:
        with st.expander(f"🗺️ Manage Tactical Layers ({len(st.session_state.map_layers)})"):
            for l_idx, layer in enumerate(st.session_state.map_layers):
                col_ly1, col_ly2 = st.columns([3, 1])
                with col_ly1:
                    st.caption(f"{layer.name}")
                with col_ly2:
                    if st.button("🗑️", key=f"del_layer_{l_idx}", help=f"Remove layer '{layer.name}'"):
                        st.session_state.map_layers.pop(l_idx)
                        st.rerun()

    st.markdown("---")
    st.markdown("### 🧭 Layer Legend")
    st.markdown("- 🔲 **Dashed Box / Arrows**: Selected Bounding Box (Lower-Left & Upper-Right)")
    st.markdown("- 🔴 **Red Star / Pin**: Selected Points / Query Focus Marker")
    st.markdown("- 🟠 **Orange Zone / Box**: Tactical Area / 15 km Buffer")
    st.markdown("- 🟣 **Purple Pin / Zone**: Location Reconnaissance")
    st.markdown("- 🔵 **Blue Pin**: General Strategic Hubs")


# ==============================================================================
# 4. Main Application Workspace: Split-Screen Layout
# ==============================================================================
# Tactical labels for the column indicator boxes
col_labels = [
    "💬 Intel Console",
    "🗺️ Geospatial Theater of Operations"
]
# Split screen using streamlit_adjustable_columns with a 1 : 1.5 ratio
col1, col2 = adjustable_columns([1, 1.5], labels=col_labels)


# ------------------------------------------------------------------------------
# 5. Left Column: Chat Interface & Query Processing
# ------------------------------------------------------------------------------
with col1:
    # Inform the user when active coordinate(s) or bounding box are bound to the upcoming prompt
    if st.session_state.selected_points:
        pt_count = len(st.session_state.selected_points)
        is_bbox_mode = st.session_state.get("selection_mode") == "Bounding Box"

        if is_bbox_mode and st.session_state.get("bounding_box"):
            b_ll, b_ur = st.session_state.bounding_box
            st.markdown(
                f"<div class='geo-status-box'>"
                f"📦 <b>Bounding Box Attached (Two-Point Box):</b><br>"
                f"• <b>Lower-Left (SW):</b> <code>({b_ll[0]:.4f}°, {b_ll[1]:.4f}°)</code><br>"
                f"• <b>Upper-Right (NE):</b> <code>({b_ur[0]:.4f}°, {b_ur[1]:.4f}°)</code><br>"
                f"Enter your question below to query intelligence for this bounded region."
                f"</div>",
                unsafe_allow_html=True
            )
        elif is_bbox_mode and pt_count == 1:
            c1 = st.session_state.selected_points[0]
            st.markdown(
                f"<div class='geo-status-box'>"
                f"⏳ <b>Corner 1 Selected:</b> <code>({c1[0]:.4f}°, {c1[1]:.4f}°)</code><br>"
                f"Click a second location on the map to complete the two-point bounding box."
                f"</div>",
                unsafe_allow_html=True
            )
        else:
            plat, plng = st.session_state.selected_points[0]
            st.markdown(
                f"<div class='geo-status-box'>"
                f"📍 <b>Location Attached:</b> <code>({plat:.4f}°, {plng:.4f}°)</code><br>"
                f"Enter your question below to query intelligence for this coordinate."
                f"</div>",
                unsafe_allow_html=True
            )

        col_c1, col_c2 = st.columns(2)
        with col_c1:
            clear_btn_label = "❌ Clear Box" if is_bbox_mode and st.session_state.get("bounding_box") else "❌ Clear Point"
            if st.button(clear_btn_label, key="clear_chat_pts", use_container_width=True):
                st.session_state.selected_points = []
                st.session_state.bounding_box = None
                st.session_state.active_point = None
                st.session_state.last_clicked = None
                st.rerun()
        with col_c2:
            if st.button("🔍 Run Reconnaissance", key="run_chat_recon", use_container_width=True):
                is_bbox = is_bbox_mode and (st.session_state.get("bounding_box") is not None)
                active_pt = None if is_bbox else (st.session_state.selected_points[0] if st.session_state.get("selected_points") else None)
                active_bbox = st.session_state.get("bounding_box") if is_bbox else None

                recon_resp = query_geo_agent(
                    text_prompt=None,
                    selected_point=active_pt,
                    bounding_box=active_bbox,
                    chat_history=st.session_state.messages
                )
                if is_bbox_mode and st.session_state.get("bounding_box"):
                    b_ll, b_ur = st.session_state.bounding_box
                    user_msg = f"Reconnaissance requested for bounding box: Lower-Left ({b_ll[0]:.4f}°, {b_ll[1]:.4f}°), Upper-Right ({b_ur[0]:.4f}°, {b_ur[1]:.4f}°)"
                else:
                    plat, plng = st.session_state.selected_points[0]
                    user_msg = f"Reconnaissance requested for coordinate: ({plat:.4f}°, {plng:.4f}°)"

                st.session_state.messages.append({"role": "user", "content": user_msg})
                st.session_state.messages.append({"role": "assistant", "content": recon_resp.answer})
                st.session_state.map_layers.extend(recon_resp.layers)
                if not st.session_state.get("keep_points", False):
                    st.session_state.selected_points = []
                    st.session_state.bounding_box = None
                    st.session_state.active_point = None
                st.rerun()

    # Render conversational message history inside a dedicated scroll container with its own scrollbar
    chat_container_height = 360 if st.session_state.selected_points else 450
    chat_container = st.container(height=chat_container_height)
    with chat_container:
        for msg in st.session_state.messages:
            role = msg["role"]
            avatar = t_cfg["user_avatar"] if role == "user" else t_cfg["ai_avatar"]
            role_tag = t_cfg["operator_tag"] if role == "user" else t_cfg["ai_tag"]
            with st.chat_message(role, avatar=avatar):
                st.markdown(f"<div class='chat-role-tag'>{role_tag}</div>", unsafe_allow_html=True)
                st.markdown(msg["content"])

    # Chat input box for user queries
    user_prompt = st.chat_input("Type a question (e.g. 'What units are stationed here?')...")

    if user_prompt:
        # 1. Append user's message to chat history
        st.session_state.messages.append({"role": "user", "content": user_prompt})

        # 2. Invoke the mock GeoAI agent router with text, selected_point, and bounding_box
        is_bbox = (st.session_state.get("selection_mode") == "Bounding Box") and (st.session_state.get("bounding_box") is not None)
        active_pt = None if is_bbox else (st.session_state.selected_points[0] if st.session_state.get("selected_points") else None)
        active_bbox = st.session_state.get("bounding_box") if is_bbox else None

        agent_resp: AgentResponse = query_geo_agent(
            text_prompt=user_prompt,
            selected_point=active_pt,
            bounding_box=active_bbox,
            chat_history=st.session_state.messages
        )

        # 3. Append assistant response and extend visual map layers
        st.session_state.messages.append({"role": "assistant", "content": agent_resp.answer})
        st.session_state.map_layers.extend(agent_resp.layers)

        # 4. Reset selected points unless user chose to retain them
        if not st.session_state.get("keep_points", False):
            st.session_state.selected_points = []
            st.session_state.bounding_box = None
            st.session_state.active_point = None

        # 5. Refresh application state to immediately display updates
        st.rerun()


# ------------------------------------------------------------------------------
# 6. Right Column: Folium Map Rendering & Click Interception
# ------------------------------------------------------------------------------
with col2:
    # Center coordinates of Ukraine: latitude ~48.3794, longitude ~31.1656
    ukraine_center = [48.3794, 31.1656]

    # Initialize the Folium Map instance without a default tile layer to prevent layer conflicts
    m = folium.Map(
        location=ukraine_center,
        zoom_start=6,
        tiles=None,
        control_scale=True
    )

    # CARTO API Key integration
    CARTO_API_KEY = "cb1_3wyp_1_6945a000f4bccf031f5aec03"

    # 1. Primary Dark Tactical Basemap: CartoDB Dark Matter (authenticated with CARTO key)
    folium.TileLayer(
        tiles=f"https://{{s}}.basemaps.cartocdn.com/rastertiles/dark_all/{{z}}/{{x}}/{{y}}.png?key={CARTO_API_KEY}",
        attr="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>",
        name="CartoDB Dark Matter (Tactical)",
        overlay=False,
        control=True,
        show=True
    ).add_to(m)

    # 2. CartoDB Voyager (Navigation Basemap authenticated with CARTO key)
    folium.TileLayer(
        tiles=f"https://{{s}}.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png?key={CARTO_API_KEY}",
        attr="&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a> contributors &copy; <a href='https://carto.com/attributions'>CARTO</a>",
        name="CartoDB Voyager (Nav)",
        overlay=False,
        control=True,
        show=False
    ).add_to(m)

    # 3. Esri World Dark Gray Canvas (Official Defense C2 dark basemap, 100% free, no key required)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, HERE, Garmin, FAO, NOAA, USGS, &copy; OpenStreetMap contributors",
        name="Esri Dark Gray Canvas",
        overlay=False,
        control=True,
        show=False
    ).add_to(m)

    # 4. High-resolution Satellite Imagery
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, Maxar, Earthstar Geographics, and the GIS User Community",
        name="Esri Satellite Imagery",
        overlay=False,
        control=True,
        show=False
    ).add_to(m)

    # 5. Topographic Basemap
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri, HERE, Garmin, Intermap, USGS, METI, OpenStreetMap contributors, and the GIS User Community",
        name="Esri Topographic",
        overlay=False,
        control=True,
        show=False
    ).add_to(m)

    # 6. OpenStreetMap (Standard Fallback)
    folium.TileLayer(
        tiles="OpenStreetMap",
        name="OpenStreetMap (Standard)",
        overlay=False,
        control=True,
        show=False
    ).add_to(m)

    # Render visually distinct marker(s) or bounding box for all currently selected points
    if st.session_state.get("selection_mode", "Bounding Box") == "Bounding Box":
        if st.session_state.get("bounding_box"):
            b_ll, b_ur = st.session_state.bounding_box
            # 1. Lower-Left (SW) Marker
            folium.Marker(
                location=[b_ll[0], b_ll[1]],
                tooltip=f"★ Bounding Box Lower-Left (SW): {b_ll[0]:.4f}°, {b_ll[1]:.4f}°",
                popup=folium.Popup(
                    f"<div style='font-family:monospace; background-color:{t_cfg['bg_card']}; "
                    f"color:{t_cfg['primary']}; padding:8px; border:1px solid {t_cfg['border_card']}; border-radius:4px;'>"
                    f"<b>★ BBOX LOWER-LEFT (SW)</b><br>"
                    f"LAT: <code>{b_ll[0]:.5f}°</code><br>"
                    f"LNG: <code>{b_ll[1]:.5f}°</code><br>"
                    f"<span style='color:{t_cfg['text_dim']}; font-size:0.8rem;'>Protocol: {t_cfg['name']}</span>"
                    f"</div>",
                    max_width=250
                ),
                icon=folium.Icon(color=t_cfg["folium_marker_color"], icon="arrow-down", prefix="glyphicon")
            ).add_to(m)

            # 2. Upper-Right (NE) Marker
            folium.Marker(
                location=[b_ur[0], b_ur[1]],
                tooltip=f"★ Bounding Box Upper-Right (NE): {b_ur[0]:.4f}°, {b_ur[1]:.4f}°",
                popup=folium.Popup(
                    f"<div style='font-family:monospace; background-color:{t_cfg['bg_card']}; "
                    f"color:{t_cfg['primary']}; padding:8px; border:1px solid {t_cfg['border_card']}; border-radius:4px;'>"
                    f"<b>★ BBOX UPPER-RIGHT (NE)</b><br>"
                    f"LAT: <code>{b_ur[0]:.5f}°</code><br>"
                    f"LNG: <code>{b_ur[1]:.5f}°</code><br>"
                    f"<span style='color:{t_cfg['text_dim']}; font-size:0.8rem;'>Protocol: {t_cfg['name']}</span>"
                    f"</div>",
                    max_width=250
                ),
                icon=folium.Icon(color=t_cfg["folium_marker_color"], icon="arrow-up", prefix="glyphicon")
            ).add_to(m)

            # 3. Visual Tactical Bounding Box Rectangle
            folium.Rectangle(
                bounds=[[b_ll[0], b_ll[1]], [b_ur[0], b_ur[1]]],
                color=t_cfg["primary"],
                weight=2,
                dash_array="6, 6",
                fill=True,
                fill_color=t_cfg["primary"],
                fill_opacity=0.18,
                tooltip=f"★ Bounding Box: [{b_ll[0]:.4f}°, {b_ll[1]:.4f}°] to [{b_ur[0]:.4f}°, {b_ur[1]:.4f}°]",
                popup=folium.Popup(
                    f"<div style='font-family:monospace; background-color:{t_cfg['bg_card']}; "
                    f"color:{t_cfg['primary']}; padding:8px; border:1px solid {t_cfg['border_card']}; border-radius:4px;'>"
                    f"<b>★ TWO-POINT BOUNDING BOX</b><br>"
                    f"<b>Lower-Left (SW):</b> <code>{b_ll[0]:.4f}°, {b_ll[1]:.4f}°</code><br>"
                    f"<b>Upper-Right (NE):</b> <code>{b_ur[0]:.4f}°, {b_ur[1]:.4f}°</code><br>"
                    f"<span style='color:{t_cfg['text_dim']}; font-size:0.8rem;'>Ready for tactical query</span>"
                    f"</div>",
                    max_width=260
                )
            ).add_to(m)

        elif len(st.session_state.selected_points) == 1:
            c_lat, c_lng = st.session_state.selected_points[0]
            folium.Marker(
                location=[c_lat, c_lng],
                tooltip=f"★ Corner 1 ({c_lat:.4f}°, {c_lng:.4f}°) - Click 2nd point to complete box",
                popup=folium.Popup(
                    f"<div style='font-family:monospace; background-color:{t_cfg['bg_card']}; "
                    f"color:{t_cfg['primary']}; padding:8px; border:1px solid {t_cfg['border_card']}; border-radius:4px;'>"
                    f"<b>★ BBOX CORNER 1 (Pending)</b><br>"
                    f"LAT: <code>{c_lat:.5f}°</code><br>"
                    f"LNG: <code>{c_lng:.5f}°</code><br>"
                    f"<span style='color:{t_cfg['text_dim']}; font-size:0.8rem;'>Click 2nd location to complete box</span>"
                    f"</div>",
                    max_width=250
                ),
                icon=folium.Icon(color="orange", icon="screenshot", prefix="glyphicon")
            ).add_to(m)

    else:
        # Standard marker rendering for Point Selection mode
        if st.session_state.selected_points:
            s_lat, s_lng = st.session_state.selected_points[0]
            popup_html = (
                f"<div style='font-family:monospace; background-color:{t_cfg['bg_card']}; "
                f"color:{t_cfg['primary']}; padding:8px; border:1px solid {t_cfg['border_card']}; border-radius:4px;'>"
                f"<b>★ TARGET POINT</b><br>"
                f"LAT: <code>{s_lat:.5f}°</code><br>"
                f"LNG: <code>{s_lng:.5f}°</code><br>"
                f"<span style='color:{t_cfg['text_dim']}; font-size:0.8rem;'>Protocol: {t_cfg['name']}</span>"
                f"</div>"
            )
            folium.Marker(
                location=[s_lat, s_lng],
                tooltip=f"★ Target Point ({s_lat:.4f}°, {s_lng:.4f}°)",
                popup=folium.Popup(popup_html, max_width=250),
                icon=folium.Icon(color=t_cfg["folium_marker_color"], icon=t_cfg["folium_marker_icon"], prefix="glyphicon")
            ).add_to(m)

    # Render all persistent MapLayer objects from session state
    for layer in st.session_state.map_layers:
        try:
            if layer.layer_type == "marker":
                folium.Marker(
                    location=[layer.data["lat"], layer.data["lng"]],
                    tooltip=layer.tooltip or layer.name,
                    popup=folium.Popup(layer.popup or layer.name, max_width=300),
                    icon=folium.Icon(color=layer.color, icon="info-sign", prefix="glyphicon")
                ).add_to(m)

            elif layer.layer_type == "circle":
                folium.Circle(
                    location=[layer.data["lat"], layer.data["lng"]],
                    radius=layer.data.get("radius", 10000),
                    color=layer.color,
                    fill=True,
                    fill_opacity=0.25,
                    tooltip=layer.tooltip or layer.name,
                    popup=folium.Popup(layer.popup or layer.name, max_width=300)
                ).add_to(m)

            elif layer.layer_type == "polygon":
                folium.Polygon(
                    locations=layer.data.get("coordinates", []),
                    color=layer.color,
                    fill=True,
                    fill_opacity=0.3,
                    tooltip=layer.tooltip or layer.name,
                    popup=folium.Popup(layer.popup or layer.name, max_width=300)
                ).add_to(m)

            elif layer.layer_type in ["rectangle", "box"]:
                folium.Rectangle(
                    bounds=layer.data.get("bounds", layer.data.get("coordinates", [])),
                    color=layer.color,
                    fill=True,
                    fill_opacity=layer.data.get("fill_opacity", 0.25),
                    tooltip=layer.tooltip or layer.name,
                    popup=folium.Popup(layer.popup or layer.name, max_width=300)
                ).add_to(m)

        except Exception as render_err:
            # Prevent map crash if individual layer data is malformed
            print(f"[Map Render Warning] Could not render layer '{layer.name}': {render_err}")

    # Add layer switcher control
    folium.LayerControl(position="topright").add_to(m)

    # Render the interactive map component inside Streamlit
    # Uses return_on_hover=False as specified in the project requirements
    map_data = st_folium(
        m,
        height=520,
        use_container_width=True,
        return_on_hover=False
    )

    # --------------------------------------------------------------------------
    # Click Interception (Selection ONLY - NO immediate backend call)
    # --------------------------------------------------------------------------
    clicked_data = map_data.get("last_clicked") if map_data else None

    if clicked_data and "lat" in clicked_data and "lng" in clicked_data:
        # Round coordinates to 5 decimal places (~1.1 meter precision)
        clicked_coord = (round(clicked_data["lat"], 5), round(clicked_data["lng"], 5))

        # Check if this click is newly registered (different from last_clicked)
        if clicked_coord != st.session_state.last_clicked:
            st.session_state.last_clicked = clicked_coord

            current_mode = st.session_state.get("selection_mode", "Bounding Box")

            # Update selected points according to selection mode
            if current_mode == "Point Selection":
                # Cancels previous selection and selects the new coordinate
                st.session_state.selected_points = [clicked_coord]
                st.session_state.bounding_box = None
                st.session_state.active_point = clicked_coord

            else:  # "Bounding Box" mode (default)
                if len(st.session_state.selected_points) != 1:
                    # First corner of a new bounding box (cancels previous box)
                    st.session_state.selected_points = [clicked_coord]
                    st.session_state.bounding_box = None
                    st.session_state.active_point = clicked_coord
                else:
                    # Second corner: calculate and save lower-left and upper-right
                    pt1 = st.session_state.selected_points[0]
                    pt2 = clicked_coord
                    lower_left, upper_right = to_bounding_box(pt1, pt2)
                    st.session_state.selected_points = [lower_left, upper_right]
                    st.session_state.bounding_box = (lower_left, upper_right)
                    st.session_state.active_point = upper_right

            # Rerun to display selection marker on map immediately WITHOUT calling backend agent
            st.rerun()


# ==============================================================================
# 7. Direct CLI Launcher Support
# ==============================================================================
# If a team member executes `python app.py` instead of `streamlit run app.py`,
# forward execution directly to the Streamlit CLI automatically.
if __name__ == "__main__":
    try:
        from streamlit.web import cli as stcli
        import streamlit.runtime as st_runtime

        if not st_runtime.exists():
            print("[GeoAI Runner] Detected direct python execution. Launching Streamlit web runtime...")
            sys.argv = ["streamlit", "run", sys.argv[0]]
            sys.exit(stcli.main())
    except Exception:
        pass
