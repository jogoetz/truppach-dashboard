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
# HND ABFLUSS
# -----------------------------
@st.cache_data(ttl=600)
def load_hnd_abfluss():
    url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&begin=01.01.2025&end=12.06.2026&setdiskr=15"

    tables = pd.read_html(url, flavor="bs4", decimal=",", thousands=".")

    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])

    # ✅ Spaltennamen sauber setzen
    cols = list(df.columns)

    # Debug einmal
    # st.write(cols)

    # ✅ richtige Spalten automatisch finden
    time_col = cols[0]

    # suche Spalte mit "Abfluss"
    value_col = None
    for c in cols:
        if "abfluss" in str(c).lower():
            value_col = c
            break

    # fallback → zweite Spalte
    if value_col is None and len(cols) >= 2:
        value_col = cols[1]

    df = df[[time_col, value_col]]
    df.columns = ["time", "abfluss"]

    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    df["abfluss"] = pd.to_numeric(df["abfluss"], errors="coerce")

    df = df[df["time"].notna() & df["abfluss"].notna()]

    return df


# -----------------------------
# ✅ BEHRINGERSMÜHLE (GKD: ABFLUSS + SCHWEBSTOFF)
# -----------------------------
@st.cache_data(ttl=600)
def load_behringersmuehle():
    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameter=konzentration&parameterNr=14&beginn=01.01.2025&ende=11.06.2026"

    try:
        tables = pd.read_html(url, flavor="bs4")
    except Exception:
        return pd.DataFrame()

    if not tables:
        return pd.DataFrame()

    df = max(tables, key=lambda x: x.shape[0])

    if df.shape[1] < 3:
        return pd.DataFrame()

    cols = list(df.columns)

    time_col = cols[0]

    # ✅ Spalten automatisch erkennen
    abfluss_col = None
    schweb_col = None

    for c in cols:
        c_str = str(c).lower()
        if "abfluss" in c_str:
            abfluss_col = c
        if "konzentration" in c_str or "schweb" in c_str:
            schweb_col = c

    # Fallback (falls HND Struktur abweicht)
    if abfluss_col is None and len(cols) > 1:
        abfluss_col = cols[1]
    if schweb_col is None and len(cols) > 2:
        schweb_col = cols[2]

    df = df[[time_col, abfluss_col, schweb_col]]
    df.columns = ["time", "abfluss_bm", "schweb_bm"]

    # Datum
    df["time"] = df["time"].astype(str).str.replace(r"\(.*\)", "", regex=True).str.strip()
    df["time"] = pd.to_datetime(df["time"], dayfirst=True, errors="coerce")

    # Werte
    for col in ["abfluss_bm", "schweb_bm"]:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", ".", regex=False)
            .str.extract(r"([-+]?\d*\.?\d+)")[0]
            .astype(float)
        )

    df = df[df["time"].notna()]

    return df


# -----------------------------
# RESET
# -----------------------------
if st.sidebar.button("🔄 Daten neu laden"):
    st.cache_data.clear()
    st.rerun()

# ✅ WICHTIG: Original-Daten separat behalten!
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

# ✅ NUR fürs Plotten gefiltert
df = df_all[
    (df_all["station"].isin(sel_stations)) &
    (df_all["parameter"].isin(sel_params))
]

if show_bm_abfluss or show_bm_schweb:
    df_bm = load_behringersmuehle()
else:
    df_bm = None

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
            y0=0,
            y1=1,
            yref="paper",
            fillcolor="gray",
            opacity=0.25,
            line_width=0
        )

for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")

    window = smooth_pressure if "Druck" in param else smooth_turbidity
    y_smooth = smooth(d["value"], window)

    axis = "y1" if "Druck" in param else "y2"

    if show_raw:
        fig.add_trace(go.Scatter(x=d["time"], y=d["value"], mode="lines", opacity=0.25, showlegend=False, yaxis=axis))

    fig.add_trace(go.Scatter(x=d["time"], y=y_smooth, mode="lines", name=f"{station} - {param}", yaxis=axis))

# Abfluss
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


# Behringersmühle Abfluss
if show_bm_abfluss and df_bm is not None and not df_bm.empty:
    fig.add_trace(go.Scatter(
        x=df_bm["time"],
        y=df_bm["abfluss_bm"],
        mode="lines",
        name="Abfluss Behringersmühle (m³/s)",
        line=dict(color="darkblue", width=2, dash="dot"),
        yaxis="y3"
    ))

# Behringersmühle Schwebstoff
if show_bm_schweb and df_bm is not None and not df_bm.empty:
    fig.add_trace(go.Scatter(
        x=df_bm["time"],
        y=df_bm["schweb_bm"],
        mode="lines",
        name="Schwebstoff Behringersmühle (g/m³)",
        line=dict(color="brown", width=2),
        yaxis="y2"
    ))


# Layout
fig.update_layout(
    height=600,
    xaxis_title="Zeit",
    yaxis=dict(title="Druck (psi)", side="left", type=scale_pressure),
    yaxis2=dict(title="Trübung (NTU)", overlaying="y", side="right", type=scale_turbidity),
    yaxis3=dict(title="Abfluss (m³/s)", overlaying="y", side="right", position=0.92)
)

st.plotly_chart(fig, width="stretch")

# -----------------------------
# ✅ KARTE (WIEDER DRIN)
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
    margin=dict(l=0, r=0, t=0, b=0)
)

st.plotly_chart(fig_map, width="stretch")

# optional: Klick → Filter
try:
    clicked = st.session_state.get("map_click")
except:
    clicked = None

# -----------------------------
# ✅ EXPORT (JETZT FIX)
# -----------------------------
st.subheader("⬇️ Datenexport")

col1, col2, col3 = st.columns(3)

with col1:
    export_station = st.selectbox("Station wählen", stations)

# ✅ WICHTIG: UNGEFILTERTE DATEN verwenden
df_export = df_all[df_all["station"] == export_station]

time_valid = df_export["time"].dropna()

if time_valid.empty:
    st.warning("Keine Zeitdaten verfügbar")
else:
    with col2:
        start_date = st.datetime_input("Startzeit", time_valid.min())

    with col3:
        end_date = st.datetime_input("Endzeit", time_valid.max())

    export_df = df_export[
        (df_export["time"] >= pd.to_datetime(start_date)) &
        (df_export["time"] <= pd.to_datetime(end_date))
    ]

    if not export_df.empty:
        csv = export_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 CSV herunterladen", csv, f"{export_station}.csv")
    else:
        st.warning("Keine Daten im Zeitraum")
