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
    r = requests.get(PARQUET_URL, timeout=10)
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

    tables = pd.read_html(url, flavor="bs4", decimal=",", thousands=".")
    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])
    cols = list(df.columns)

    time_col = cols[0]
    value_col = next((c for c in cols if "abfluss" in str(c).lower()), cols[1])

    df = df[[time_col, value_col]]
    df.columns = ["time", "abfluss"]

    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")
    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")

    return df.dropna()

# -----------------------------
# BEHRINGERSMÜHLE
# -----------------------------
@st.cache_data(ttl=600)
def load_behringersmuehle():

    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameter=konzentration&parameterNr=14&beginn=01.01.2025&ende=11.06.2026"

    try:
        tables = pd.read_html(
            url,
            flavor="bs4",
            decimal=",",
            thousands=None
        )
    except Exception:
        return pd.DataFrame()

    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])

    # ✅ nur relevante Spalten
    df = df.iloc[:, :3]
    df.columns = ["time", "schweb_bm", "abfluss_bm"]

    # ✅ Datum
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    # ✅ Zahlen korrekt
    df["schweb_bm"] = pd.to_numeric(df["schweb_bm"], errors="coerce")
    df["abfluss_bm"] = pd.to_numeric(df["abfluss_bm"], errors="coerce")

    df = df.dropna(subset=["time", "schweb_bm", "abfluss_bm"])

    return df

# -----------------------------
# RESET
# -----------------------------
if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

df_all = load_data()

if df_all.empty:
    st.error("❌ Keine Daten gefunden")
    st.stop()

# -----------------------------
# FILTER
# -----------------------------
stations = sorted(df_all["station"].unique())
params = sorted(df_all["parameter"].unique())

default_selection = stations
if st.session_state.selected_station_map:
    default_selection = [st.session_state.selected_station_map]

sel_stations = st.sidebar.multiselect("Stationen", stations, default_selection)
sel_params = st.sidebar.multiselect("Parameter", params, params)

smooth_pressure = st.sidebar.slider("Glättung Druck", 1, 200, 10)
smooth_turbidity = st.sidebar.slider("Glättung Trübung", 1, 200, 10)

show_raw = st.sidebar.checkbox("Rohdaten anzeigen", False)
show_maintenance = st.sidebar.checkbox("Wartungstage anzeigen", False)
show_hnd = st.sidebar.checkbox("🌊 Abfluss Plankenfels", False)
show_bm_abfluss = st.sidebar.checkbox("🌊 Abfluss Behringersmühle", False)
show_bm_schweb  = st.sidebar.checkbox("🟤 Schwebstoff Behringersmühle (g/m³)", False)

scale_pressure = st.sidebar.radio("Skala Druck", ["linear", "log"], horizontal=True)
scale_turbidity = st.sidebar.radio("Skala Trübung", ["linear", "log"], horizontal=True)

df = df_all[
    (df_all["station"].isin(sel_stations)) &
    (df_all["parameter"].isin(sel_params))
]

df_bm = load_behringersmuehle() if (show_bm_abfluss or show_bm_schweb) else None

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

if show_maintenance:
    for d in maintenance_dates:
        fig.add_shape(
            type="rect",
            x0=d,
            x1=d + pd.Timedelta(days=1),
            yref="paper",
            y0=0,
            y1=1,
            opacity=0.25,
            fillcolor="gray",
            line_width=0
        )

color_map = {
    "Plankenfels": "#1f77b4",
    "Geislareuth": "#ff7f0e",
    "Seitenbach": "#2ca02c",
    "Wehr": "#d62728",
}

for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")
    is_pressure = "Druck" in param

    window = smooth_pressure if is_pressure else smooth_turbidity
    y_smooth = smooth(d["value"], window)

    axis = "y" if is_pressure else "y2"
    color = color_map.get(station, "#888888")

    if show_raw:
        fig.add_trace(go.Scatter(
            x=d["time"], y=d["value"],
            opacity=0.25,
            showlegend=False,
            line=dict(color=color, dash="dot"),
            yaxis=axis
        ))

    fig.add_trace(go.Scatter(
        x=d["time"],
        y=y_smooth,
        name=f"{station} - {param}",
        line=dict(color=color, dash="dot" if is_pressure else "solid"),
        yaxis=axis
    ))

# Abfluss
if show_hnd:
    d = load_hnd_abfluss()
    fig.add_trace(go.Scatter(x=d["time"], y=d["abfluss"], name="Abfluss PF", yaxis="y3"))

if show_bm_abfluss and df_bm is not None:
    fig.add_trace(go.Scatter(x=df_bm["time"], y=df_bm["abfluss_bm"], name="Abfluss BM", yaxis="y3"))

# Schwebstoff
if show_bm_schweb and df_bm is not None:
    fig.add_trace(go.Scatter(x=df_bm["time"], y=df_bm["schweb_bm"], name="Schwebstoff BM", yaxis="y4"))

# ✅ 4 ACHSEN
fig.update_layout(
    height=650,
    xaxis_title="Zeit",
    hovermode="x unified",

    yaxis=dict(title="Druck (psi)", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung (NTU)", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss (m³/s)", overlaying="y", side="right", position=0.95),
    
    yaxis4=dict(
        title="Schwebstoff (g/m³)",
        overlaying="y",
        side="left",
        position=0.02,   # weiter nach außen
        anchor="x"       # wichtig!
    ),

    margin=dict(l=120, r=80)   # mehr Platz links

)

st.plotly_chart(fig, use_container_width=True)

# -----------------------------
# KARTE
# -----------------------------
st.subheader("🗺️ Messstationen")

station_coords = {
    "Plankenfels": [49.8791219270009, 11.3350454717875],
    "Geislareuth": [49.92225187, 11.42177715],
    "Seitenbach": [49.9151933518834, 11.3986191898584],
    "Wehr": [49.91562086, 11.39690505]
}

map_df = pd.DataFrame([
    {"station": s, "lat": coords[0], "lon": coords[1]}
    for s, coords in station_coords.items()
])

fig_map = go.Figure(go.Scattermapbox(
    lat=map_df["lat"],
    lon=map_df["lon"],
    mode="markers",
    marker=dict(size=14, color=[color_map.get(s, "#888888") for s in map_df["station"]]),
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
st.subheader("⬇️ Datenexport (Rohdaten)")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

with col2:
    start_date = st.datetime_input("Startzeit", df_all["time"].min())

with col3:
    end_date = st.datetime_input("Endzeit", df_all["time"].max())

export_df = df_all[
    (df_all["station"] == export_station) &
    (df_all["time"] >= pd.to_datetime(start_date)) &
    (df_all["time"] <= pd.to_datetime(end_date))
].sort_values("time")

if not export_df.empty:
    csv = export_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 CSV herunterladen", csv, f"{export_station}_export.csv")
else:
    st.warning("Keine Daten im gewählten Zeitraum")
