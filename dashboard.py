import pandas as pd
import streamlit as st
import plotly.graph_objects as go
import requests
import io
import folium
from streamlit_folium import st_folium
import json
from datetime import datetime

# -----------------------------
# CONFIG
# -----------------------------

PARQUET_URL = "https://github.com/jogoetz/truppach-dashboard/raw/refs/heads/main/data.parquet"
GEOJSON_URL = "https://raw.githubusercontent.com/jogoetz/truppach-dashboard/main/catchments_simpl.geojson"

@st.cache_data
def load_geojson():
    r = requests.get(GEOJSON_URL)
    r.raise_for_status()
    return r.json()

geojson_data = load_geojson()

st.set_page_config(layout="wide")

# -----------------------------
# PASSWORT-SCHUTZ
# -----------------------------

def check_password():
    """Gibt True zurück, wenn das Passwort korrekt ist."""
    def password_entered():
        """Überprüft das eingegebene Passwort."""
        if st.session_state["password"] == "Truppach123!":  # Ändern Sie das Passwort hier
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("Bitte Passwort eingeben", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("Bitte Passwort eingeben", type="password", on_change=password_entered, key="password")
        st.error("❌ Falsches Passwort")
        return False
    else:
        return True

if check_password():
    st.title("🌊 Monitoring Truppach - Druck, Trübung, spez. Leitfähigkeit")

if "selected_station_map" not in st.session_state:
    st.session_state.selected_station_map = None

# -----------------------------
# WARTUNGSTAGE
# -----------------------------

maintenance_dates = pd.to_datetime([
    "02.07.2026","19.06.2026","03.06.2026","15.05.2026","30.04.2026","26.03.2026",
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
# Plankenfels
# -----------------------------

@st.cache_data(ttl=600)
def load_hnd_abfluss(today_str):
 
    url = "https://www.hnd.bayern.de/pegel/oberer_main_elbe/plankenfels-24244504/tabelle?methode=abfluss&begin=01.01.2025&end={today}&setdiskr=15"
    url = url.replace("{today}", today_str)
    
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
def load_behringersmuehle(today_str):

    url = "https://www.gkd.bayern.de/de/fluesse/schwebstoff/regnitz/behringersmuehle-24241710/gesamtzeitraum/tabelle?zr=gesamt&parameter=konzentration&parameterNr=14&beginn=01.01.2025&ende={today}"
    url = url.replace("{today}", today_str)
    
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

    df = df.dropna(subset=["time"])   # ✅ nur Zeit notwendig!

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

smooth_pressure = st.sidebar.slider("Glättung Druck (n, 5-Min Intervalle)", 1, 200, 10)
smooth_turbidity = st.sidebar.slider("Glättung Trübung (n, 5-Min Intervalle)", 1, 200, 10)
smooth_conductivity = st.sidebar.slider("Glättung Leitfähigkeit (n, 5-Min Intervalle)", 1, 200, 10)
min_gap = st.sidebar.slider("Min. Lücke (Minuten) Datenverfügbarkeit", 1, 1000, 10)
show_raw = st.sidebar.checkbox("Rohdaten anzeigen", False)
show_maintenance = st.sidebar.checkbox("Wartungstage anzeigen", False)
show_hnd = st.sidebar.checkbox("🌊 Abfluss Plankenfels", False)
show_bm_abfluss = st.sidebar.checkbox("🌊 Abfluss Behringersmühle", False)
show_bm_schweb  = st.sidebar.checkbox("🟤 Schwebstoff Behringersmühle", False)

scale_pressure = st.sidebar.radio("Skala Druck (psi)", ["linear", "log"], horizontal=True)
scale_turbidity = st.sidebar.radio("Skala Trübung (NTU)", ["linear", "log"], horizontal=True)
scale_conductivity = st.sidebar.radio("Skala spez. Leitfähigkeit (µS/cm)", ["linear", "log"], horizontal=True)

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

def format_duration(start, end):
    delta = end - start
    total_minutes = int(delta.total_seconds() // 60)

    days = total_minutes // (60 * 24)
    hours = (total_minutes % (60 * 24)) // 60
    minutes = total_minutes % 60

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")

    return " ".join(parts) if parts else "0m"

# -----------------------------
# PLOT
# -----------------------------

st.subheader("📈 Daten")
fig = go.Figure()

# ✅ FLAGS
use_y  = False
use_y2 = False
use_y3 = False
use_y4 = False
use_y5 = False
force_base_axis = False

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
    "Behringersmühle": "#9467bd",
}

# -----------------------------
# EIGENE DATEN
# -----------------------------

for (station, param), d in df.groupby(["station", "parameter"]):
    d = d.sort_values("time")
    color = color_map.get(station, "#888888")
    is_pressure = "Druck" in param
    is_turbidity = "Trübung" in param
    is_conductivity = "Leitfähigkeit" in param

    if is_pressure:
        window = smooth_pressure
        axis = "y"
        use_y = True

    elif is_turbidity:
        window = smooth_turbidity
        axis = "y2"
        use_y2 = True

    elif is_conductivity:
        window = smooth_conductivity
        axis = "y5"
        use_y5 = True

    else:
        window = 1
        axis = "y"

    y_smooth = smooth(d["value"], window)

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
        line=dict(
           color=color, 
           dash=(
               "dot" if is_pressure
                else "dash" if is_conductivity
                else "solid"
            )
        ),
        yaxis=axis
    ))

# -----------------------------
# EXTERNE DATEN
# -----------------------------

# Abfluss Plankenfels
if show_hnd:
    d = load_hnd_abfluss()
    if not d.empty:
        use_y3 = True
        fig.add_trace(go.Scatter(
            x=d["time"],
            y=d["abfluss"],
            name="Abfluss Plankenfels",
            yaxis="y3"
        ))

# Abfluss Behringersmühle
if show_bm_abfluss and df_bm is not None:
    d_abf = df_bm.dropna(subset=["time", "abfluss_bm"])
    if not d_abf.empty:
        use_y3 = True
        fig.add_trace(go.Scatter(
            x=d_abf["time"],
            y=d_abf["abfluss_bm"],
            name="Abfluss Behringersmühle",
            yaxis="y3",
            line=dict(color="black", width=2)
        ))

# Schwebstoff Behringersmühle
if show_bm_schweb and df_bm is not None:
    d_sch = df_bm.dropna(subset=["time", "schweb_bm"])
    if not d_sch.empty:
        use_y4 = True
        fig.add_trace(go.Scatter(
            x=d_sch["time"],
            y=d_sch["schweb_bm"],
            name="Schwebstoff Behringersmühle",
            yaxis="y4",
            line=dict(color="brown", width=2),
            opacity=0.8
        ))

# -----------------------------
# DUMMY TRACES (nur aktive Achsen!)
# -----------------------------

if not use_y and (use_y2 or use_y3 or use_y4 or use_y5):
    use_y = True
    force_base_axis = True

xmin = df_all["time"].min()
xmax = df_all["time"].max()

def add_dummy(axis):
    fig.add_trace(go.Scatter(
        x=[xmin, xmax],
        y=[0, 0],
        line=dict(color="rgba(0,0,0,0)"),
        showlegend=False,
        hoverinfo="skip",
        yaxis=axis
    ))

if use_y or force_base_axis:
    add_dummy("y")
if use_y2:
    add_dummy("y2")
if use_y3:
    add_dummy("y3")
if use_y4:
    add_dummy("y4")
if use_y5:
    add_dummy("y5")    

force_base_axis = False

# -----------------------------
# ACHSEN DYNAMISCH
# -----------------------------

layout_axes = {}

if use_y:
    layout_axes["yaxis"] = dict(
        title=dict(
             text="Druck (psi)",
             standoff=0
        ),
        side="left",
        type=scale_pressure,
        position=0.00,
        visible=not force_base_axis
    )

if use_y4:
    layout_axes["yaxis4"] = dict(
        title=dict(
             text="Schwebstoff (g/m³)",
             standoff=0
        ),
        overlaying="y",
        side="left",
        position=0.05
    )

if use_y2:
    layout_axes["yaxis2"] = dict(
        title=dict(
             text="Trübung (NTU)",
             standoff=0
        ),
        overlaying="y",
        side="right",
        position=0.95,
        type=scale_turbidity
    )

if use_y3:
    layout_axes["yaxis3"] = dict(
        title=dict(
             text="Abfluss (m³/s)",
             standoff=0
        ),
        overlaying="y",
        side="left",
        position=0.10
    )

if use_y5:
    layout_axes["yaxis5"] = dict(
        title=dict(
             text="Spez. Leitfähigkeit (µS/cm)",
             standoff=0
        ),
        overlaying="y",
        side="right",
        position=0.90,
        type=scale_conductivity
    )

# -----------------------------
# LAYOUT
# -----------------------------

latest_time = df_all["time"].max()
start_time = latest_time - pd.Timedelta(days=21)
fig.update_layout(
    height=650,
    xaxis=dict(title="Zeit", range=[start_time, latest_time], domain=[0.15, 0.85]),
    uirevision="constant",
    hovermode="x unified",
    margin=dict(l=50, r=180),
    **layout_axes
)

st.plotly_chart(fig, use_container_width=True)
# ✅ Stationen definieren
station_coords = {
    "Plankenfels": [49.8791219270009, 11.3350454717875],
    "Geislareuth": [49.92225187, 11.42177715],
    "Seitenbach": [49.9151933518834, 11.3986191898584],
    "Wehr": [49.91562086, 11.39690505],
    "Behringersmühle": [49.695227, 11.328322]
}

# ✅ DataFrame bauen
map_df = pd.DataFrame([
    {"station": s, "lat": coords[0], "lon": coords[1]}
    for s, coords in station_coords.items()
])

# -----------------------------
# ✅ FOLIUM KARTE
# -----------------------------

st.subheader("🗺️ Messstationen und Einzugsgebiete")

# Mittelpunkt
center_lat = map_df["lat"].mean()
center_lon = map_df["lon"].mean()

m = folium.Map(
    location=[center_lat, center_lon],
    zoom_start=10,
    tiles=None,
    control_scale=True
)

# ✅ Hintergrundlayer
folium.TileLayer(
    tiles="OpenStreetMap",
    name="🗺️ Karte",
    attr="© OpenStreetMap"
).add_to(m)

folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    name="🛰️ Orthophoto",
    attr="Tiles © Esri"
).add_to(m)

# ✅ Stationen
fg_stations = folium.FeatureGroup(name="📍 Stationen", show=True)

for _, row in map_df.iterrows():
    color = color_map.get(row["station"], "#666666")

    folium.CircleMarker(
        location=[row["lat"], row["lon"]],
        radius=8,
        color="black",
        weight=1,
        fill=True,
        fill_color=color,
        fill_opacity=0.95,
        tooltip=row["station"],
        popup=row["station"]
    ).add_to(fg_stations)

fg_stations.add_to(m)

# ✅ Mapping EZG → Station (für Farbe!)
ezg_to_station = {
    "EZG Geislareuth": "Geislareuth",
    "EZG Seitenbach": "Seitenbach",
    "EZG Wehr": "Wehr",
    "EZG Plankenfels": "Plankenfels",
    }

# ✅ EINZELNE FeatureGroups pro EZG
for ezg_name, station in ezg_to_station.items():

    color = color_map.get(station, "gray")

    fg = folium.FeatureGroup(
        name=f"📐 {ezg_name}",
        show=False
    )

    def style_function(feature, ezg_name=ezg_name, color=color):
        if feature["properties"]["GEBBEZ"] != ezg_name:
            return {"fillOpacity": 0, "opacity": 0}

        return {
            "fillColor": color,
            "color": color,
            "weight": 2,
            "fillOpacity": 0.4,
        }

    folium.GeoJson(
        geojson_data,
        style_function=style_function,
        tooltip=folium.GeoJsonTooltip(fields=["GEBBEZ"])
    ).add_to(fg)

    fg.add_to(m)

# ✅ LayerControl
folium.LayerControl(collapsed=False).add_to(m)

# -----------------------------
# ✅ LEGENDE
# -----------------------------

legend_items_stations = ""
for station, color in color_map.items():
    legend_items_stations += f"""
    <div>
        <span style="display:inline-block;width:12px;height:12px;
        background:{color};border-radius:50%;margin-right:6px;"></span>
        {station}
    </div>
    """

legend_items_polys = ""
for ezg, station in ezg_to_station.items():
    color = color_map.get(station, "gray")
    legend_items_polys += f"""
    <div>
        <span style="display:inline-block;width:12px;height:12px;
        background:{color};margin-right:6px;opacity:0.6;"></span>
        {ezg}
    </div>
    """

legend_html = f"""
<div style="
position: fixed;
bottom: 30px;
right: 30px;
z-index: 9999;
background-color: white;
padding: 12px 14px;
border-radius: 10px;
box-shadow: 0 2px 12px rgba(0,0,0,0.25);
font-size: 14px;
line-height: 1.5;
">

<b>📍 Stationen</b><br>
{legend_items_stations}

<hr style="margin:6px 0;">

<b>📐 Einzugsgebiete</b><br>
{legend_items_polys}

</div>
"""

m.get_root().html.add_child(folium.Element(legend_html))

# ✅ Anzeige
map_data = st_folium(m, height=700, use_container_width=True)

# ✅ Klick → Station filtern
if map_data and map_data.get("last_active_drawing"):
    props = map_data["last_active_drawing"]["properties"]

    if "GEBBEZ" in props:
        selected_area = props["GEBBEZ"]

        if selected_area in ezg_to_station:
            st.session_state.selected_station_map = ezg_to_station[selected_area]
            st.rerun()

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

        grouped["Dauer"] = grouped.apply(lambda r: format_duration(r["Start"], r["Ende"]), axis=1)

        grouped["station"] = station
        grouped["parameter"] = param

        results.append(grouped)

    return pd.concat(results, ignore_index=True)

def get_gaps(blocks, min_gap_minutes=10):
    gaps = []

    for (station, param), d in blocks.groupby(["station", "parameter"]):
        d = d.sort_values("Start").reset_index(drop=True)

        for i in range(len(d) - 1):
            gap_start = d.loc[i, "Ende"]
            gap_end = d.loc[i+1, "Start"]

            gap_minutes = (gap_end - gap_start).total_seconds() / 60

            # ✅ HIER ist der Filter
            if gap_minutes > min_gap_minutes:
                 gaps.append({
                    "station": station,
                    "parameter": param,
                    "Start": gap_start,
                    "Ende": gap_end,
                    "Dauer": format_duration(gap_start, gap_end)
                })

    return pd.DataFrame(gaps)

summary = get_time_blocks(df)
gaps = get_gaps(summary, min_gap)

show_gaps = st.checkbox("Nicht verfügbare Zeiträume anzeigen", True)

if show_gaps:
    gaps_display = gaps.copy()

    if not gaps_display.empty:

        # ✅ Spalten umbenennen
        gaps_display = gaps_display.rename(columns={
            "station": "Station",
            "parameter": "Parameter"
        })

        # ✅ Datum formatieren
        gaps_display["Start"] = gaps_display["Start"].dt.strftime("%Y-%m-%d %H:%M")
        gaps_display["Ende"] = gaps_display["Ende"].dt.strftime("%Y-%m-%d %H:%M")

        # ✅ Spalten REIHENFOLGE festlegen
        gaps_display = gaps_display[[
            "Station", "Parameter", "Start", "Ende", "Dauer"
        ]]

        st.dataframe(gaps_display, width="stretch")

    else:
        st.info("✅ Keine Datenlücken gefunden")

else:
    summary_display = summary.copy()

    # ✅ Spalten umbenennen
    summary_display = summary_display.rename(columns={
        "station": "Station",
        "parameter": "Parameter"
    })

    # ✅ Datum formatieren
    summary_display["Start"] = summary_display["Start"].dt.strftime("%Y-%m-%d %H:%M")
    summary_display["Ende"] = summary_display["Ende"].dt.strftime("%Y-%m-%d %H:%M")

    # ✅ gleiche Reihenfolge wie oben!
    summary_display = summary_display[[
        "Station", "Parameter", "Start", "Ende", "Dauer"
    ]]

    st.dataframe(summary_display, width="stretch")

