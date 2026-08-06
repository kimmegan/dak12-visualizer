import streamlit as st
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
import plotly.graph_objects as go
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import io as _io
import hashlib
import os
from datetime import datetime

st.set_page_config(page_title="DAK-12 Visualizer", layout="wide", page_icon="🔬")

st.markdown("""
<style>
.block-container { padding-top: 1.5rem; }
.stSidebar > div:first-child { padding-top: 1rem; }
h1 { font-size: 1.6rem !important; }
div[data-testid="column"] { padding: 0 4px; }
</style>
""", unsafe_allow_html=True)

COLORS = [
    "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
    "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf",
]

# ── Data loading ──────────────────────────────────────────────────────────────

def parse_date_cell(cell_value):
    """Parse a 'Date : 2026-Jun-08 10:07:49' style cell into a clean display string."""
    s = str(cell_value).strip()
    if not s.lower().startswith("date"):
        return None
    parts = s.split(":", 1)
    if len(parts) != 2:
        return None
    date_part = parts[1].strip()
    try:
        dt = datetime.strptime(date_part, "%Y-%b-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.strftime("%b %d, %Y · %I:%M %p")

@st.cache_data
def load_xlsx(file_bytes):
    xl = pd.ExcelFile(_io.BytesIO(file_bytes))
    sheets = {}
    
    for sn in xl.sheet_names:
        raw = pd.read_excel(_io.BytesIO(file_bytes), sheet_name=sn, header=None)
        label = sn
        
        for _, row in raw.iterrows():
            cell = str(row.iloc[0])
            if cell.strip().lower().startswith("name"):
                parts = cell.split(":", 1)
                if len(parts) == 2:
                    label = parts[1].strip()
                break
        
        date_str = None
        if raw.shape[0] > 1:
            date_str = parse_date_cell(raw.iloc[1, 0])
        
        header_row = None
        for i, row in raw.iterrows():
            if any("f (MHz)" in str(v) for v in row.values):
                header_row = i
                break
        
        if header_row is None:
            continue
        
        df = pd.read_excel(_io.BytesIO(file_bytes), sheet_name=sn, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        
        def find_col(df, candidates):
            for col in df.columns:
                col_n = col.lower().replace(" ", "").replace("'", "'").replace("'","'")
                for cand in candidates:
                    if cand.lower().replace(" ","") in col_n:
                        return col
            return None
        
        freq_col = find_col(df, ["f(mhz)", "freq"])
        eps_col = find_col(df, ["ε'", "e'", "eps", "permittivity", "epsilon", "ε"])
        sigma_col = find_col(df, ["σ(s/m)", "sigma", "conductivity", "s/m", "σ"])
        
        if not freq_col or not eps_col or not sigma_col:
            continue
        
        df = df.dropna(subset=[freq_col])
        df = df[pd.to_numeric(df[freq_col], errors="coerce").notna()]
        
        df["f (MHz)"] = pd.to_numeric(df[freq_col])
        df["eps"] = pd.to_numeric(df[eps_col], errors="coerce")
        df["sigma"] = pd.to_numeric(df[sigma_col], errors="coerce")
        
        df = df[["f (MHz)", "eps", "sigma"]].sort_values("f (MHz)").reset_index(drop=True)
        sheets[sn] = {"name": label, "df": df, "date_str": date_str}
    
    return sheets

def parse_lim(v):
    try:
        return float(str(v).strip())
    except Exception:
        return None

def parse_list(s):
    vals = []
    for part in s.split(","):
        v = parse_lim(part)
        if v is not None:
            vals.append(v)
    return vals

def get_file_id(file_obj):
    """Generate stable ID for uploaded file"""
    content = file_obj.read()
    file_obj.seek(0)
    return hashlib.md5(content).hexdigest()

def get_group_color(group_name):
    """Assign each replicate group its own distinct color based on group order."""
    names = list(st.session_state.groupings.keys())
    if group_name in names:
        return COLORS[names.index(group_name) % len(COLORS)]
    return COLORS[0]

# ── Initialize session state ──────────────────────────────────────────────────

if "loaded_files" not in st.session_state:
    st.session_state.loaded_files = {}

if "legend_order" not in st.session_state:
    st.session_state.legend_order = []

if "show_average_and_bands" not in st.session_state:
    st.session_state.show_average_and_bands = False

if "groupings" not in st.session_state:
    st.session_state.groupings = {}

if "group_names_editable" not in st.session_state:
    st.session_state.group_names_editable = {}

if "show_grouping_modal" not in st.session_state:
    st.session_state.show_grouping_modal = False

if "show_info_modal" not in st.session_state:
    st.session_state.show_info_modal = False

# Current sheet -> group mapping, computed once per run so both the sidebar
# (group-creation tree) and the main plot use the exact same, up-to-date view.
sheet_to_group = {}
for _group_name, _member_ids in st.session_state.groupings.items():
    for _full_id in _member_ids:
        sheet_to_group[_full_id] = _group_name

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔬 DAK-12 Visualizer")
    st.caption("Dielectric Measurement Tool")
    st.divider()
    
    # Multi-file upload
    st.markdown("**Upload XLSX Files**")
    uploaded_files = st.file_uploader("Upload one or more XLSX files", 
                                      type=["xlsx", "xlsm"], 
                                      accept_multiple_files=True)
    
    current_file_ids = set()
    
    if uploaded_files:
        for file_obj in uploaded_files:
            file_id = get_file_id(file_obj)
            current_file_ids.add(file_id)
            
            if file_id not in st.session_state.loaded_files:
                sheets_dict = load_xlsx(file_obj.read())
                
                # Date/time comes from row 2, column A of the first valid buffer sheet
                if sheets_dict:
                    first_sheet_key = list(sheets_dict.keys())[0]
                    file_date_str = sheets_dict[first_sheet_key].get("date_str") or "No date available"
                else:
                    file_date_str = "No date available"
                
                st.session_state.loaded_files[file_id] = {
                    "name": file_obj.name,
                    "sheets": list(sheets_dict.keys()),
                    "sheets_dict": sheets_dict,
                    "date_str": file_date_str,
                }
                
                for sheet_key in sheets_dict.keys():
                    full_id = f"{file_id}|{sheet_key}"
                    if full_id not in st.session_state.legend_order:
                        st.session_state.legend_order.append(full_id)
    
    # Remove files that are no longer uploaded
    files_to_remove = []
    for file_id in list(st.session_state.loaded_files.keys()):
        if file_id not in current_file_ids:
            files_to_remove.append(file_id)
    
    for file_id in files_to_remove:
        for sheet_key in st.session_state.loaded_files[file_id]["sheets"]:
            full_id = f"{file_id}|{sheet_key}"
            if full_id in st.session_state.legend_order:
                st.session_state.legend_order.remove(full_id)
            
            for group_name in list(st.session_state.groupings.keys()):
                if full_id in st.session_state.groupings[group_name]:
                    st.session_state.groupings[group_name].remove(full_id)
                    if not st.session_state.groupings[group_name]:
                        del st.session_state.groupings[group_name]
                        if group_name in st.session_state.group_names_editable:
                            del st.session_state.group_names_editable[group_name]
        
        del st.session_state.loaded_files[file_id]
    
    # Build name map with auto-numbering
    sheet_name_counts = {}
    for file_id, file_data in st.session_state.loaded_files.items():
        for sheet_key in file_data["sheets"]:
            sheet_name = file_data["sheets_dict"][sheet_key]["name"]
            if sheet_name not in sheet_name_counts:
                sheet_name_counts[sheet_name] = []
            sheet_name_counts[sheet_name].append((file_id, sheet_key))
    
    display_names = {}
    for sheet_name, ids_list in sheet_name_counts.items():
        if len(ids_list) == 1:
            display_names[f"{ids_list[0][0]}|{ids_list[0][1]}"] = sheet_name
        else:
            for idx, (file_id, sheet_key) in enumerate(ids_list, 1):
                display_names[f"{file_id}|{sheet_key}"] = f"{sheet_name} ({idx})"
    
    if st.session_state.loaded_files:
        st.divider()
    
    # Graph title
    st.markdown("**Graph Title**")
    graph_title = st.text_input("", value="DAK-12 Dielectric Measurements",
                                key="graph_title", label_visibility="collapsed")
    
    st.divider()
    
    # Sheets / Buffers
    st.markdown("**Sheets / Buffers**")
    st.caption("Show · ε' · σ")
    
    show_eps_map = {}
    show_sigma_map = {}
    
    for file_id, file_data in st.session_state.loaded_files.items():
        with st.expander(f"📁 {file_data['name']}", expanded=False):
            st.caption(f"🕒 {file_data.get('date_str', 'No date available')}")
            
            # "All ε'" and "All σ" buttons
            col_all_e, col_all_s = st.columns(2)
            
            def make_all_eps_cb(fid):
                def _cb():
                    for sk in st.session_state.loaded_files[fid]["sheets"]:
                        full_id = f"{fid}|{sk}"
                        st.session_state[f"eps_{full_id}"] = st.session_state.get(f"all_eps_{fid}", False)
                        if st.session_state[f"eps_{full_id}"]:
                            st.session_state[f"all_{full_id}"] = True
                return _cb
            
            def make_all_sig_cb(fid):
                def _cb():
                    for sk in st.session_state.loaded_files[fid]["sheets"]:
                        full_id = f"{fid}|{sk}"
                        st.session_state[f"sig_{full_id}"] = st.session_state.get(f"all_sig_{fid}", False)
                        if st.session_state[f"sig_{full_id}"]:
                            st.session_state[f"all_{full_id}"] = True
                return _cb
            
            with col_all_e:
                st.checkbox("All ε'", key=f"all_eps_{file_id}", 
                           on_change=make_all_eps_cb(file_id))
            
            with col_all_s:
                st.checkbox("All σ", key=f"all_sig_{file_id}",
                           on_change=make_all_sig_cb(file_id))
            
            st.divider()
            
            hc0, hc1, hc2, hc3 = st.columns([3.2, 0.7, 0.7, 0.7])
            hc1.markdown("<div style='text-align:center;font-size:10px;font-weight:600'>All</div>", unsafe_allow_html=True)
            hc2.markdown("<div style='text-align:center;font-size:10px;color:#1f77b4;font-weight:600'>ε'</div>", unsafe_allow_html=True)
            hc3.markdown("<div style='text-align:center;font-size:10px;color:#d62728;font-weight:600'>σ</div>", unsafe_allow_html=True)
            
            for sheet_key in file_data["sheets"]:
                full_id = f"{file_id}|{sheet_key}"
                for suffix in ["all", "eps", "sig"]:
                    if f"{suffix}_{full_id}" not in st.session_state:
                        st.session_state[f"{suffix}_{full_id}"] = False
            
            def make_master_cb(full_id):
                def _cb():
                    v = st.session_state[f"all_{full_id}"]
                    st.session_state[f"eps_{full_id}"] = v
                    st.session_state[f"sig_{full_id}"] = v
                return _cb
            
            for sheet_key in file_data["sheets"]:
                full_id = f"{file_id}|{sheet_key}"
                sheet_data = file_data["sheets_dict"][sheet_key]
                idx = list(st.session_state.loaded_files.keys()).index(file_id) * len(file_data["sheets"]) + file_data["sheets"].index(sheet_key)
                color = COLORS[idx % len(COLORS)]
                display_name = display_names.get(full_id, sheet_key)
                
                c0, c1, c2, c3 = st.columns([3.2, 0.7, 0.7, 0.7])
                
                with c0:
                    st.markdown(
                        f"<div style='display:flex;align-items:center;gap:5px;"
                        f"font-size:11px;padding-top:6px'>"
                        f"<span style='display:inline-block;width:9px;height:9px;"
                        f"border-radius:50%;background:{color};flex-shrink:0'></span>"
                        f"{display_name}</div>",
                        unsafe_allow_html=True)
                
                with c1:
                    st.checkbox("", key=f"all_{full_id}",
                               on_change=make_master_cb(full_id),
                               label_visibility="collapsed")
                
                with c2:
                    show_eps_map[full_id] = st.checkbox("", key=f"eps_{full_id}",
                                                        label_visibility="collapsed")
                
                with c3:
                    show_sigma_map[full_id] = st.checkbox("", key=f"sig_{full_id}",
                                                          label_visibility="collapsed")
    
    selected_keys = [k for k in st.session_state.legend_order
                    if k in show_eps_map or k in show_sigma_map
                    if show_eps_map.get(k) or show_sigma_map.get(k)]
    
    if st.session_state.loaded_files:
        st.divider()
    
    # Analysis options
    st.markdown("**Analysis**")
    
    show_average_and_bands = st.checkbox(
        "Average Selected Data & Show Error Bands (±SD)",
        value=st.session_state.show_average_and_bands,
        key="show_average_and_bands",
        help="When ON: calculates mean and SD across all selected sheets. When OFF: shows individual sheets."
    )
    
    if selected_keys:
        st.divider()
    
    # Grouping system
    st.markdown("**Replicate Groups**")
    
    if st.button("➕ New Group", use_container_width=True):
        # Clear any leftover selections/name from a previous group-creation
        # session so the modal always starts fresh (this was silently
        # overwriting earlier groups when a stale name was reused).
        for _k in list(st.session_state.keys()):
            if _k.startswith("gselect_") or _k == "new_group_name":
                del st.session_state[_k]
        st.session_state.show_grouping_modal = True
    
    if st.session_state.groupings:
        st.caption("Groups:")
        for group_name in list(st.session_state.groupings.keys()):
            member_ids = st.session_state.groupings[group_name]
            member_names = [display_names.get(fid, fid.split("|")[1]) for fid in member_ids]
            group_color = get_group_color(group_name)
            
            st.markdown(
                f"<div style='display:flex;align-items:center;gap:6px;margin-top:4px'>"
                f"<span style='display:inline-block;width:9px;height:9px;border-radius:50%;"
                f"background:{group_color};flex-shrink:0'></span>"
                f"<span style='font-size:10px;color:#888'>group color</span></div>",
                unsafe_allow_html=True)
            
            col_gname, col_gedit = st.columns([3, 0.5])
            
            with col_gname:
                display_gname = st.session_state.group_names_editable.get(group_name, group_name)
                new_gname = st.text_input(
                    f"Group name", value=display_gname,
                    key=f"group_name_{group_name}",
                    label_visibility="collapsed"
                )
                if new_gname != st.session_state.group_names_editable.get(group_name, group_name):
                    st.session_state.group_names_editable[group_name] = new_gname
            
            with col_gedit:
                if st.button("🗑️", key=f"del_group_{group_name}", help="Delete group"):
                    for fid in member_ids:
                        if fid in st.session_state.legend_order:
                            idx = st.session_state.legend_order.index(fid)
                            st.session_state.legend_order[idx] = fid
                    del st.session_state.groupings[group_name]
                    if group_name in st.session_state.group_names_editable:
                        del st.session_state.group_names_editable[group_name]
                    st.rerun()
            
            st.caption(f"{', '.join(member_names)}")
    
    if selected_keys:
        st.divider()
    
    # Grouping modal
    if st.session_state.show_grouping_modal:
        st.markdown("**Create New Group**")
        group_name_input = st.text_input("Group name", placeholder="e.g., 'Buffer 1 replicates'", key="new_group_name")
        
        st.markdown("Select sheets:")
        st.caption("Sheets already in another group aren't listed — remove them from that group first if you need to move them.")
        selected_for_group = {}
        
        assignable_full_ids = [fid for fid in selected_keys if fid not in sheet_to_group]
        
        for full_id in assignable_full_ids:
            if f"gselect_{full_id}" not in st.session_state:
                st.session_state[f"gselect_{full_id}"] = False
        
        def make_select_all_file_cb(fid, file_keys):
            def _cb():
                val = st.session_state.get(f"gselect_all_{fid}", False)
                for fk in file_keys:
                    st.session_state[f"gselect_{fk}"] = val
            return _cb
        
        for file_id, file_data in st.session_state.loaded_files.items():
            file_keys = [f"{file_id}|{sk}" for sk in file_data["sheets"] if f"{file_id}|{sk}" in assignable_full_ids]
            if not file_keys:
                continue
            
            with st.expander(f"📁 {file_data['name']}", expanded=False):
                if f"gselect_all_{file_id}" not in st.session_state:
                    st.session_state[f"gselect_all_{file_id}"] = False
                
                st.checkbox("Select all buffers in this file", key=f"gselect_all_{file_id}",
                           on_change=make_select_all_file_cb(file_id, file_keys))
                
                for full_id in file_keys:
                    display_name = display_names.get(full_id, full_id)
                    col_indent, col_check = st.columns([0.3, 3])
                    with col_check:
                        selected_for_group[full_id] = st.checkbox(
                            display_name, key=f"gselect_{full_id}")
        
        col_create, col_cancel = st.columns(2)
        with col_create:
            if st.button("Create", use_container_width=True):
                if not group_name_input or not any(selected_for_group.values()):
                    st.error("Enter group name and select sheets")
                elif group_name_input in st.session_state.groupings:
                    st.error(f"A group named '{group_name_input}' already exists — choose a different name.")
                else:
                    members = [fid for fid, selected in selected_for_group.items() if selected]
                    st.session_state.groupings[group_name_input] = members
                    st.session_state.group_names_editable[group_name_input] = group_name_input
                    st.session_state.show_grouping_modal = False
                    for _k in list(st.session_state.keys()):
                        if _k.startswith("gselect_") or _k == "new_group_name":
                            del st.session_state[_k]
                    st.rerun()
        
        with col_cancel:
            if st.button("Cancel", use_container_width=True):
                st.session_state.show_grouping_modal = False
                for _k in list(st.session_state.keys()):
                    if _k.startswith("gselect_") or _k == "new_group_name":
                        del st.session_state[_k]
                st.rerun()
    
    # Info modal
    if st.session_state.show_info_modal:
        with st.expander("ℹ️ Help & Information", expanded=True):
            st.markdown("""
**Select All Buttons**
- Toggle all ε' or σ for a single file

**Replicate Groups**
- Create groups to average specific subsets of sheets
- Example: "Buffer 1 replicates" (3 sheets) → shows as 1 mean line
- Grouped sheets don't appear individually on the plot
- Each group gets its own distinct color in the legend

**Average & Error Bands**
- Global toggle: average ALL selected sheets
- Shows ±1 standard deviation as shaded region

**Error Bands (±SD)**
- Auto-shown for replicate groups
- Shows uncertainty in the averaged data

**Legend**
- Customize names and reorder traces
- Use ▲ and ▼ buttons

**Frequency Markers**
- Enter comma-separated frequencies to interpolate values
- Results shown in table below plot

**File Info**
- Date/time is read from row 2, column A of the first buffer in each file
            """)
        
        if st.button("Close Help", use_container_width=True):
            st.session_state.show_info_modal = False
            st.rerun()
    
    if selected_keys:
        st.divider()
    
    # Legend names + order
    st.markdown("**Legend Names & Order**")
    
    def move_up(full_id):
        order = st.session_state["legend_order"]
        i = order.index(full_id)
        if i > 0:
            order[i], order[i-1] = order[i-1], order[i]
    
    def move_down(full_id):
        order = st.session_state["legend_order"]
        i = order.index(full_id)
        if i < len(order) - 1:
            order[i], order[i+1] = order[i+1], order[i]
    
    legend_names = {}
    for full_id in selected_keys:
        row = st.columns([3.2, 0.45, 0.45])
        
        display_name = display_names.get(full_id, full_id)
        
        with row[0]:
            legend_names[full_id] = st.text_input(
                full_id, value=display_name,
                key=f"leg_{full_id}", label_visibility="collapsed")
        
        with row[1]:
            st.button("▲", key=f"up_{full_id}",
                     on_click=move_up, args=(full_id,),
                     use_container_width=True)
        
        with row[2]:
            st.button("▼", key=f"dn_{full_id}",
                     on_click=move_down, args=(full_id,),
                     use_container_width=True)
    
    for full_id in st.session_state.legend_order:
        if full_id not in legend_names:
            display_name = display_names.get(full_id, full_id)
            legend_names[full_id] = display_name
    
    ordered_keys = st.session_state.legend_order
    selected_keys = [k for k in ordered_keys if k in selected_keys]
    
    if selected_keys:
        st.divider()
    
    # Frequency markers
    st.markdown("**Frequency Markers (x-axis)**")
    marker_input = st.text_input("Frequencies (MHz) — comma-separated",
                                placeholder="e.g. 21.33, 63.86",
                                key="xmarkers")
    marker_freqs = parse_list(marker_input)
    
    st.divider()
    
    # Y-axis markers
    st.markdown("**Y-Axis Markers (horizontal lines)**")
    eps_hline_input = st.text_input(
        "ε' values — comma-separated",
        placeholder="e.g. 78.5, 79.0", key="eps_hlines")
    sigma_hline_input = st.text_input(
        "σ values (S/m) — comma-separated",
        placeholder="e.g. 0.04, 0.05", key="sig_hlines")
    
    eps_hlines = parse_list(eps_hline_input)
    sigma_hlines = parse_list(sigma_hline_input)
    
    st.divider()
    
    # Axis limits
    st.markdown("**Axis Limits**")
    col1, col2 = st.columns(2)
    
    with col1:
        xmin = st.text_input("Freq Min (MHz)", value="10", key="xmin")
        y1min = st.text_input("ε' Min", value="auto", key="y1min")
        y2min = st.text_input("σ Min (S/m)", value="auto", key="y2min")
    
    with col2:
        xmax = st.text_input("Freq Max (MHz)", value="295", key="xmax")
        y1max = st.text_input("ε' Max", value="auto", key="y1max")
        y2max = st.text_input("σ Max (S/m)", value="auto", key="y2max")

# ── Main plot ─────────────────────────────────────────────────────────────────

plot_title = graph_title if st.session_state.loaded_files else "DAK-12 Dielectric Measurements"

st.markdown(f"## {plot_title}")

if not st.session_state.loaded_files:
    st.info("👈 Upload one or more DAK-12 XLSX files in the sidebar to get started.")
    st.stop()

if not selected_keys:
    st.warning("Select at least one ε' or σ toggle in the sidebar to plot.")
    st.stop()

x_lo = parse_lim(xmin); x_hi = parse_lim(xmax)
y1_lo = parse_lim(y1min); y1_hi = parse_lim(y1max)
y2_lo = parse_lim(y2min); y2_hi = parse_lim(y2max)

any_eps = any(show_eps_map.get(k) for k in selected_keys)
any_sigma = any(show_sigma_map.get(k) for k in selected_keys)

# ── Global averaging logic ────────────────────────────────────────────────────
# (sheet_to_group was already computed above, before the sidebar was rendered)

global_stats = None
if show_average_and_bands and selected_keys:
    dfs = []
    for full_id in selected_keys:
        if full_id not in sheet_to_group:
            file_id, sheet_key = full_id.split("|")
            df = st.session_state.loaded_files[file_id]["sheets_dict"][sheet_key]["df"]
            dfs.append(df)
    
    if dfs:
        freq = dfs[0]["f (MHz)"].values
        eps_vals = np.array([df["eps"].values for df in dfs])
        sigma_vals = np.array([df["sigma"].values for df in dfs])
        
        eps_mean = np.mean(eps_vals, axis=0)
        eps_sd = np.std(eps_vals, axis=0, ddof=1) if len(dfs) > 1 else np.zeros_like(eps_mean)
        
        sigma_mean = np.mean(sigma_vals, axis=0)
        sigma_sd = np.std(sigma_vals, axis=0, ddof=1) if len(dfs) > 1 else np.zeros_like(sigma_mean)
        
        global_stats = {
            "freq": freq,
            "eps_mean": eps_mean,
            "eps_sd": eps_sd,
            "sigma_mean": sigma_mean,
            "sigma_sd": sigma_sd,
        }

# ── Group statistics ──────────────────────────────────────────────────────────

group_stats = {}
for group_name, member_ids in st.session_state.groupings.items():
    dfs = []
    for full_id in member_ids:
        file_id, sheet_key = full_id.split("|")
        df = st.session_state.loaded_files[file_id]["sheets_dict"][sheet_key]["df"]
        dfs.append(df)
    
    if dfs:
        freq = dfs[0]["f (MHz)"].values
        eps_vals = np.array([df["eps"].values for df in dfs])
        sigma_vals = np.array([df["sigma"].values for df in dfs])
        
        eps_mean = np.mean(eps_vals, axis=0)
        eps_sd = np.std(eps_vals, axis=0, ddof=1) if len(dfs) > 1 else np.zeros_like(eps_mean)
        
        sigma_mean = np.mean(sigma_vals, axis=0)
        sigma_sd = np.std(sigma_vals, axis=0, ddof=1) if len(dfs) > 1 else np.zeros_like(sigma_mean)
        
        group_stats[group_name] = {
            "freq": freq,
            "eps_mean": eps_mean,
            "eps_sd": eps_sd,
            "sigma_mean": sigma_mean,
            "sigma_sd": sigma_sd,
        }

fig = go.Figure()

marker_table_rows = []

# If global averaging is ON, show only mean + error bands
if show_average_and_bands and global_stats:
    stats = global_stats
    
    mean_color = "#1f77b4"
    sigma_color = "#d62728"
    
    if any_eps:
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=stats["eps_mean"],
            name="Permittivity ε' (mean)",
            line=dict(color=mean_color, width=2.5, dash="solid"),
            mode="lines", yaxis="y1",
            hovertemplate=f"<b>ε' (mean)</b><br>Freq: %{{x:.1f}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
        ))
        
        upper_eps = stats["eps_mean"] + stats["eps_sd"]
        lower_eps = stats["eps_mean"] - stats["eps_sd"]
        
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=upper_eps,
            fill=None, mode="lines",
            line_color="rgba(255,255,255,0)",
            showlegend=False, hoverinfo="skip",
            yaxis="y1"
        ))
        
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=lower_eps,
            fill="tonexty", mode="lines",
            line_color="rgba(255,255,255,0)",
            fillcolor="rgba(31, 119, 180, 0.2)",
            name="ε' (±SD)",
            showlegend=True,
            yaxis="y1",
            hoverinfo="skip"
        ))
    
    if any_sigma:
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=stats["sigma_mean"],
            name="Conductivity σ (mean)",
            line=dict(color=sigma_color, width=2.5, dash="dash"),
            mode="lines", yaxis="y2",
            hovertemplate=f"<b>σ (mean)</b><br>Freq: %{{x:.1f}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
        ))
        
        upper_sigma = stats["sigma_mean"] + stats["sigma_sd"]
        lower_sigma = stats["sigma_mean"] - stats["sigma_sd"]
        
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=upper_sigma,
            fill=None, mode="lines",
            line_color="rgba(255,255,255,0)",
            showlegend=False, hoverinfo="skip",
            yaxis="y2"
        ))
        
        fig.add_trace(go.Scatter(
            x=stats["freq"], y=lower_sigma,
            fill="tonexty", mode="lines",
            line_color="rgba(255,255,255,0)",
            fillcolor="rgba(214, 39, 40, 0.2)",
            name="σ (±SD)",
            showlegend=True,
            yaxis="y2",
            hoverinfo="skip"
        ))
    
    if marker_freqs:
        f_eps_fn = interp1d(stats["freq"], stats["eps_mean"], kind="cubic", fill_value="extrapolate")
        f_sigma_fn = interp1d(stats["freq"], stats["sigma_mean"], kind="cubic", fill_value="extrapolate")
        f_eps_sd_fn = interp1d(stats["freq"], stats["eps_sd"], kind="cubic", fill_value="extrapolate")
        f_sigma_sd_fn = interp1d(stats["freq"], stats["sigma_sd"], kind="cubic", fill_value="extrapolate")
        
        valid_mf = [mf for mf in marker_freqs if stats["freq"].min() <= mf <= stats["freq"].max()]
        
        if valid_mf:
            ep_vals = [float(f_eps_fn(mf)) for mf in valid_mf]
            sg_vals = [float(f_sigma_fn(mf)) for mf in valid_mf]
            ep_sd_vals = [float(f_eps_sd_fn(mf)) for mf in valid_mf]
            sg_sd_vals = [float(f_sigma_sd_fn(mf)) for mf in valid_mf]
            
            if any_eps:
                fig.add_trace(go.Scatter(
                    x=valid_mf, y=ep_vals, mode="markers",
                    marker=dict(color=mean_color, size=9, line=dict(color="#e65100", width=2)),
                    yaxis="y1", showlegend=False,
                    hovertemplate=f"<b>ε' (mean)</b><br>Freq: %{{x}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
                ))
            
            if any_sigma:
                fig.add_trace(go.Scatter(
                    x=valid_mf, y=sg_vals, mode="markers",
                    marker=dict(color=sigma_color, size=8, symbol="diamond",
                               line=dict(color="#e65100", width=2)),
                    yaxis="y2", showlegend=False,
                    hovertemplate=f"<b>σ (mean)</b><br>Freq: %{{x}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
                ))
            
            for mf, ep_v, sg_v, ep_sd_v, sg_sd_v in zip(valid_mf, ep_vals, sg_vals, ep_sd_vals, sg_sd_vals):
                marker_table_rows.append({
                    "Buffer": "Mean (all selected)", "Freq (MHz)": mf,
                    "ε'": round(ep_v, 4), "ε' SD": round(ep_sd_v, 4),
                    "σ (S/m)": round(sg_v, 6), "σ SD": round(sg_sd_v, 6),
                })

else:
    # Show individual sheets (not in groups) and groups as means
    plotted_groups = set()
    
    for k in selected_keys:
        # If this sheet is in a group, plot the group instead
        if k in sheet_to_group:
            group_name = sheet_to_group[k]
            if group_name in plotted_groups:
                continue
            
            plotted_groups.add(group_name)
            stats = group_stats[group_name]
            
            display_name = st.session_state.group_names_editable.get(group_name, group_name)
            color = get_group_color(group_name)
            
            if any_eps:
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=stats["eps_mean"],
                    name=f"{display_name} ε'",
                    line=dict(color=color, width=2.5, dash="solid"),
                    mode="lines", yaxis="y1",
                    hovertemplate=f"<b>{display_name} ε'</b><br>Freq: %{{x:.1f}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
                ))
                
                upper = stats["eps_mean"] + stats["eps_sd"]
                lower = stats["eps_mean"] - stats["eps_sd"]
                
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=upper,
                    fill=None, mode="lines",
                    line_color="rgba(255,255,255,0)",
                    showlegend=False, hoverinfo="skip",
                    yaxis="y1"
                ))
                
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=lower,
                    fill="tonexty", mode="lines",
                    line_color="rgba(255,255,255,0)",
                    fillcolor=f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.2)",
                    showlegend=False,
                    yaxis="y1",
                    hoverinfo="skip"
                ))
            
            if any_sigma:
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=stats["sigma_mean"],
                    name=f"{display_name} σ",
                    line=dict(color=color, width=2.5, dash="dash"),
                    mode="lines", yaxis="y2",
                    hovertemplate=f"<b>{display_name} σ</b><br>Freq: %{{x:.1f}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
                ))
                
                upper = stats["sigma_mean"] + stats["sigma_sd"]
                lower = stats["sigma_mean"] - stats["sigma_sd"]
                
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=upper,
                    fill=None, mode="lines",
                    line_color="rgba(255,255,255,0)",
                    showlegend=False, hoverinfo="skip",
                    yaxis="y2"
                ))
                
                fig.add_trace(go.Scatter(
                    x=stats["freq"], y=lower,
                    fill="tonexty", mode="lines",
                    line_color="rgba(255,255,255,0)",
                    fillcolor=f"rgba({int(color[1:3], 16)}, {int(color[3:5], 16)}, {int(color[5:7], 16)}, 0.2)",
                    showlegend=False,
                    yaxis="y2",
                    hoverinfo="skip"
                ))
            
            if marker_freqs:
                f_eps_fn = interp1d(stats["freq"], stats["eps_mean"], kind="cubic", fill_value="extrapolate")
                f_sigma_fn = interp1d(stats["freq"], stats["sigma_mean"], kind="cubic", fill_value="extrapolate")
                f_eps_sd_fn = interp1d(stats["freq"], stats["eps_sd"], kind="cubic", fill_value="extrapolate")
                f_sigma_sd_fn = interp1d(stats["freq"], stats["sigma_sd"], kind="cubic", fill_value="extrapolate")
                
                valid_mf = [mf for mf in marker_freqs if stats["freq"].min() <= mf <= stats["freq"].max()]
                
                if valid_mf:
                    ep_vals = [float(f_eps_fn(mf)) for mf in valid_mf]
                    sg_vals = [float(f_sigma_fn(mf)) for mf in valid_mf]
                    ep_sd_vals = [float(f_eps_sd_fn(mf)) for mf in valid_mf]
                    sg_sd_vals = [float(f_sigma_sd_fn(mf)) for mf in valid_mf]
                    
                    if any_eps:
                        fig.add_trace(go.Scatter(
                            x=valid_mf, y=ep_vals, mode="markers",
                            marker=dict(color=color, size=9, line=dict(color="#e65100", width=2)),
                            yaxis="y1", showlegend=False,
                            hovertemplate=f"<b>{display_name}</b><br>Freq: %{{x}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
                        ))
                    
                    if any_sigma:
                        fig.add_trace(go.Scatter(
                            x=valid_mf, y=sg_vals, mode="markers",
                            marker=dict(color=color, size=8, symbol="diamond",
                                       line=dict(color="#e65100", width=2)),
                            yaxis="y2", showlegend=False,
                            hovertemplate=f"<b>{display_name}</b><br>Freq: %{{x}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
                        ))
                    
                    for mf, ep_v, sg_v, ep_sd_v, sg_sd_v in zip(valid_mf, ep_vals, sg_vals, ep_sd_vals, sg_sd_vals):
                        marker_table_rows.append({
                            "Buffer": display_name, "Freq (MHz)": mf,
                            "ε'": round(ep_v, 4), "ε' SD": round(ep_sd_v, 4),
                            "σ (S/m)": round(sg_v, 6), "σ SD": round(sg_sd_v, 6),
                        })
        
        else:
            # Not in a group, show individual sheet
            file_id, sheet_key = k.split("|")
            file_data = st.session_state.loaded_files[file_id]
            sheets_dict = file_data["sheets_dict"]
            
            all_keys_ever = list(st.session_state.legend_order)
            idx = all_keys_ever.index(k) if k in all_keys_ever else 0
            color = COLORS[idx % len(COLORS)]
            
            df = sheets_dict[sheet_key]["df"]
            freq = df["f (MHz)"].values
            eps = df["eps"].values
            sigma = df["sigma"].values
            
            name = legend_names.get(k, display_names.get(k, k))
            
            if show_eps_map.get(k):
                fig.add_trace(go.Scatter(
                    x=freq, y=eps,
                    name=f"{name} ε'",
                    line=dict(color=color, width=2, dash="solid"),
                    mode="lines", yaxis="y1",
                    hovertemplate=f"<b>{name} — ε'</b><br>Freq: %{{x:.1f}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
                ))
            
            if show_sigma_map.get(k):
                fig.add_trace(go.Scatter(
                    x=freq, y=sigma,
                    name=f"{name} σ",
                    line=dict(color=color, width=2, dash="dash"),
                    mode="lines", yaxis="y2",
                    hovertemplate=f"<b>{name} — σ</b><br>Freq: %{{x:.1f}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
                ))
            
            if marker_freqs:
                f_eps_fn = interp1d(freq, eps, kind="cubic", fill_value="extrapolate")
                f_sigma_fn = interp1d(freq, sigma, kind="cubic", fill_value="extrapolate")
                
                valid_mf = [mf for mf in marker_freqs if freq.min() <= mf <= freq.max()]
                
                if valid_mf:
                    ep_vals = [float(f_eps_fn(mf)) for mf in valid_mf]
                    sg_vals = [float(f_sigma_fn(mf)) for mf in valid_mf]
                    
                    if show_eps_map.get(k):
                        fig.add_trace(go.Scatter(
                            x=valid_mf, y=ep_vals, mode="markers",
                            marker=dict(color=color, size=9, line=dict(color="#e65100", width=2)),
                            yaxis="y1", showlegend=False,
                            hovertemplate=f"<b>{name}</b><br>Freq: %{{x}} MHz<br>ε': %{{y:.4f}}<extra></extra>"
                        ))
                    
                    if show_sigma_map.get(k):
                        fig.add_trace(go.Scatter(
                            x=valid_mf, y=sg_vals, mode="markers",
                            marker=dict(color=color, size=8, symbol="diamond",
                                       line=dict(color="#e65100", width=2)),
                            yaxis="y2", showlegend=False,
                            hovertemplate=f"<b>{name}</b><br>Freq: %{{x}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>"
                        ))
                    
                    for mf, ep_v, sg_v in zip(valid_mf, ep_vals, sg_vals):
                        marker_table_rows.append({
                            "Buffer": name, "Freq (MHz)": mf,
                            "ε'": round(ep_v, 4), "ε' SD": "N/A",
                            "σ (S/m)": round(sg_v, 6), "σ SD": "N/A",
                        })

if not any_eps and any_sigma:
    df0 = st.session_state.loaded_files[list(st.session_state.loaded_files.keys())[0]]["sheets_dict"][st.session_state.loaded_files[list(st.session_state.loaded_files.keys())[0]]["sheets"][0]]["df"]
    fig.add_trace(go.Scatter(
        x=df0["f (MHz)"].values, y=[None]*len(df0),
        yaxis="y1", showlegend=False, hoverinfo="skip",
        line=dict(width=0)
    ))

# ── Horizontal y-axis markers ─────────────────────────────────────────────────

hline_shapes = []
hline_annotations = []

for val in eps_hlines:
    hline_shapes.append(dict(
        type="line", xref="paper", x0=0, x1=1,
        yref="y", y0=val, y1=val,
        line=dict(color="#1f77b4", width=1.2, dash="dot")
    ))
    hline_annotations.append(dict(
        xref="paper", x=0, yref="y", y=val,
        text=f"ε'={val}", showarrow=False,
        font=dict(size=10, color="#1f77b4"),
        xanchor="left", yanchor="bottom"
    ))

for val in sigma_hlines:
    hline_shapes.append(dict(
        type="line", xref="paper", x0=0, x1=1,
        yref="y2", y0=val, y1=val,
        line=dict(color="#d62728", width=1.2, dash="dot")
    ))
    hline_annotations.append(dict(
        xref="paper", x=1, yref="y2", y=val,
        text=f"σ={val}", showarrow=False,
        font=dict(size=10, color="#d62728"),
        xanchor="right", yanchor="bottom"
    ))

fig.update_layout(
    template="plotly_white",
    height=580,
    margin=dict(l=60, r=80, t=50, b=60),
    hovermode="x unified",
    title=dict(text=plot_title, x=0.5, xanchor="center", font=dict(size=16)),
    legend=dict(orientation="v", x=1.08, y=1,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#cccccc", borderwidth=1),
    shapes=hline_shapes,
    annotations=hline_annotations,
    xaxis=dict(
        title="Frequency (MHz)",
        range=[x_lo, x_hi] if (x_lo is not None and x_hi is not None) else None,
        showgrid=True, gridcolor="#e0e0e0",
    ),
    yaxis=dict(
        title="Permittivity ε'" if any_eps else "",
        side="left",
        range=[y1_lo, y1_hi] if (y1_lo is not None and y1_hi is not None) else None,
        showgrid=True, gridcolor="#e0e0e0",
        showticklabels=any_eps,
    ),
    yaxis2=dict(
        title="Conductivity σ (S/m)" if any_sigma else "",
        overlaying="y", side="right",
        range=[y2_lo, y2_hi] if (y2_lo is not None and y2_hi is not None) else None,
        showgrid=False,
        showticklabels=any_sigma,
    ),
    plot_bgcolor="white", paper_bgcolor="white",
)

st.plotly_chart(fig, use_container_width=True)

# ── Export PNG ────────────────────────────────────────────────────────────────

def build_export_png(selected_keys, st_session, legend_names, display_names,
                    show_eps_map, show_sigma_map,
                    marker_freqs, eps_hlines, sigma_hlines,
                    any_eps, any_sigma, plot_title,
                    x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi,
                    global_stats, show_average_and_bands, sheet_to_group, group_stats, group_names_editable):
    
    group_name_list = list(st_session.groupings.keys())
    
    fig_ex, ax1_ex = plt.subplots(figsize=(12, 6), facecolor="white")
    fig_ex.subplots_adjust(left=0.09, right=0.88, top=0.92, bottom=0.10)
    
    ax2_ex = ax1_ex.twinx()
    
    for ax in [ax1_ex, ax2_ex]:
        ax.set_facecolor("white")
        ax.tick_params(labelsize=9)
        for sp in ax.spines.values():
            sp.set_edgecolor("#cccccc")
    
    ax1_ex.grid(True, color="#e0e0e0", linewidth=0.6, linestyle="--")
    ax1_ex.set_xlabel("Frequency (MHz)", fontsize=10)
    ax1_ex.set_ylabel("Permittivity ε'" if any_eps else "", fontsize=10)
    if not any_eps:
        ax1_ex.set_yticks([])
    
    ax2_ex.yaxis.set_label_position("right")
    ax2_ex.yaxis.tick_right()
    ax2_ex.set_ylabel("Conductivity σ (S/m)" if any_sigma else "", fontsize=10)
    if not any_sigma:
        ax2_ex.set_yticks([])
    
    ax1_ex.set_title(plot_title, fontsize=12, fontweight="bold", pad=8)
    
    handles = []
    
    if show_average_and_bands and global_stats:
        stats = global_stats
        mean_color = "#1f77b4"
        sigma_color = "#d62728"
        
        if any_eps:
            ax1_ex.plot(stats["freq"], stats["eps_mean"], color=mean_color, linewidth=1.8)
            handles.append(Line2D([0],[0], color=mean_color, lw=2, label="ε' (mean)"))
            
            upper = stats["eps_mean"] + stats["eps_sd"]
            lower = stats["eps_mean"] - stats["eps_sd"]
            ax1_ex.fill_between(stats["freq"], lower, upper, color=mean_color, alpha=0.2)
        
        if any_sigma:
            ax2_ex.plot(stats["freq"], stats["sigma_mean"], color=sigma_color, lw=1.8, linestyle="--")
            handles.append(Line2D([0],[0], color=sigma_color, lw=2, linestyle="--", label="σ (mean)"))
            
            upper = stats["sigma_mean"] + stats["sigma_sd"]
            lower = stats["sigma_mean"] - stats["sigma_sd"]
            ax2_ex.fill_between(stats["freq"], lower, upper, color=sigma_color, alpha=0.2)
    
    else:
        plotted_groups = set()
        
        for k in selected_keys:
            if k in sheet_to_group:
                group_name = sheet_to_group[k]
                if group_name in plotted_groups:
                    continue
                
                plotted_groups.add(group_name)
                stats = group_stats[group_name]
                
                color = COLORS[group_name_list.index(group_name) % len(COLORS)] if group_name in group_name_list else COLORS[0]
                
                display_name = group_names_editable.get(group_name, group_name)
                
                if any_eps:
                    ax1_ex.plot(stats["freq"], stats["eps_mean"], color=color, linewidth=1.8)
                    handles.append(Line2D([0],[0], color=color, lw=2, label=f"{display_name} ε'"))
                    
                    upper = stats["eps_mean"] + stats["eps_sd"]
                    lower = stats["eps_mean"] - stats["eps_sd"]
                    ax1_ex.fill_between(stats["freq"], lower, upper, color=color, alpha=0.2)
                
                if any_sigma:
                    ax2_ex.plot(stats["freq"], stats["sigma_mean"], color=color, lw=1.8, linestyle="--")
                    handles.append(Line2D([0],[0], color=color, lw=2, linestyle="--", label=f"{display_name} σ"))
                    
                    upper = stats["sigma_mean"] + stats["sigma_sd"]
                    lower = stats["sigma_mean"] - stats["sigma_sd"]
                    ax2_ex.fill_between(stats["freq"], lower, upper, color=color, alpha=0.2)
            
            else:
                file_id, sheet_key = k.split("|")
                file_data = st_session.loaded_files[file_id]
                sheets_dict = file_data["sheets_dict"]
                
                all_keys_ever = list(st_session.legend_order)
                idx = all_keys_ever.index(k) if k in all_keys_ever else 0
                color = COLORS[idx % len(COLORS)]
                
                df = sheets_dict[sheet_key]["df"]
                freq = df["f (MHz)"].values
                name = legend_names.get(k, display_names.get(k, k))
                
                if show_eps_map.get(k):
                    ax1_ex.plot(freq, df["eps"].values, color=color, linewidth=1.8)
                    handles.append(Line2D([0],[0], color=color, lw=2, label=f"{name} ε'"))
                
                if show_sigma_map.get(k):
                    ax2_ex.plot(freq, df["sigma"].values, color=color, lw=1.8, linestyle="--")
                    handles.append(Line2D([0],[0], color=color, lw=2, linestyle="--", label=f"{name} σ"))
    
    for val in eps_hlines:
        ax1_ex.axhline(val, color="#1f77b4", linewidth=1.2, linestyle=":")
        ax1_ex.text(0.01, val, f"ε'={val}", transform=ax1_ex.get_yaxis_transform(),
                   color="#1f77b4", fontsize=8, va="bottom")
    
    for val in sigma_hlines:
        ax2_ex.axhline(val, color="#d62728", linewidth=1.2, linestyle=":")
        ax2_ex.text(0.99, val, f"σ={val}", transform=ax2_ex.get_yaxis_transform(),
                   color="#d62728", fontsize=8, va="bottom", ha="right")
    
    if x_lo is not None and x_hi is not None: ax1_ex.set_xlim(x_lo, x_hi)
    if y1_lo is not None and y1_hi is not None: ax1_ex.set_ylim(y1_lo, y1_hi)
    if y2_lo is not None and y2_hi is not None: ax2_ex.set_ylim(y2_lo, y2_hi)
    
    if handles:
        ax1_ex.legend(handles=handles, loc="upper right", fontsize=8,
                     framealpha=0.9, facecolor="white", edgecolor="#cccccc")
    
    buf = _io.BytesIO()
    fig_ex.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig_ex)
    
    buf.seek(0)
    return buf.read()

png_bytes = build_export_png(
    selected_keys, st.session_state, legend_names, display_names,
    show_eps_map, show_sigma_map,
    marker_freqs, eps_hlines, sigma_hlines,
    any_eps, any_sigma, plot_title,
    x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi,
    global_stats, show_average_and_bands, sheet_to_group, group_stats, st.session_state.group_names_editable)

st.download_button("💾 Export Plot as PNG", data=png_bytes,
                  file_name=plot_title+".png", mime="image/png")

# Info modal at bottom
if st.session_state.show_info_modal:
    st.divider()
    with st.expander("ℹ️ Help & Information", expanded=True):
        st.markdown("""
**Select All Buttons**
- Toggle all ε' or σ for a single file

**Replicate Groups**
- Create groups to average specific subsets of sheets
- Example: "Buffer 1 replicates" (3 sheets) → shows as 1 mean line
- Grouped sheets don't appear individually on the plot
- Each group gets its own distinct color in the legend

**Average & Error Bands**
- Global toggle: average ALL selected sheets
- Shows ±1 standard deviation as shaded region

**Error Bands (±SD)**
- Auto-shown for replicate groups
- Shows uncertainty in the averaged data

**Legend**
- Customize names and reorder traces
- Use ▲ and ▼ buttons

**Frequency Markers**
- Enter comma-separated frequencies to interpolate values
- Results shown in table below plot

**File Info**
- Date/time is read from row 2, column A of the first buffer in each file
        """)

if marker_table_rows:
    st.divider()
    st.markdown("**Interpolated Values at Marked Frequencies**")
    st.caption("ε' SD / σ SD are only available for replicate groups and the global average (they need multiple sheets to compute a spread). Individual, ungrouped sheets show N/A.")
    
    marker_df = pd.DataFrame(marker_table_rows)
    st.dataframe(marker_df, use_container_width=True, hide_index=True)
    
    with st.expander("📋 Copy as table (tab-separated — paste into Excel/Sheets/Docs)"):
        tsv_text = marker_df.to_csv(sep="\t", index=False)
        st.code(tsv_text, language=None)
        st.caption("Hover the block above and click the copy icon in its top-right corner, then paste directly into a spreadsheet.")
