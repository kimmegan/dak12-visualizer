# DAK-12 Dielectric Visualizer

A web app for visualizing dielectric measurements from the DAK-12 probe system.

## Features
- Upload multi-sheet DAK-12 XLSX files
- Select/deselect individual buffers to plot
- Dual Y-axis: Permittivity (ε') on left, Conductivity (σ) on right
- Interactive hover tooltips
- Frequency marker tool with interpolated values
- Adjustable axis limits
- Export plot as PNG

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy to Streamlit Cloud (free)
1. Push this folder to a GitHub repo
2. Go to https://share.streamlit.io
3. Click "New app" → select your repo → set main file to `app.py`
4. Click Deploy
