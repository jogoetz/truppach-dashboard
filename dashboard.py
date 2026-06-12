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
# ✅ WARTUNGSTAGE
# -----------------------------
maintenance_dates = [
    "03.06.2026","15.05.2026","30.04.2026","26.03.2026",
    "11.02.2026","09.02.2026","27.01.2026",
    "18.12.2025","08.12.2025","02.12.2025",
    "06.11.2025","30.10.2025","20.10.2025",
    "15.10.2025","02.10.2025","01.09.2025"
]
maintenance_dates = pd.to_datetime(maintenance_dates, dayfirst=True)

# -----------------------------
# LOAD MAIN DATA
# -----------------------------
@st.cache_data
def load_data():
    r = requests.get(PARQUET_URL)
    r.raise_for_status()
    df = pd.read_parquet(io.BytesIO(r.content))
    df["time"] = pd.to_datetime(df["time"], errors="coerce")
    return df

# -----------------------------
# ✅ HND DATA
# -----------------------------
@st.cache_data(ttl=600)
def load_hnd_abfluss():
    url = "https://www.gkd.bayern.de/de/fluesse/abfluss/bayern/plankenfels-24244504/messwerte?zr=woche&addhr=hr_hw&beginn=01.01.2025&ende=12.06.2026"
    # url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&von=01.01.2025&bis=31.12.2026"
    tables = pd.read_html(url, flavor="bs4", decimal=",", thousands=".")
    df_hnd = tables[0]

    df_hnd.columns = ["time", "abfluss"]
    df_hnd["time"] = pd.to_datetime(df_hnd["time"], dayfirst=True)
    df_hnd["abfluss"] = pd.to_numeric(df_hnd["abfluss"], errors="coerce")

    return df_hnd.dropna()

# -----------------------------
# RESET
# -----------------------------
if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

df = load_data()

if df is None or df.empty:
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

# ✅ NEU: HND Abfluss
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
# ✅ PLOT
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
            line_width=0,
            layer="below"
        )

base_colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728"]
color_map = {s: base_colors[i % 4] for i, s in enumerate(stations)}

# Hauptdaten
for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_smooth = smooth(d["value"], window)

    axis = "y1" if "Druck" in param else "y2"
    color = color_map.get(station, "#000000")
    dash = "dash" if "Druck" in param else "solid"

    if show_raw:
        fig.add_trace(
            go.Scatter(
                x=d["time"],
                y=d["value"],
                mode="lines",
                line=dict(width=1, color=color, dash=dash),
                opacity=0.25,
                showlegend=False,
                yaxis=axis
            )
        )

    fig.add_trace(
        go.Scatter(
            x=d["time"],
            y=y_smooth,
            mode="lines",
            line=dict(width=3, color=color, dash=dash),
            name=f"{station} - {param}",
            legendgroup=station,
            yaxis=axis
        )
    )

# ✅ HND Abfluss hinzufügen
if show_hnd:
    df_hnd = load_hnd_abfluss()

#    df_hnd = df_hnd[
#       (df_hnd["time"] >= df["time"].min()) &
#      (df_hnd["time"] <= df["time"].max())
# ]

    fig.add_trace(
        go.Scatter(
            x=df_hnd["time"],
            y=df_hnd["abfluss"],
            mode="lines",
            name="Abfluss HND (m³/s)",
            line=dict(color="black", width=2, dash="dot"),
            yaxis="y3"
        )
    )

# Layout
fig.update_layout(
    height=600,
    xaxis_title="Zeit",
    yaxis=dict(title="Druck (psi)", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung (NTU)", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss (m³/s)", overlaying="y", side="right", position=0.92),
    legend=dict(
        x=1.05,
        y=1,
        xanchor="left",
        yanchor="top",
        bgcolor="rgba(255,255,255,0.8)"
    ),
    margin=dict(l=60, r=350, t=20, b=40),
    uirevision="keep-zoom"
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# ✅ KARTE
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

fig_map = go.Figure()
fig_map.add_trace(go.Scattermapbox(
    lat=map_df["lat"],
    lon=map_df["lon"],
    mode="markers",
    marker=dict(size=14, color=[color_map.get(s, "#888888") for s in map_df["station"]]),
    text=map_df["station"],
    hovertemplate="<b>%{text}</b><extra></extra>"
))

fig_map.update_layout(
    mapbox_style="open-street-map",
    mapbox_zoom=11,
    mapbox_center=dict(lat=map_df["lat"].mean(), lon=map_df["lon"].mean()),
    height=400,
    margin=dict(l=0, r=0, t=0, b=0)
)

st.plotly_chart(fig_map, use_container_width=True)

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
    st.download_button("📥 CSV herunterladen", csv, f"{export_station}_export.csv", "text/csv")
else:
    st.warning("Keine Daten im gewählten Zeitraum")
