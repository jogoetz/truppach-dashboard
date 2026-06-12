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
# HND ABFLUSS Plankenfels
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
# GKD Behringersmühle (beides!)
# -----------------------------
@st.cache_data(ttl=600)
def load_bm():
    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameterNr=15&parameter=konzentration"

    try:
        tables = pd.read_html(url, flavor="bs4")
    except Exception:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])

    if df.shape[1] < 3:
        return pd.DataFrame()

    df = df.iloc[:, :3]
    df.columns = ["time", "abfluss", "schweb"]

    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    for col in ["abfluss", "schweb"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.extract(r"([-+]?\d*\.?\d+)")[0]
            .astype(float)
        )

    return df.dropna(subset=["time"])

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

sel_stations = st.sidebar.multiselect("Stationen", stations, stations)
sel_params = st.sidebar.multiselect("Parameter", params, params)

show_raw = st.sidebar.checkbox("Rohdaten", True)
show_maintenance = st.sidebar.checkbox("Wartung", True)

# externe daten
show_pf = st.sidebar.checkbox("Abfluss Plankenfels", True)
show_rain = st.sidebar.checkbox("Niederschlag", True)
show_bm_a = st.sidebar.checkbox("BM Abfluss", False)
show_bm_s = st.sidebar.checkbox("BM Schwebstoff", True)

# -----------------------------
# FILTER
# -----------------------------
df = df[
    (df["station"].isin(sel_stations)) &
    (df["parameter"].isin(sel_params))
]

# -----------------------------
# PLOT
# -----------------------------
fig = go.Figure()

# Wartung
if show_maintenance:
    for d in maintenance_dates:
        fig.add_vrect(x0=d, x1=d+pd.Timedelta(days=1), fillcolor="gray", opacity=0.2)

# Sensoren
for (s,p), d in df.groupby(["station","parameter"]):
    d = d.sort_values("time")

    if show_raw:
        fig.add_trace(go.Scatter(x=d["time"], y=d["value"], opacity=0.2, showlegend=False))

    fig.add_trace(go.Scatter(x=d["time"], y=d["value"], name=f"{s}-{p}"))

# --- externe ---
if show_pf:
    d = load_hnd_abfluss()
    fig.add_trace(go.Scatter(x=d["time"], y=d["abfluss"], name="PF Abfluss", line=dict(color="black"), yaxis="y3"))

if show_rain:
    d = load_rain()
    fig.add_trace(go.Bar(x=d["time"], y=d["rain"], name="Regen", opacity=0.3, yaxis="y4"))

if show_bm_a or show_bm_s:
    d = load_bm()
    
    if show_bm_a:
        fig.add_trace(go.Scatter(x=d["time"], y=d["abfluss"], name="BM Abfluss", line=dict(color="blue"), yaxis="y3"))

    if show_bm_s:
        fig.add_trace(go.Scatter(x=d["time"], y=d["schweb"], name="BM Schwebstoff", line=dict(color="brown"), yaxis="y2"))

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
# EXPORT
# -----------------------------
st.subheader("Export")

station = st.selectbox("Station", stations)

df_e = df[df["station"]==station]
tv = df_e["time"].dropna()

if tv.empty:
    st.stop()

start = st.datetime_input("Start", tv.min())
end   = st.datetime_input("Ende", tv.max())

out = df_e[(df_e["time"]>=start)&(df_e["time"]<=end)]

st.download_button("CSV", out.to_csv(index=False), f"{station}.csv")
