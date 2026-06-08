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

        # fuzzy column matching — handles unicode variations across platforms
        def find_col(df, candidates):
            for col in df.columns:
                col_n = col.lower().replace(" ", "").replace("'", "'").replace("'","'")
                for cand in candidates:
                    if cand.lower().replace(" ","") in col_n:
                        return col
            return None

        freq_col  = find_col(df, ["f(mhz)", "freq"])
        eps_col   = find_col(df, ["ε'", "e'", "eps", "permittivity", "epsilon", "ε"])
        sigma_col = find_col(df, ["σ(s/m)", "sigma", "conductivity", "s/m", "σ"])

        if not freq_col or not eps_col or not sigma_col:
            continue

        df = df.dropna(subset=[freq_col])
        df = df[pd.to_numeric(df[freq_col], errors="coerce").notna()]
        df["f (MHz)"] = pd.to_numeric(df[freq_col])
        df["eps"]     = pd.to_numeric(df[eps_col],   errors="coerce")
        df["sigma"]   = pd.to_numeric(df[sigma_col], errors="coerce")
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

        # ── Graph title ──────────────────────────────────────────────────────
        st.markdown("**Graph Title**")
        graph_title = st.text_input("", value="DAK-12 Dielectric Measurements",
                                    key="graph_title", label_visibility="collapsed")

        st.divider()

        # ── Sheets: 3 toggles (master | ε' | σ) ─────────────────────────────
        st.markdown("**Sheets / Buffers**")
        st.caption("Show · ε' · σ")

        hc0, hc1, hc2, hc3 = st.columns([3.2, 0.7, 0.7, 0.7])
        hc1.markdown("<div style='text-align:center;font-size:10px;font-weight:600'>All</div>", unsafe_allow_html=True)
        hc2.markdown("<div style='text-align:center;font-size:10px;color:#1f77b4;font-weight:600'>ε'</div>", unsafe_allow_html=True)
        hc3.markdown("<div style='text-align:center;font-size:10px;color:#d62728;font-weight:600'>σ</div>", unsafe_allow_html=True)

        show_eps_map   = {}
        show_sigma_map = {}

        for k in sheet_keys:
            idx   = sheet_keys.index(k)
            color = COLORS[idx % len(COLORS)]
            name  = sheets[k]["name"]
            c0, c1, c2, c3 = st.columns([3.2, 0.7, 0.7, 0.7])
            with c0:
                st.markdown(
                    f"<div style='display:flex;align-items:center;gap:5px;"
                    f"font-size:11px;padding-top:6px'>"
                    f"<span style='display:inline-block;width:9px;height:9px;"
                    f"border-radius:50%;background:{color};flex-shrink:0'></span>"
                    f"{k}: {name}</div>",
                    unsafe_allow_html=True)
            with c1:
                # master toggle — mirrors both ε' and σ
                master = st.checkbox("", value=False, key=f"all_{k}",
                                     label_visibility="collapsed")
            with c2:
                show_eps_map[k] = st.checkbox("", value=master, key=f"eps_{k}",
                                              label_visibility="collapsed")
            with c3:
                show_sigma_map[k] = st.checkbox("", value=master, key=f"sig_{k}",
                                                label_visibility="collapsed")

        selected_keys = [k for k in sheet_keys
                         if show_eps_map.get(k) or show_sigma_map.get(k)]

        st.divider()

        # ── Legend names + order ─────────────────────────────────────────────
        st.markdown("**Legend Names & Order**")
        legend_names = {}
        for k in sheet_keys:
            legend_names[k] = st.text_input(
                k, value=sheets[k]["name"],
                key=f"leg_{k}", label_visibility="collapsed")

        st.markdown("**Plot order** (1 = top)")
        order_inputs = {}
        ocols = st.columns(2)
        for i, k in enumerate(sheet_keys):
            order_inputs[k] = ocols[i % 2].number_input(
                legend_names.get(k, k)[:16],
                min_value=1, max_value=len(sheet_keys),
                value=i + 1, step=1, key=f"ord_{k}")

        selected_keys = [k for k in
                         sorted(sheet_keys, key=lambda k: (order_inputs[k], sheet_keys.index(k)))
                         if k in selected_keys]

        st.divider()

        # ── Frequency markers (x) ────────────────────────────────────────────
        st.markdown("**Frequency Markers (x-axis)**")
        marker_input = st.text_input("Frequencies (MHz) — comma-separated",
                                     placeholder="e.g. 21.33, 63.86",
                                     key="xmarkers")
        marker_freqs = parse_list(marker_input)

        st.divider()

        # ── Y-axis markers (horizontal lines) ────────────────────────────────
        st.markdown("**Y-Axis Markers (horizontal lines)**")
        eps_hline_input = st.text_input(
            "ε' values — comma-separated",
            placeholder="e.g. 78.5, 79.0", key="eps_hlines")
        sigma_hline_input = st.text_input(
            "σ values (S/m) — comma-separated",
            placeholder="e.g. 0.04, 0.05", key="sig_hlines")
        eps_hlines   = parse_list(eps_hline_input)
        sigma_hlines = parse_list(sigma_hline_input)

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
        sheets         = {}
        sheet_keys     = []
        selected_keys  = []
        legend_names   = {}
        marker_freqs   = []
        eps_hlines     = []
        sigma_hlines   = []
        show_eps_map   = {}
        show_sigma_map = {}
        graph_title    = "DAK-12 Dielectric Measurements"

# ── Main plot ─────────────────────────────────────────────────────────────────

plot_title = graph_title if uploaded else "DAK-12 Dielectric Measurements"
st.markdown(f"## {plot_title}")

if not uploaded:
    st.info("👈 Upload a DAK-12 XLSX file in the sidebar to get started.")
    st.stop()

if not selected_keys:
    st.warning("Select at least one ε' or σ toggle in the sidebar to plot.")
    st.stop()

x_lo  = parse_lim(xmin);  x_hi  = parse_lim(xmax)
y1_lo = parse_lim(y1min); y1_hi = parse_lim(y1max)
y2_lo = parse_lim(y2min); y2_hi = parse_lim(y2max)

any_eps   = any(show_eps_map.get(k)   for k in selected_keys)
any_sigma = any(show_sigma_map.get(k) for k in selected_keys)

fig = go.Figure()
marker_table_rows = []

for k in selected_keys:
    idx   = sheet_keys.index(k)
    color = COLORS[idx % len(COLORS)]
    df    = sheets[k]["df"]
    freq  = df["f (MHz)"].values
    eps   = df["eps"].values
    sigma = df["sigma"].values
    name  = legend_names.get(k, k)

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

# dummy trace so grid renders when only sigma is shown
if not any_eps and any_sigma:
    df0 = sheets[selected_keys[0]]["df"]
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
        title="Permittivity (ε')" if any_eps else "",
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

def build_export_png(selected_keys, sheets, sheet_keys, legend_names,
                     show_eps_map, show_sigma_map, marker_freqs,
                     eps_hlines, sigma_hlines,
                     any_eps, any_sigma, plot_title,
                     x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi):
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
    ax1_ex.set_ylabel("Permittivity (ε')" if any_eps else "", fontsize=10)
    if not any_eps:
        ax1_ex.set_yticks([])
    ax2_ex.yaxis.set_label_position("right")
    ax2_ex.yaxis.tick_right()
    ax2_ex.set_ylabel("Conductivity σ (S/m)" if any_sigma else "", fontsize=10)
    if not any_sigma:
        ax2_ex.set_yticks([])
    ax1_ex.set_title(plot_title, fontsize=12, fontweight="bold", pad=8)

    handles = []
    for k in selected_keys:
        color = COLORS[sheet_keys.index(k) % len(COLORS)]
        df    = sheets[k]["df"]
        freq  = df["f (MHz)"].values
        name  = legend_names.get(k, k)
        if show_eps_map.get(k):
            ax1_ex.plot(freq, df["eps"].values, color=color, linewidth=1.8)
            handles.append(Line2D([0],[0], color=color, lw=2, label=f"{name} ε'"))
        if show_sigma_map.get(k):
            ax2_ex.plot(freq, df["sigma"].values, color=color, lw=1.8, linestyle="--")
            handles.append(Line2D([0],[0], color=color, lw=2, linestyle="--", label=f"{name} σ"))
        if marker_freqs:
            f_e = interp1d(freq, df["eps"].values,   kind="cubic", fill_value="extrapolate")
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

    # horizontal y-axis markers
    for val in eps_hlines:
        ax1_ex.axhline(val, color="#1f77b4", linewidth=1.2, linestyle=":")
        ax1_ex.text(0.01, val, f"ε'={val}", transform=ax1_ex.get_yaxis_transform(),
                    color="#1f77b4", fontsize=8, va="bottom")
    for val in sigma_hlines:
        ax2_ex.axhline(val, color="#d62728", linewidth=1.2, linestyle=":")
        ax2_ex.text(0.99, val, f"σ={val}", transform=ax2_ex.get_yaxis_transform(),
                    color="#d62728", fontsize=8, va="bottom", ha="right")

    if x_lo  is not None and x_hi  is not None: ax1_ex.set_xlim(x_lo,  x_hi)
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
    selected_keys, sheets, sheet_keys, legend_names,
    show_eps_map, show_sigma_map, marker_freqs,
    eps_hlines, sigma_hlines,
    any_eps, any_sigma, plot_title,
    x_lo, x_hi, y1_lo, y1_hi, y2_lo, y2_hi)
st.download_button("💾 Export Plot as PNG", data=png_bytes,
                   file_name="dak12_plot.png", mime="image/png")

# ── Marker table ──────────────────────────────────────────────────────────────

if marker_table_rows:
    st.divider()
    st.markdown("**Interpolated Values at Marked Frequencies**")
    st.dataframe(pd.DataFrame(marker_table_rows), use_container_width=True, hide_index=True)
