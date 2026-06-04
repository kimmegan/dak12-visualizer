import streamlit as st
import pandas as pd
import numpy as np
from scipy.interpolate import interp1d
import plotly.graph_objects as go

st.set_page_config(page_title="DAK-12 Visualizer", layout="wide", page_icon="🔬")

st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }
    .stSidebar > div:first-child { padding-top: 1rem; }
    h1 { font-size: 1.6rem !important; }
</style>
""", unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data
def load_xlsx(file_bytes):
    import io
    xl = pd.ExcelFile(io.BytesIO(file_bytes))
    sheets = {}
    for sn in xl.sheet_names:
        raw = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sn, header=None)
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
        df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=sn, header=header_row)
        df.columns = [str(c).strip() for c in df.columns]
        df = df.dropna(subset=["f (MHz)"])
        df = df[pd.to_numeric(df["f (MHz)"], errors="coerce").notna()]
        df["f (MHz)"] = pd.to_numeric(df["f (MHz)"])
        df["ε'"]      = pd.to_numeric(df["ε'"],      errors="coerce")
        df["σ (S/m)"] = pd.to_numeric(df["σ (S/m)"], errors="coerce")
        df = df.sort_values("f (MHz)").reset_index(drop=True)
        sheets[sn] = {"name": label, "df": df}
    return sheets

COLORS = [
    "#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
    "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf",
]

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
        st.markdown("**Sheets / Buffers**")
        selected_keys = []
        for k in sheet_keys:
            if st.checkbox(f"{k}: {sheets[k]['name']}", value=False, key=f"cb_{k}"):
                selected_keys.append(k)

        st.divider()
        st.markdown("**Legend Names**")
        legend_names = {}
        for k in sheet_keys:
            legend_names[k] = st.text_input(k, value=sheets[k]["name"],
                                             key=f"leg_{k}", label_visibility="collapsed")

        st.divider()
        st.markdown("**Frequency Markers**")
        marker_input = st.text_input("Add frequency (MHz) — comma-separated",
                                     placeholder="e.g. 21.33, 63.86, 127.7")
        marker_freqs = []
        if marker_input.strip():
            for part in marker_input.split(","):
                try:
                    marker_freqs.append(float(part.strip()))
                except ValueError:
                    pass

        st.divider()
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

        def parse_lim(v):
            try:
                return float(v.strip())
            except Exception:
                return None

    else:
        sheets = {}
        selected_keys = []
        legend_names = {}
        marker_freqs = []

# ── Main plot area ────────────────────────────────────────────────────────────

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

    # ε' line (primary y)
    fig.add_trace(go.Scatter(
        x=freq, y=eps,
        name=f"{name} ε'",
        line=dict(color=color, width=2, dash="solid"),
        mode="lines",
        yaxis="y1",
        hovertemplate=(
            f"<b>{name} — ε'</b><br>"
            "Freq: %{x:.1f} MHz<br>"
            "ε': %{y:.4f}<extra></extra>"
        )
    ))

    # σ line (secondary y)
    fig.add_trace(go.Scatter(
        x=freq, y=sigma,
        name=f"{name} σ",
        line=dict(color=color, width=2, dash="dash"),
        mode="lines",
        yaxis="y2",
        hovertemplate=(
            f"<b>{name} — σ</b><br>"
            "Freq: %{x:.1f} MHz<br>"
            "σ: %{y:.6f} S/m<extra></extra>"
        )
    ))

    # markers
    if marker_freqs:
        f_eps   = interp1d(freq, eps,   kind="cubic", fill_value="extrapolate")
        f_sigma = interp1d(freq, sigma, kind="cubic", fill_value="extrapolate")
        valid_mf = [mf for mf in marker_freqs if freq.min() <= mf <= freq.max()]
        if valid_mf:
            ep_vals = [float(f_eps(mf))   for mf in valid_mf]
            sg_vals = [float(f_sigma(mf)) for mf in valid_mf]

            fig.add_trace(go.Scatter(
                x=valid_mf, y=ep_vals,
                mode="markers",
                marker=dict(color=color, size=9,
                            line=dict(color="#e65100", width=2)),
                name=f"{name} markers ε'",
                yaxis="y1",
                showlegend=False,
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    "Freq: %{x} MHz<br>"
                    "ε': %{y:.4f}<extra></extra>"
                )
            ))
            fig.add_trace(go.Scatter(
                x=valid_mf, y=sg_vals,
                mode="markers",
                marker=dict(color=color, size=8, symbol="diamond",
                            line=dict(color="#e65100", width=2)),
                name=f"{name} markers σ",
                yaxis="y2",
                showlegend=False,
                hovertemplate=(
                    f"<b>{name}</b><br>"
                    "Freq: %{x} MHz<br>"
                    "σ: %{y:.6f} S/m<extra></extra>"
                )
            ))

            for mf, ep_v, sg_v in zip(valid_mf, ep_vals, sg_vals):
                marker_table_rows.append({
                    "Buffer": name,
                    "Freq (MHz)": mf,
                    "ε'": round(ep_v, 4),
                    "σ (S/m)": round(sg_v, 6),
                })

# axis limits
x_lo = parse_lim(xmin);  x_hi = parse_lim(xmax)
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
        title="Permittivity (ε')",
        side="left",
        range=[y1_lo, y1_hi] if (y1_lo is not None and y1_hi is not None) else None,
        showgrid=True, gridcolor="#e0e0e0",
    ),
    yaxis2=dict(
        title="Conductivity σ (S/m)",
        overlaying="y",
        side="right",
        range=[y2_lo, y2_hi] if (y2_lo is not None and y2_hi is not None) else None,
        showgrid=False,
    ),
    plot_bgcolor="white",
    paper_bgcolor="white",
)

st.plotly_chart(fig, use_container_width=True)

# ── Export button (matplotlib re-render, no kaleido needed) ──────────────────

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
import io as _io

def build_export_png(selected_keys, sheets, legend_names, marker_freqs,
                     x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi):
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

    colors = ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd",
              "#8c564b","#e377c2","#7f7f7f","#bcbd22","#17becf"]
    sheet_keys = list(sheets.keys())
    handles = []
    for k in selected_keys:
        idx   = sheet_keys.index(k)
        color = colors[idx % len(colors)]
        df    = sheets[k]["df"]
        freq  = df["f (MHz)"].values
        eps   = df["ε'"].values
        sigma = df["σ (S/m)"].values
        name  = legend_names.get(k, k)
        ax1_ex.plot(freq, eps,   color=color, linewidth=1.8)
        ax2_ex.plot(freq, sigma, color=color, linewidth=1.8, linestyle="--")
        handles.append(Line2D([0],[0], color=color, lw=2, label=f"{name} ε'"))
        handles.append(Line2D([0],[0], color=color, lw=2, linestyle="--", label=f"{name} σ"))
        if marker_freqs:
            f_eps   = interp1d(freq, eps,   kind="cubic", fill_value="extrapolate")
            f_sigma = interp1d(freq, sigma, kind="cubic", fill_value="extrapolate")
            for mf in marker_freqs:
                if freq.min() <= mf <= freq.max():
                    ax1_ex.plot(mf, float(f_eps(mf)),   "o", color=color,
                                markeredgecolor="#e65100", markeredgewidth=1.5, markersize=7, zorder=6)
                    ax2_ex.plot(mf, float(f_sigma(mf)), "D", color=color,
                                markeredgecolor="#e65100", markeredgewidth=1.5, markersize=6, zorder=6)
    if x_lo is not None and x_hi is not None:
        ax1_ex.set_xlim(x_lo, x_hi)
    if y1_lo is not None and y1_hi is not None:
        ax1_ex.set_ylim(y1_lo, y1_hi)
    if y2_lo is not None and y2_hi is not None:
        ax2_ex.set_ylim(y2_lo, y2_hi)
    ax1_ex.legend(handles=handles, loc="upper right", fontsize=7.5,
                  framealpha=0.85, facecolor="white", edgecolor="#cccccc")
    buf = _io.BytesIO()
    fig_ex.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig_ex)
    buf.seek(0)
    return buf.read()

png_bytes = build_export_png(selected_keys, sheets, legend_names, marker_freqs,
                              x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi)
st.download_button("💾 Export Plot as PNG", data=png_bytes,
                   file_name="dak12_plot.png", mime="image/png")

# ── Marker table ──────────────────────────────────────────────────────────────

if marker_table_rows:
    st.divider()
    st.markdown("**Interpolated Values at Marked Frequencies**")
    st.dataframe(pd.DataFrame(marker_table_rows), use_container_width=True, hide_index=True)
