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
        df = df.dropna(subset=["f (MHz)"])
        df = df[pd.to_numeric(df["f (MHz)"], errors="coerce").notna()]
        df["f (MHz)"] = pd.to_numeric(df["f (MHz)"])
        df["ε'"]      = pd.to_numeric(df["ε'"],      errors="coerce")
        df["σ (S/m)"] = pd.to_numeric(df["σ (S/m)"], errors="coerce")
        df = df.sort_values("f (MHz)").reset_index(drop=True)
        sheets[sn] = {"name": label, "df": df}
    return sheets

def parse_lim(v):
    try:
        return float(v.strip())
    except Exception:
        return None

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("🔬 DAK-12 Visualizer")
    st.caption("Dielectric Measurement Tool")
    st.divider()

    uploaded = st.file_uploader("Upload XLSX File", type=["xlsx", "xlsm"])

    if uploaded:
        sheets = load_xlsx(uploaded.read())
        sheet_keys = list(sheets.keys())

        st.divider()

        # ── Sheets / Buffers with per-row ε' and σ toggles ──────────────────
        st.markdown("**Sheets / Buffers**")

        # Header row
        hc0, hc1, hc2, hc3 = st.columns([3.2, 0.9, 0.9, 0.9])
        hc1.markdown("<div style='text-align:center;font-size:11px;font-weight:600'>Show</div>", unsafe_allow_html=True)
        hc2.markdown("<div style='text-align:center;font-size:11px;color:#1f77b4;font-weight:600'>ε'</div>", unsafe_allow_html=True)
        hc3.markdown("<div style='text-align:center;font-size:11px;color:#d62728;font-weight:600'>σ</div>", unsafe_allow_html=True)

        selected_keys  = []
        show_eps_map   = {}   # key -> bool
        show_sigma_map = {}   # key -> bool

        for k in sheet_keys:
            idx   = sheet_keys.index(k)
            color = COLORS[idx % len(COLORS)]
            name  = sheets[k]["name"]

            c0, c1, c2, c3 = st.columns([3.2, 0.9, 0.9, 0.9])
            with c0:
                # colour dot + label
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:6px;font-size:12px'>"
                    f"<span style='display:inline-block;width:10px;height:10px;"
                    f"border-radius:50%;background:{color};flex-shrink:0'></span>"
                    f"{k}: {name}</div>",
                    unsafe_allow_html=True)
            with c1:
                show = st.checkbox("", value=False, key=f"cb_{k}",
                                   label_visibility="collapsed")
            with c2:
                eps_on = st.checkbox("", value=True, key=f"eps_{k}",
                                     label_visibility="collapsed",
                                     disabled=not show)
            with c3:
                sig_on = st.checkbox("", value=True, key=f"sig_{k}",
                                     label_visibility="collapsed",
                                     disabled=not show)
            if show:
                selected_keys.append(k)
            show_eps_map[k]   = show and eps_on
            show_sigma_map[k] = show and sig_on

        st.divider()

        # ── Legend names + order ─────────────────────────────────────────────
        st.markdown("**Legend Names & Order**")
        st.caption("Edit names · drag the ↕ number to reorder")

        # initialise order list in session state
        if "legend_order" not in st.session_state or \
                set(st.session_state.legend_order) != set(sheet_keys):
            st.session_state.legend_order = sheet_keys[:]

        legend_names = {}
        new_order    = []

        for k in sheet_keys:
            legend_names[k] = st.text_input(
                k, value=sheets[k]["name"],
                key=f"leg_{k}", label_visibility="collapsed")

        st.markdown("**Plot order** (1 = first in legend)")
        order_inputs = {}
        ocols = st.columns(2)
        for i, k in enumerate(sheet_keys):
            name  = legend_names.get(k, k)
            col   = ocols[i % 2]
            order_inputs[k] = col.number_input(
                name[:18], min_value=1, max_value=len(sheet_keys),
                value=i + 1, step=1, key=f"ord_{k}")

        # resolve order (sort by number, ties keep original order)
        sorted_keys = sorted(sheet_keys, key=lambda k: (order_inputs[k], sheet_keys.index(k)))
        # apply order only to selected keys
        selected_keys = [k for k in sorted_keys if k in selected_keys]

        st.divider()

        # ── Frequency markers ────────────────────────────────────────────────
        st.markdown("**Frequency Markers**")
        marker_input = st.text_input("Frequencies (MHz) — comma-separated",
                                     placeholder="e.g. 21.33, 63.86, 127.7")
        marker_freqs = []
        if marker_input.strip():
            for part in marker_input.split(","):
                try:
                    marker_freqs.append(float(part.strip()))
                except ValueError:
                    pass

        st.divider()

        # ── Axis limits ──────────────────────────────────────────────────────
        st.markdown("**Axis Limits**")
        col1, col2 = st.columns(2)
        with col1:
            xmin  = st.text_input("Freq Min (MHz)", value="10",   key="xmin")
            y1min = st.text_input("ε' Min",         value="auto", key="y1min")
            y2min = st.text_input("σ Min (S/m)",    value="auto", key="y2min")
        with col2:
            xmax  = st.text_input("Freq Max (MHz)", value="295",  key="xmax")
            y1max = st.text_input("ε' Max",         value="auto", key="y1max")
            y2max = st.text_input("σ Max (S/m)",    value="auto", key="y2max")

    else:
        sheets = {}
        sheet_keys = []
        selected_keys = []
        legend_names  = {}
        marker_freqs  = []
        show_eps_map  = {}
        show_sigma_map= {}

# ── Main plot ─────────────────────────────────────────────────────────────────

st.markdown("## DAK-12 Dielectric Measurements")

if not uploaded:
    st.info("👈 Upload a DAK-12 XLSX file in the sidebar to get started.")
    st.stop()

if not selected_keys:
    st.warning("Select at least one buffer in the sidebar to plot.")
    st.stop()

fig = go.Figure()
marker_table_rows = []

for k in selected_keys:
    idx   = sheet_keys.index(k)
    color = COLORS[idx % len(COLORS)]
    df    = sheets[k]["df"]
    freq  = df["f (MHz)"].values
    eps   = df["ε'"].values
    sigma = df["σ (S/m)"].values
    name  = legend_names.get(k, k)

    if show_eps_map.get(k):
        fig.add_trace(go.Scatter(
            x=freq, y=eps,
            name=f"{name} ε'",
            line=dict(color=color, width=2, dash="solid"),
            mode="lines", yaxis="y1",
            hovertemplate=(f"<b>{name} — ε'</b><br>Freq: %{{x:.1f}} MHz<br>ε': %{{y:.4f}}<extra></extra>")
        ))

    if show_sigma_map.get(k):
        fig.add_trace(go.Scatter(
            x=freq, y=sigma,
            name=f"{name} σ",
            line=dict(color=color, width=2, dash="dash"),
            mode="lines", yaxis="y2",
            hovertemplate=(f"<b>{name} — σ</b><br>Freq: %{{x:.1f}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>")
        ))

    if marker_freqs:
        f_eps_fn   = interp1d(freq, eps,   kind="cubic", fill_value="extrapolate")
        f_sigma_fn = interp1d(freq, sigma, kind="cubic", fill_value="extrapolate")
        valid_mf   = [mf for mf in marker_freqs if freq.min() <= mf <= freq.max()]
        if valid_mf:
            ep_vals = [float(f_eps_fn(mf))   for mf in valid_mf]
            sg_vals = [float(f_sigma_fn(mf)) for mf in valid_mf]
            if show_eps_map.get(k):
                fig.add_trace(go.Scatter(
                    x=valid_mf, y=ep_vals, mode="markers",
                    marker=dict(color=color, size=9, line=dict(color="#e65100", width=2)),
                    name=f"{name} markers ε'", yaxis="y1", showlegend=False,
                    hovertemplate=(f"<b>{name}</b><br>Freq: %{{x}} MHz<br>ε': %{{y:.4f}}<extra></extra>")
                ))
            if show_sigma_map.get(k):
                fig.add_trace(go.Scatter(
                    x=valid_mf, y=sg_vals, mode="markers",
                    marker=dict(color=color, size=8, symbol="diamond",
                                line=dict(color="#e65100", width=2)),
                    name=f"{name} markers σ", yaxis="y2", showlegend=False,
                    hovertemplate=(f"<b>{name}</b><br>Freq: %{{x}} MHz<br>σ: %{{y:.6f}} S/m<extra></extra>")
                ))
            for mf, ep_v, sg_v in zip(valid_mf, ep_vals, sg_vals):
                marker_table_rows.append({
                    "Buffer": name, "Freq (MHz)": mf,
                    "ε'": round(ep_v, 4), "σ (S/m)": round(sg_v, 6),
                })

x_lo  = parse_lim(xmin);  x_hi  = parse_lim(xmax)
y1_lo = parse_lim(y1min); y1_hi = parse_lim(y1max)
y2_lo = parse_lim(y2min); y2_hi = parse_lim(y2max)

fig.update_layout(
    template="plotly_white",
    height=580,
    margin=dict(l=60, r=80, t=30, b=60),
    hovermode="x unified",
    legend=dict(orientation="v", x=1.08, y=1,
                bgcolor="rgba(255,255,255,0.85)",
                bordercolor="#cccccc", borderwidth=1),
    xaxis=dict(
        title="Frequency (MHz)",
        range=[x_lo, x_hi] if (x_lo is not None and x_hi is not None) else None,
        showgrid=True, gridcolor="#e0e0e0",
    ),
    yaxis=dict(
        title="Permittivity (ε')", side="left",
        range=[y1_lo, y1_hi] if (y1_lo is not None and y1_hi is not None) else None,
        showgrid=True, gridcolor="#e0e0e0",
    ),
    yaxis2=dict(
        title="Conductivity σ (S/m)", overlaying="y", side="right",
        range=[y2_lo, y2_hi] if (y2_lo is not None and y2_hi is not None) else None,
        showgrid=False,
    ),
    plot_bgcolor="white", paper_bgcolor="white",
)

st.plotly_chart(fig, use_container_width=True)

# ── Export PNG ────────────────────────────────────────────────────────────────

def build_export_png(selected_keys, sheets, legend_names, show_eps_map, show_sigma_map,
                     marker_freqs, x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi):
    fig_ex, ax1_ex = plt.subplots(figsize=(12, 6), facecolor="white")
    fig_ex.subplots_adjust(left=0.08, right=0.88, top=0.92, bottom=0.10)
    ax2_ex = ax1_ex.twinx()
    for ax in [ax1_ex, ax2_ex]:
        ax.set_facecolor("white")
        ax.tick_params(labelsize=8)
        for spine in ax.spines.values():
            spine.set_edgecolor("#cccccc")
    ax1_ex.grid(True, color="#e0e0e0", linewidth=0.6, linestyle="--")
    ax1_ex.set_xlabel("Frequency (MHz)", fontsize=10)
    ax1_ex.set_ylabel("Permittivity (ε')", fontsize=10)
    ax2_ex.yaxis.set_label_position("right")
    ax2_ex.yaxis.tick_right()
    ax2_ex.set_ylabel("Conductivity σ (S/m)", fontsize=10)
    ax1_ex.set_title("DAK-12 Dielectric Measurements", fontsize=12, fontweight="bold", pad=8)
    colors = COLORS
    sk = list(sheets.keys())
    handles = []
    for k in selected_keys:
        color = colors[sk.index(k) % len(colors)]
        df    = sheets[k]["df"]
        freq  = df["f (MHz)"].values
        name  = legend_names.get(k, k)
        if show_eps_map.get(k):
            ax1_ex.plot(freq, df["ε'"].values, color=color, linewidth=1.8)
            handles.append(Line2D([0],[0], color=color, lw=2, label=f"{name} ε'"))
        if show_sigma_map.get(k):
            ax2_ex.plot(freq, df["σ (S/m)"].values, color=color, linewidth=1.8, linestyle="--")
            handles.append(Line2D([0],[0], color=color, lw=2, linestyle="--", label=f"{name} σ"))
        if marker_freqs:
            f_e = interp1d(freq, df["ε'"].values,      kind="cubic", fill_value="extrapolate")
            f_s = interp1d(freq, df["σ (S/m)"].values, kind="cubic", fill_value="extrapolate")
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
    if x_lo  is not None and x_hi  is not None: ax1_ex.set_xlim(x_lo,  x_hi)
    if y1_lo is not None and y1_hi is not None: ax1_ex.set_ylim(y1_lo, y1_hi)
    if y2_lo is not None and y2_hi is not None: ax2_ex.set_ylim(y2_lo, y2_hi)
    ax1_ex.legend(handles=handles, loc="upper right", fontsize=7.5,
                  framealpha=0.85, facecolor="white", edgecolor="#cccccc")
    buf = _io.BytesIO()
    fig_ex.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig_ex)
    buf.seek(0)
    return buf.read()

png_bytes = build_export_png(
    selected_keys, sheets, legend_names, show_eps_map, show_sigma_map,
    marker_freqs, x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi)
st.download_button("💾 Export Plot as PNG", data=png_bytes,
                   file_name="dak12_plot.png", mime="image/png")

# ── Marker table ──────────────────────────────────────────────────────────────

if marker_table_rows:
    st.divider()
    st.markdown("**Interpolated Values at Marked Frequencies**")
    st.dataframe(pd.DataFrame(marker_table_rows), use_container_width=True, hide_index=True)
