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
# ✅ GKD ABFLUSS (ROBUST FINAL)
# -----------------------------
@st.cache_data(ttl=600)
def load_gkd_abfluss():
    url = "https://www.gkd.bayern.de/de/fluesse/abfluss/bayern/plankenfels-24244504/messwerte?zr=alle&beginn=01.01.2025&ende=12.06.2026"

    try:
        tables = pd.read_html(url, flavor="bs4")
    except Exception:
        return pd.DataFrame()

    if not tables:
        return pd.DataFrame()

    # ✅ größte Tabelle nehmen → echte Messwerte
    df = max(tables, key=lambda x: x.shape[0])

    # Sicherheitscheck
    if df.shape[1] < 2:
        return pd.DataFrame()

    # nur relevante Spalten
    df = df.iloc[:, :2]
    df.columns = ["time", "abfluss"]

    # ✅ Datum robust interpretieren
    df["time"] = df["time"].astype(str)
    df["time"] = df["time"].str.replace(r"\(.*\)", "", regex=True).str.strip()

    df["time"] = pd.to_datetime(
        df["time"],
        dayfirst=True,
        errors="coerce"
    )

    # ✅ Abfluss konvertieren
    df["abfluss"] = pd.to_numeric(
        df["abfluss"].astype(str).str.replace(",", ".", regex=False),
        errors="coerce"
    )

    # ✅ nur gültige Daten behalten
    df = df[df["time"].notna() & df["abfluss"].notna()]

    return df

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
show_hnd = st.sidebar.checkbox("🌊 Abfluss Pegel Plankenfels", False)

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

# -----------------------------
# PLOT
# -----------------------------
st.subheader("📈 Daten")
fig = go.Figure()

# Wartung anzeigen
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

# Farben
base_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
color_map = {s: base_colors[i % 4] for i, s in enumerate(stations)}

# Sensor-Daten
for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_smooth = smooth(d["value"], window)

    axis = "y1" if "Druck" in param else "y2"

    if show_raw:
        fig.add_trace(go.Scatter(
            x=d["time"], y=d["value"],
            mode="lines",
            opacity=0.25,
            showlegend=False,
            yaxis=axis
        ))

    fig.add_trace(go.Scatter(
        x=d["time"], y=y_smooth,
        mode="lines",
        name=f"{station} - {param}",
        yaxis=axis
    ))

# ✅ Abfluss hinzufügen
if show_hnd:
    df_hnd = load_gkd_abfluss()

    if not df_hnd.empty:
        fig.add_trace(go.Scatter(
            x=df_hnd["time"],
            y=df_hnd["abfluss"],
            mode="lines",
            name="Abfluss (m³/s)",
            line=dict(color="black", width=2, dash="dot"),
            yaxis="y3"
        ))
    else:
        st.warning("Keine Abflussdaten verfügbar (GKD liefert aktuell keine verwertbaren Werte)")

# Layout
fig.update_layout(
    height=600,
    xaxis_title="Zeit",
    yaxis=dict(title="Druck", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss", overlaying="y", side="right", position=0.92),
    margin=dict(l=60, r=300, t=20, b=40)
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# EXPORT
# -----------------------------
st.subheader("⬇️ Datenexport")

time_valid = df["time"].dropna()

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

with col2:
    start_date = st.datetime_input("Startzeit", time_valid.min())

with col3:
    end_date = st.datetime_input("Endzeit", time_valid.max())

export_df = df[
    (df["station"] == export_station) &
    (df["time"] >= pd.to_datetime(start_date)) &
    (df["time"] <= pd.to_datetime(end_date))
]

if not export_df.empty:
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 CSV herunterladen", csv, f"{export_station}.csv")
else:
    st.warning("Keine Daten im Zeitraum")
