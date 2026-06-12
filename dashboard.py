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
# ✅ HND ABFLUSS (Plankenfels)
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
# ✅ NIEDERSCHLAG (Mistelgau)
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
# ✅ SCHWEBSTOFF (GKD, Behringersmühle)
# -----------------------------
@st.cache_data(ttl=600)
def load_schwebstoff():
    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameterNr=15&parameter=konzentration"

    try:
        tables = pd.read_html(url, flavor="bs4")
    except Exception:
        return pd.DataFrame()

    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])
    if df.shape[1] < 2:
        return pd.DataFrame()

    df = df.iloc[:, :2]
    df.columns = ["time", "schweb"]

    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    df["schweb"] = (
        df["schweb"]
        .astype(str)
        .str.replace(",", ".", regex=False)
        .str.extract(r"([-+]?\d*\.?\d+)")[0]
        .astype(float)
    )

    return df[df["time"].notna() & df["schweb"].notna()]

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

sel_stations = st.sidebar.multiselect("Stationen", stations, stations)
sel_params = st.sidebar.multiselect("Parameter", params, params)

smooth_pressure = st.sidebar.slider("Glättung Druck", 1, 200, 10)
smooth_turbidity = st.sidebar.slider("Glättung Trübung", 1, 200, 10)

show_raw = st.sidebar.checkbox("Rohdaten anzeigen", True)
show_maintenance = st.sidebar.checkbox("Wartungstage anzeigen", True)

# ✅ neue Checkboxen
show_hnd = st.sidebar.checkbox("🌊 Abfluss Plankenfels", True)
show_rain = st.sidebar.checkbox("🌧️ Niederschlag Mistelgau", True)
show_schweb = st.sidebar.checkbox("🟤 Schwebstoff Behringersmühle (g/m³)", True)

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
            opacity=0.25
        )

# Sensoren
for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_s = smooth(d["value"], window)

    axis = "y1" if "Druck" in param else "y2"

    if show_raw:
        fig.add_trace(go.Scatter(x=d["time"], y=d["value"], mode="lines", opacity=0.25, showlegend=False, yaxis=axis))

    fig.add_trace(go.Scatter(x=d["time"], y=y_s, mode="lines", name=f"{station}-{param}", yaxis=axis))

# Abfluss
if show_hnd:
    dfa = load_hnd_abfluss()
    if not dfa.empty:
        fig.add_trace(go.Scatter(x=dfa["time"], y=dfa["abfluss"], name="Abfluss", line=dict(color="black"), yaxis="y3"))

# Regen
if show_rain:
    dfr = load_rain_mistelgau()
    if not dfr.empty:
        fig.add_trace(go.Bar(x=dfr["time"], y=dfr["rain"], name="Regen", opacity=0.3, yaxis="y4"))

# Schwebstoff
if show_schweb:
    dfs = load_schwebstoff()
    if not dfs.empty:
        fig.add_trace(go.Scatter(x=dfs["time"], y=dfs["schweb"], name="Schwebstoff", line=dict(color="brown"), yaxis="y2"))

# Layout
fig.update_layout(
    height=650,
    yaxis=dict(title="Druck"),
    yaxis2=dict(title="Trübung / Schwebstoff", overlaying="y", side="right"),
    yaxis3=dict(title="Abfluss", overlaying="y", side="right", position=0.9),
    yaxis4=dict(title="Regen", overlaying="y", side="right", position=1.0),
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# EXPORT (FIX)
# -----------------------------
st.subheader("⬇️ Datenexport")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

df_f = df[df["station"] == export_station]
time_valid = df_f["time"].dropna()

if time_valid.empty:
    st.warning("Keine Zeitdaten")
    st.stop()

with col2:
    start = st.datetime_input("Start", time_valid.min())

with col3:
    end = st.datetime_input("Ende", time_valid.max())

exp = df_f[(df_f["time"] >= start) & (df_f["time"] <= end)]

if not exp.empty:
    st.download_button("CSV", exp.to_csv(index=False), f"{export_station}.csv")
else:
    st.warning("Keine Daten")
