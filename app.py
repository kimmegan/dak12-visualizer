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
        sheets[sn] = {"name": label, "df": df}
    
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

# ── Initialize session state ──────────────────────────────────────────────────

if "loaded_files" not in st.session_state:
    st.session_state.loaded_files = {}

if "legend_order" not in st.session_state:
    st.session_state.legend_order = []

if "show_average_and_bands" not in st.session_state:
    st.session_state.show_average_and_bands = False

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
    
    # Process newly uploaded files
    if uploaded_files:
        for file_obj in uploaded_files:
            file_id = get_file_id(file_obj)
            
            if file_id not in st.session_state.loaded_files:
                sheets_dict = load_xlsx(file_obj.read())
                st.session_state.loaded_files[file_id] = {
                    "name": file_obj.name,
                    "sheets": list(sheets_dict.keys()),
                    "sheets_dict": sheets_dict,
                }
                
                for sheet_key in sheets_dict.keys():
                    full_id = f"{file_id}|{sheet_key}"
                    if full_id not in st.session_state.legend_order:
                        st.session_state.legend_order.append(full_id)
    
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
        with st.expander(f"📁 {file_data['name']}", expanded=True):
            
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

global_stats = None
if show_average_and_bands and selected_keys:
    dfs = []
    for full_id in selected_keys:
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

fig = go.Figure()

marker_table_rows = []

# If averaging is ON, show only mean + error bands
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
        
        valid_mf = [mf for mf in marker_freqs if stats["freq"].min() <= mf <= stats["freq"].max()]
        
        if valid_mf:
            ep_vals = [float(f_eps_fn(mf)) for mf in valid_mf]
            sg_vals = [float(f_sigma_fn(mf)) for mf in valid_mf]
            
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
            
            for mf, ep_v, sg_v in zip(valid_mf, ep_vals, sg_vals):
                marker_table_rows.append({
                    "Buffer": "Mean", "Freq (MHz)": mf,
                    "ε'": round(ep_v, 4), "σ (S/m)": round(sg_v, 6),
                })

else:
    for k in selected_keys:
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
                        "ε'": round(ep_v, 4), "σ (S/m)": round(sg_v, 6),
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
                    global_stats, show_average_and_bands):
    
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
        
        if marker_freqs:
            f_e = interp1d(stats["freq"], stats["eps_mean"], kind="cubic", fill_value="extrapolate")
            f_s = interp1d(stats["freq"], stats["sigma_mean"], kind="cubic", fill_value="extrapolate")
            
            for mf in marker_freqs:
                if stats["freq"].min() <= mf <= stats["freq"].max():
                    if any_eps:
                        ax1_ex.plot(mf, float(f_e(mf)), "o", color=mean_color,
                                   markeredgecolor="#e65100", markeredgewidth=1.5,
                                   markersize=7, zorder=6)
                    if any_sigma:
                        ax2_ex.plot(mf, float(f_s(mf)), "D", color=sigma_color,
                                   markeredgecolor="#e65100", markeredgewidth=1.5,
                                   markersize=6, zorder=6)
    
    else:
        for k in selected_keys:
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
            
            if marker_freqs:
                f_e = interp1d(freq, df["eps"].values, kind="cubic", fill_value="extrapolate")
                f_s = interp1d(freq, df["sigma"].values, kind="cubic", fill_value="extrapolate")
                
                for mf in marker_freqs:
                    if freq.min() <= mf <= freq.max():
                        if show_eps_map.get(k):
                            ax1_ex.plot(mf, float(f_e(mf)), "o", color=color,
                                       markeredgecolor="#e65100", markeredgewidth=1.5,
                                       markersize=7, zorder=6)
                        if show_sigma_map.get(k):
                            ax2_ex.plot(mf, float(f_s(mf)), "D", color=color,
                                       markeredgecolor="#e65100", markeredgewidth=1.5,
                                       markersize=6, zorder=6)
    
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
    global_stats, show_average_and_bands)

st.download_button("💾 Export Plot as PNG", data=png_bytes,
                  file_name=plot_title+".png", mime="image/png")

if marker_table_rows:
    st.divider()
    st.markdown("**Interpolated Values at Marked Frequencies**")
    st.dataframe(pd.DataFrame(marker_table_rows), use_container_width=True, hide_index=True)
