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
    "15.10.2025","02.10.2025","01.09.2025"
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
# ✅ HND ABFLUSS
# -----------------------------
@st.cache_data(ttl=600)
def load_hnd_abfluss():
    url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&begin=01.01.2025&end=12.06.2026&setdiskr=15"

    tables = pd.read_html(url, flavor="bs4", decimal=",", thousands=".")
    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])
    if df.shape[1] < 2:
        return pd.DataFrame()

    df = df.iloc[:, :2]
    df.columns = ["time", "abfluss"]

    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")

    return df[df["time"].notna() & df["abfluss"].notna()]

# -----------------------------
# ✅ NIEDERSCHLAG (RICHTIGE TABELLE!)
# -----------------------------
@st.cache_data(ttl=600)
def load_rain_mistelgau():
    url = "https://www.hnd.bayern.de/niederschlag/regnitz/mistelbach-200113/tabelle?beginn=13.06.2025&ende=12.06.2026"

    tables = pd.read_html(url, flavor="bs4", decimal=",", thousands=".")
    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])
    if df.shape[1] < 2:
        return pd.DataFrame()

    df = df.iloc[:, :2]
    df.columns = ["time", "rain"]

    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    df["rain"] = pd.to_numeric(df["rain"], errors="coerce")

    return df[df["time"].notna() & df["rain"].notna()]

# -----------------------------
# RESET
# -----------------------------
if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

df = load_data()

if df.empty:
    st.error("❌ Keine Daten gefunden")
    st.stop()

# -----------------------------
# FILTER
# -----------------------------
stations = sorted(df["station"].unique())
params = sorted(df["parameter"].unique())

default_selection = stations
if st.session_state.selected_station_map:
    default_selection = [st.session_state.selected_station_map]

sel_stations = st.sidebar.multiselect("Stationen", stations, default_selection)
sel_params = st.sidebar.multiselect("Parameter", params, params)

smooth_pressure = st.sidebar.slider("Glättung Druck", 1, 200, 10)
smooth_turbidity = st.sidebar.slider("Glättung Trübung", 1, 200, 10)

show_raw = st.sidebar.checkbox("Rohdaten anzeigen", True)
show_maintenance = st.sidebar.checkbox("Wartungstage anzeigen", True)
show_hnd = st.sidebar.checkbox("🌊 Abfluss Plankenfels (HND, m³/s)", True)
show_rain = st.sidebar.checkbox("🌧️ Niederschlag Mistelgau (7 Tage", True)

scale_pressure = st.sidebar.radio("Skala Druck", ["linear", "log"], horizontal=True)
scale_turbidity = st.sidebar.radio("Skala Trübung", ["linear", "log"], horizontal=True)

df = df[
    (df["station"].isin(sel_stations)) &
    (df["parameter"].isin(sel_params))
]

# -----------------------------
# HELPER
# -----------------------------
def smooth(series, window):
    return series.rolling(window, min_periods=1).mean()

# -----------------------------
# PLOT
# -----------------------------
st.subheader("📈 Daten")
fig = go.Figure()

# Wartung
if show_maintenance:
    for d in maintenance_dates:
        fig.add_shape(
            type="rect",
            x0=d,
            x1=d + pd.Timedelta(days=1),
            y0=0,
            y1=1,
            yref="paper",
            fillcolor="gray",
            opacity=0.25,
            line_width=0
        )

# Sensoren
for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_smooth = smooth(d["value"], window)

    axis = "y1" if "Druck" in param else "y2"

    if show_raw:
        fig.add_trace(go.Scatter(x=d["time"], y=d["value"], mode="lines", opacity=0.25, showlegend=False, yaxis=axis))

    fig.add_trace(go.Scatter(x=d["time"], y=y_smooth, mode="lines", name=f"{station} - {param}", yaxis=axis))

# ✅ Abfluss
if show_hnd:
    df_hnd = load_hnd_abfluss()
    if not df_hnd.empty:
        fig.add_trace(go.Scatter(
            x=df_hnd["time"],
            y=df_hnd["abfluss"],
            mode="lines",
            name="Abfluss (m³/s)",
            line=dict(color="black", width=2, dash="dot"),
            yaxis="y3"
        ))

# ✅ Niederschlag (jetzt komplett)
if show_rain:
    df_rain = load_rain_mistelgau()
    if not df_rain.empty:
        fig.add_trace(go.Bar(
            x=df_rain["time"],
            y=df_rain["rain"],
            name="Niederschlag (mm)",
            marker_color="blue",
            opacity=0.3,
            yaxis="y4"
        ))

# Layout
fig.update_layout(
    height=650,
    xaxis_title="Zeit",
    yaxis=dict(title="Druck", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss", overlaying="y", side="right", position=0.9),
    yaxis4=dict(title="Niederschlag", overlaying="y", side="right", position=2.0),
    margin=dict(l=60, r=350, t=20, b=40)
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# ✅ EXPORT (ROBUST)
# -----------------------------
st.subheader("⬇️ Datenexport")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

df_filtered = df[df["station"] == export_station]
time_valid = df_filtered["time"].dropna()

if time_valid.empty:
    st.warning("Keine Zeitdaten verfügbar")
    st.stop()

with col2:
    start_date = st.datetime_input("Startzeit", time_valid.min())

with col3:
    end_date = st.datetime_input("Endzeit", time_valid.max())

export_df = df_filtered[
    (df_filtered["time"] >= pd.to_datetime(start_date)) &
    (df_filtered["time"] <= pd.to_datetime(end_date))
]

if not export_df.empty:
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 CSV herunterladen", csv, f"{export_station}.csv")
else:
    st.warning("Keine Daten im Zeitraum")
