import os
import json
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from bs4 import BeautifulSoup

# -----------------------------
# CONFIG
# -----------------------------
FOLDER = r"C:\data\Uni\projekte\Truppach\Troll_Data\html"
DATA_FILE = "data.parquet"
INDEX_FILE = "processed_files.json"

st.set_page_config(layout="wide")
st.title("🌊 Monitoring Truppach - Druck & Trübung")

# -----------------------------
# PARSER
# -----------------------------
def parse_html(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f, "html.parser")

    table = soup.find("table", {"id": "isi-report"})
    if table is None:
        return None

    header_row = table.find("tr", attrs={"isi-data-table": True})
    if header_row is None:
        header_row = table.find("tr", attrs={"isi-data-table": ""})
    if header_row is None:
        return None

    headers = header_row.find_all("td")

    col_map = {}

    for i, h in enumerate(headers):
        text = h.get_text(strip=True)

        if "Druck" in text and "psi" in text:
            col_map["pressure"] = i
        elif "Trübung" in text:
            col_map["turbidity"] = i

    if not col_map:
        return None

    station = "unknown"
    loc = table.find("td", {"isi-property": "Name"})
    if loc:
        val = loc.find("span", {"isi-value": True})
        if val:
            station = val.get_text(strip=True)

    rows = table.find_all("tr", {"isi-data-row": True})

    data = []

    for r in rows:
        cells = r.find_all("td")

        try:
            time = cells[0].get_text(strip=True)

            if "pressure" in col_map:
                v = cells[col_map["pressure"]].get_text(strip=True)
                if v != "":
                    data.append({
                        "time": time,
                        "station": station,
                        "parameter": "Druck (psi)",
                        "value": float(v)
                    })

            if "turbidity" in col_map:
                v = cells[col_map["turbidity"]].get_text(strip=True)
                if v != "":
                    data.append({
                        "time": time,
                        "station": station,
                        "parameter": "Trübung (NTU)",
                        "value": float(v)
                    })

        except:
            continue

    if not data:
        return None

    return pd.DataFrame(data)

# -----------------------------
# LOAD
# -----------------------------
def load_data_incremental(folder):
    if os.path.exists(INDEX_FILE):
        with open(INDEX_FILE, "r") as f:
            processed_files = set(json.load(f))
    else:
        processed_files = set()

    new_data = []
    all_files = [f for f in os.listdir(folder) if f.endswith(".html")]

    for file in all_files:
        if file in processed_files:
            continue

        path = os.path.join(folder, file)
        df = parse_html(path)

        if df is not None and not df.empty:
            new_data.append(df)

        processed_files.add(file)

    if new_data:
        new_df = pd.concat(new_data, ignore_index=True)

        if os.path.exists(DATA_FILE):
            old_df = pd.read_parquet(DATA_FILE)
            df = pd.concat([old_df, new_df], ignore_index=True)
        else:
            df = new_df

        df.to_parquet(DATA_FILE, index=False)

        with open(INDEX_FILE, "w") as f:
            json.dump(list(processed_files), f)

    if os.path.exists(DATA_FILE):
        df = pd.read_parquet(DATA_FILE)
    else:
        return None

    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df

@st.cache_data
def get_data(folder):
    return load_data_incremental(folder)

# -----------------------------
# RESET
# -----------------------------
if st.sidebar.button("♻️ Cache zurücksetzen"):
    if os.path.exists(DATA_FILE):
        os.remove(DATA_FILE)
    if os.path.exists(INDEX_FILE):
        os.remove(INDEX_FILE)
    st.rerun()

# -----------------------------
# LOAD DATA
# -----------------------------
df = get_data(FOLDER)

if df is None or df.empty:
    st.error("❌ Keine Daten gefunden")
    st.stop()

# -----------------------------
# FILTER
# -----------------------------
stations = sorted(df["station"].unique())
params = sorted(df["parameter"].unique())

sel_stations = st.sidebar.multiselect("Stationen", stations, stations)
sel_params = st.sidebar.multiselect("Parameter", params, params)

smooth_pressure = st.sidebar.slider("Glättung Druck", 1, 200, 10)
smooth_turbidity = st.sidebar.slider("Glättung Trübung", 1, 200, 10)

show_raw = st.sidebar.checkbox("Rohdaten anzeigen", True)

# ✅ NEU: Achsenskalierung
scale_pressure = st.sidebar.radio("Skala Druck", ["linear", "log"], horizontal=True)
scale_turbidity = st.sidebar.radio("Skala Trübung", ["linear", "log"], horizontal=True)

df = df[
    (df["station"].isin(sel_stations)) &
    (df["parameter"].isin(sel_params))
]

# -----------------------------
# HELPERS
# -----------------------------
def smooth(series, window):
    return series.rolling(window, min_periods=1).mean()

def downsample(d, max_points=1500):
    if len(d) > max_points:
        return d.iloc[::max(1, len(d)//max_points)]
    return d

# -----------------------------
# ✅ PLOT
# -----------------------------
fig = go.Figure()

base_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
color_map = {s: base_colors[i % 4] for i, s in enumerate(stations)}

for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    d_raw = d
    d_smooth = downsample(d.copy())

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_smooth = smooth(d_smooth["value"], window)

    axis = "y1" if "Druck" in param else "y2"
    color = color_map.get(station, "#000000")

    dash = "dash" if "Druck" in param else "solid"

    if show_raw:
        fig.add_trace(
            go.Scatter(
                x=d_raw["time"],
                y=d_raw["value"],
                mode="lines",
                line=dict(width=1, color=color, dash=dash),
                opacity=0.25,
                showlegend=False,
                yaxis=axis
            )
        )

    fig.add_trace(
        go.Scatter(
            x=d_smooth["time"],
            y=y_smooth,
            mode="lines",
            line=dict(width=3, color=color, dash=dash),
            name=f"{station} - {param}",
            legendgroup=station,
            yaxis=axis
        )
    )

# ✅ Layout mit skalierbaren Achsen
fig.update_layout(
    height=600,
    xaxis_title="Zeit",
    yaxis=dict(title="Druck (psi)", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung (NTU)", overlaying="y", side="right", type=scale_turbidity),
    
 # ✅ Legende klar rechts außerhalb
    legend=dict(
        x=1.05,
        y=1,
        xanchor="left",
        yanchor="top",
        bgcolor="rgba(255,255,255,0.8)"
    ),

    # ✅ Plot bewusst schmaler machen
    margin=dict(l=60, r=350, t=20, b=40)
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# ✅ EXPORT
# -----------------------------
st.subheader("⬇️ Datenexport (Rohdaten)")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

with col2:
    start_date = st.datetime_input("Startzeit", df["time"].min())

with col3:
    end_date = st.datetime_input("Endzeit", df["time"].max())

export_df = df[
    (df["station"] == export_station) &
    (df["time"] >= pd.to_datetime(start_date)) &
    (df["time"] <= pd.to_datetime(end_date))
].sort_values("time")

if not export_df.empty:
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button(
        "📥 CSV herunterladen",
        csv,
        f"{export_station}_export.csv",
        "text/csv"
    )
else:
    st.warning("Keine Daten im gewählten Zeitraum")

# -----------------------------
# ✅ ZEITBLÖCKE
# -----------------------------
st.subheader("📅 Verfügbare Daten (Teilzeiträume)")

def get_time_blocks(data, gap_minutes=10):
    results = []

    for (station, param), d in data.groupby(["station", "parameter"]):
        d = d.sort_values("time")
        dt = d["time"].diff().dt.total_seconds().div(60)
        blocks = (dt > gap_minutes).cumsum()

        d = d.copy()
        d["block"] = blocks

        grouped = d.groupby("block").agg(
            Start=("time", "min"),
            Ende=("time", "max"),
            Punkte=("time", "count")
        ).reset_index(drop=True)

        grouped["station"] = station
        grouped["parameter"] = param

        results.append(grouped)

    return pd.concat(results, ignore_index=True)

summary = get_time_blocks(df)

summary["Start"] = summary["Start"].dt.strftime("%Y-%m-%d %H:%M")
summary["Ende"] = summary["Ende"].dt.strftime("%Y-%m-%d %H:%M")

st.dataframe(summary, width="stretch")
