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

if "selected_station_map" not in st.session_state:
    st.session_state.selected_station_map = None

# -----------------------------
# WARTUNGSTAGE
# -----------------------------
maintenance_dates = pd.to_datetime([
    "03.06.2026","15.05.2026","30.04.2026","26.03.2026",
    "11.02.2026","09.02.2026","27.01.2026",
    "18.12.2025","08.12.2025","02.12.2025",
    "06.11.2025","30.10.2025","20.10.2025",
], dayfirst=True)

# -----------------------------
# LOAD MAIN DATA
# -----------------------------
@st.cache_data
def load_data():
    r = requests.get(PARQUET_URL)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df.dropna(subset=["time"])

# -----------------------------
# HND ABFLUSS
# -----------------------------
@st.cache_data(ttl=600)
def load_hnd_abfluss():
    url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&begin=01.01.2025&end=12.06.2026&setdiskr=15"
    tables = pd.read_html(url, flavor="bs4")
    df = max(tables, key=lambda x: x.shape[0])

    df = df.iloc[:, :2]
    df.columns = ["time", "abfluss"]

    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")
    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")

    return df.dropna()

# -----------------------------
# HND NIEDERSCHLAG
# -----------------------------
@st.cache_data(ttl=600)
def load_rain():
    url = "https://www.hnd.bayern.de/niederschlag/regnitz/mistelbach-200113/tabelle?beginn=13.06.2025&ende=12.06.2026"
    tables = pd.read_html(url, flavor="bs4")
    df = max(tables, key=lambda x: x.shape[0])

    df = df.iloc[:, :2]
    df.columns = ["time", "rain"]

    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")
    df["rain"] = pd.to_numeric(df["rain"], errors="coerce")

    return df.dropna()

# -----------------------------
# GKD SCHWEBSTOFF
# -----------------------------
@st.cache_data(ttl=600)
def load_schweb():
    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameterNr=15&parameter=konzentration"

    tables = pd.read_html(url, flavor="bs4")
    df = max(tables, key=lambda x: x.shape[0])

    df = df.iloc[:, :2]
    df.columns = ["time", "schweb"]

    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    df["schweb"] = (
        df["schweb"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .str.extract(r"([-+]?\d*\.?\d+)")[0]
        .astype(float)
    )

    return df.dropna()

# -----------------------------
# LOAD
# -----------------------------
df = load_data()

if df.empty:
    st.error("Keine Daten")
    st.stop()

# -----------------------------
# SIDEBAR
# -----------------------------
stations = sorted(df["station"].unique())
params = sorted(df["parameter"].unique())

default_sel = stations
if st.session_state.selected_station_map:
    default_sel = [st.session_state.selected_station_map]

sel_stations = st.sidebar.multiselect("Stationen", stations, default_sel)
sel_params = st.sidebar.multiselect("Parameter", params, params)

show_raw = st.sidebar.checkbox("Rohdaten", True)
show_maintenance = st.sidebar.checkbox("Wartung", True)

show_pf = st.sidebar.checkbox("Abfluss Plankenfels", True)
show_rain = st.sidebar.checkbox("Niederschlag", True)
show_schweb = st.sidebar.checkbox("Schwebstoff", True)

# -----------------------------
# FILTER
# -----------------------------
df = df[
    df["station"].isin(sel_stations) &
    df["parameter"].isin(sel_params)
]

# -----------------------------
# PLOT
# -----------------------------
fig = go.Figure()

if show_maintenance:
    for d in maintenance_dates:
        fig.add_vrect(x0=d, x1=d+pd.Timedelta(days=1), fillcolor="gray", opacity=0.2)

for (s,p), d in df.groupby(["station","parameter"]):
    d = d.sort_values("time")

    if show_raw:
        fig.add_trace(go.Scatter(x=d["time"], y=d["value"], opacity=0.2, showlegend=False))

    fig.add_trace(go.Scatter(x=d["time"], y=d["value"], name=f"{s}-{p}"))

# externe Daten
if show_pf:
    d = load_hnd_abfluss()
    fig.add_trace(go.Scatter(x=d["time"], y=d["abfluss"], name="PF Abfluss", yaxis="y3"))

if show_rain:
    d = load_rain()
    fig.add_trace(go.Bar(x=d["time"], y=d["rain"], name="Regen", yaxis="y4"))

if show_schweb:
    d = load_schweb()
    fig.add_trace(go.Scatter(x=d["time"], y=d["schweb"], name="Schwebstoff", yaxis="y2"))

fig.update_layout(
    height=600,
    yaxis=dict(title="Druck"),
    yaxis2=dict(title="Trübung/Schwebstoff", overlaying="y", side="right"),
    yaxis3=dict(title="Abfluss", overlaying="y", side="right", position=0.9),
    yaxis4=dict(title="Regen", overlaying="y", side="right", position=1.0)
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# ✅ KARTE (INTERAKTIV)
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
    for s,c in station_coords.items()
])

fig_map = go.Figure()

fig_map.add_trace(go.Scattermapbox(
    lat=map_df["lat"],
    lon=map_df["lon"],
    mode="markers+text",
    text=map_df["station"],
    marker=dict(size=14, color="blue")
))

fig_map.update_layout(
    mapbox_style="open-street-map",
    mapbox_zoom=11,
    mapbox_center=dict(
        lat=map_df["lat"].mean(),
        lon=map_df["lon"].mean()
    ),
    height=400,
    margin=dict(l=0,r=0,t=0,b=0)
)

# ✅ Klick-Auswahl
clicked = st.plotly_chart(fig_map, use_container_width=True)

if clicked and "points" in clicked:
    point = clicked["points"][0]
    selected = map_df.iloc[point["pointIndex"]]["station"]
    st.session_state.selected_station_map = selected
    st.rerun()

# -----------------------------
# EXPORT
# -----------------------------
st.subheader("Export")

station = st.selectbox("Station", stations)

df_e = df[df["station"]==station]
tv = df_e["time"].dropna()

start = st.datetime_input("Start", tv.min())
end   = st.datetime_input("Ende", tv.max())

out = df_e[(df_e["time"]>=start)&(df_e["time"]<=end)]

st.download_button("CSV", out.to_csv(index=False), f"{station}.csv")
