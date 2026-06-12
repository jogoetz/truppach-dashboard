import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import requests
import io

# -----------------------------
# CONFIG
# -----------------------------
PARQUET_URL = "https://github.com/jogoetz/truppach-dashboard/raw/refs/heads/main/data.parquet"

st.set_page_config(layout="wide")
st.title("🌊 Monitoring Truppach - Druck & Trübung")

# -----------------------------
# COLORS
# -----------------------------
color_map = {
    "Plankenfels": "#1f77b4",
    "Geislareuth": "#ff7f0e",
    "Seitenbach": "#2ca02c",
    "Wehr": "#d62728",
}

# -----------------------------
# LOAD DATA
# -----------------------------
@st.cache_data
def load_data():
    r = requests.get(PARQUET_URL, timeout=10)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df.dropna(subset=["time"])

@st.cache_data(ttl=600)
def load_hnd():
    url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&begin=01.01.2025&end=12.06.2026&setdiskr=15"
    try:
        df = pd.read_html(url, decimal=",", thousands=".")[0]
    except:
        return pd.DataFrame()
    df = df.iloc[:, :2]
    df.columns = ["time", "abfluss"]
    df["time"] = pd.to_datetime(df["time"], errors="coerce", dayfirst=True)
    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")
    return df.dropna()

@st.cache_data(ttl=600)
def load_bm():
    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameter=konzentration&parameterNr=14&beginn=01.01.2025&ende=11.06.2026"
    try:
        df = pd.read_html(url)[0]
    except:
        return pd.DataFrame()
    df = df.iloc[:, :3]
    df.columns = ["time", "schweb", "abfluss"]
    df["time"] = pd.to_datetime(df["time"], dayfirst=True)
    df["schweb"] = pd.to_numeric(df["schweb"], errors="coerce")
    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")
    return df.dropna()

df_all = load_data()
df_hnd = load_hnd()
df_bm = load_bm()

# -----------------------------
# SIDEBAR
# -----------------------------
stations = sorted(df_all["station"].unique())
params = sorted(df_all["parameter"].unique())

sel_stations = st.sidebar.multiselect("Stationen", stations, stations)
sel_params = st.sidebar.multiselect("Parameter", params, params)

st.sidebar.markdown("### Achsen")
show_pressure = st.sidebar.checkbox("Druck", True)
show_turbidity = st.sidebar.checkbox("Trübung", True)
show_flow = st.sidebar.checkbox("Abfluss", True)
show_sediment = st.sidebar.checkbox("Schwebstoff", True)

scale_pressure = st.sidebar.radio("Skala Druck", ["linear", "log"])
scale_turbidity = st.sidebar.radio("Skala Trübung", ["linear", "log"])

df = df_all[
    (df_all["station"].isin(sel_stations)) &
    (df_all["parameter"].isin(sel_params))
]

# -----------------------------
# PLOT
# -----------------------------
fig = go.Figure()

def smooth(s, w=10):
    return s.rolling(w, min_periods=1).mean()

for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")
    is_pressure = "Druck" in param

    if is_pressure and not show_pressure:
        continue
    if not is_pressure and not show_turbidity:
        continue

    axis = "y" if is_pressure else "y2"

    fig.add_trace(go.Scatter(
        x=d["time"],
        y=smooth(d["value"]),
        name=f"{station} - {param}",
        line=dict(
            color=color_map.get(station, "#888"),
            dash="dot" if is_pressure else "solid",
            width=2
        ),
        yaxis=axis
    ))

# Abfluss
if show_flow:
    if not df_hnd.empty:
        fig.add_trace(go.Scatter(
            x=df_hnd["time"], y=df_hnd["abfluss"],
            name="Abfluss PF",
            line=dict(color="black"),
            yaxis="y3"
        ))
    if not df_bm.empty:
        fig.add_trace(go.Scatter(
            x=df_bm["time"], y=df_bm["abfluss"],
            name="Abfluss BM",
            line=dict(color="gray"),
            yaxis="y3"
        ))

# Schwebstoff
if show_sediment and not df_bm.empty:
    fig.add_trace(go.Scatter(
        x=df_bm["time"],
        y=df_bm["schweb"],
        name="Schwebstoff BM",
        line=dict(color="brown"),
        yaxis="y4"
    ))

# -----------------------------
# LAYOUT (4 AXES)
# -----------------------------
fig.update_layout(
    height=650,
    hovermode="x unified",

    xaxis=dict(title="Zeit"),

    yaxis=dict(title="Druck (psi)", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung (NTU)", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss (m³/s)", overlaying="y", side="right", position=0.95),
    yaxis4=dict(title="Schwebstoff (g/m³)", overlaying="y", side="left", position=0.05),

    margin=dict(l=80, r=80)
)

st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# MAP
# -----------------------------
st.subheader("🗺️ Messstationen")

station_coords = {
    "Plankenfels": [49.8791, 11.3350],
    "Geislareuth": [49.9222, 11.4217],
    "Seitenbach": [49.9151, 11.3986],
    "Wehr": [49.9156, 11.3969]
}

map_df = pd.DataFrame([
    {"station": s, "lat": c[0], "lon": c[1]}
    for s, c in station_coords.items()
])

fig_map = go.Figure(go.Scattermapbox(
    lat=map_df["lat"],
    lon=map_df["lon"],
    mode="markers",
    marker=dict(size=14, color=[color_map.get(s) for s in map_df["station"]]),
    text=map_df["station"]
))

fig_map.update_layout(
    mapbox_style="open-street-map",
    mapbox_zoom=11,
    mapbox_center=dict(lat=map_df["lat"].mean(), lon=map_df["lon"].mean()),
    height=400
)

st.plotly_chart(fig_map, use_container_width=True)

# -----------------------------
# EXPORT
# -----------------------------
st.subheader("⬇️ Datenexport")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station", stations)

with col2:
    start = st.datetime_input("Start", df_all["time"].min())

with col3:
    end = st.datetime_input("Ende", df_all["time"].max())

export_df = df_all[
    (df_all["station"] == export_station) &
    (df_all["time"] >= pd.to_datetime(start)) &
    (df_all["time"] <= pd.to_datetime(end))
]

if not export_df.empty:
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button("CSV herunterladen", csv, f"{export_station}.csv")
else:
    st.warning("Keine Daten")
