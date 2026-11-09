import pandas as pd
import numpy as np
import duckdb
import holoviews as hv
import panel as pn
import geoviews as gv
import geoviews.tile_sources as gvts
import gsw
import cartopy.crs as ccrs
import collections
import pathlib
import re
from io import BytesIO
from scipy.interpolate import griddata
import section_grid
from holoviews.operation import contours as hv_contours
from bokeh.models import HoverTool, ColumnDataSource, LinearAxis, Range1d, CustomJS
from bokeh.plotting import figure

# 1. ENGINE INITIALIZATION
pn.extension('tabulator')
hv.extension('bokeh')
gv.extension('bokeh')

# 2b. EXPORT STYLING
def _white_figure(fig):
    """Opaque white figure, so exported PNGs have no transparent (checkerboard) area."""
    fig.background_fill_color = 'white'
    fig.border_fill_color = 'white'
    # The dashboard theme sets border_fill_alpha = 0 (transparent).  Bokeh does not send a property that
    # equals its default (1.0), so the theme would win; 0.999 is sent and still exports fully opaque.
    fig.background_fill_alpha = 0.999
    fig.border_fill_alpha = 0.999
    fig.outline_line_color = '#888888'


def _white_background(plot, element):
    """HoloViews hook: opaque white figure with dark labels and title."""
    fig = plot.state
    _white_figure(fig)
    for ax in list(fig.xaxis) + list(fig.yaxis):
        ax.axis_label_text_color = '#222222'
        ax.major_label_text_color = '#222222'
    if fig.title is not None:
        fig.title.text_color = '#222222'


def _white_border(plot, element):
    """Opaque white border for exported PNGs, keeping the plot area's own colour (used for the map)."""
    fig = plot.state
    fig.border_fill_color = 'white'
    fig.border_fill_alpha = 0.999        # the theme sets 0; 0.999 is sent and still exports opaque


def _limit_map_zoom(plot, element):
    """Ocean Base has tiles only to about zoom 10 in many regions; stop there instead of showing blank tiles."""
    for r in plot.state.renderers:
        src = getattr(r, 'tile_source', None)
        if src is not None:
            src.max_zoom = 10


def _to_mercator(lon, lat):
    """WGS84 degrees -> Web Mercator metres (the projection of the web map tiles)."""
    r = 6378137.0
    return np.radians(lon) * r, np.log(np.tan(np.pi / 4 + np.radians(lat) / 2)) * r


# BokehJS paints the white backing of a multi-plot (grid) export without the browser's display-scaling
# factor, so at 125% Windows scaling only the top-left 80% of the PNG is filled and the toolbar corner
# exports transparent.  This one-time patch makes grid exports paint white behind everything.
_WHITE_EXPORT_JS = """
const M = Bokeh.Models.get('GridPlot');
const V = M && M.prototype.default_view;
if (V && !V.prototype.__white_export) {
  V.prototype.__white_export = true;
  const orig = V.prototype.export;
  V.prototype.export = function (...args) {
    const out = orig.apply(this, args);
    try {
      const c = out.canvas, ctx = out.ctx;
      if (c instanceof HTMLCanvasElement) {
        ctx.save(); ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.globalCompositeOperation = 'destination-over';
        ctx.fillStyle = 'white'; ctx.fillRect(0, 0, c.width, c.height); ctx.restore();
      }
    } catch (e) {}
    return out;
  };
}
"""
if pn.state.curdoc is not None:
    pn.state.curdoc.js_on_event('document_ready', CustomJS(code=_WHITE_EXPORT_JS))


# 2. DATABASE CONNECTION
BASE_DIR = pathlib.Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "processed" / "wf_ctd_eos80.duckdb"
TABLE_NAME = "ctd_data"

if not DB_PATH.exists():
    raise FileNotFoundError(f"Database not found at {DB_PATH}. Run main.py first.")

con = duckdb.connect(str(DB_PATH), read_only=True)

# Fetch Metadata
raw_cruises = con.execute(f"SELECT DISTINCT cruise_id FROM {TABLE_NAME} ORDER BY cruise_id").df()['cruise_id'].tolist()

default_cruise = raw_cruises[0]

# Data source: databases built by main.py --source ... hold raw (.hex) rows and
# SeaSoft-processed rows (downcast / upcast / fullcast) side by side.  Databases
# built before that have no data_source column; the selectors are then hidden.
HAS_SOURCE = 'data_source' in [r[1] for r in con.execute(f"PRAGMA table_info('{TABLE_NAME}')").fetchall()]
SOURCE_LABELS = {
    'raw': 'Raw (.hex)',
    'downcast': 'Processed downcast (.cnv)',
    'upcast': 'Processed upcast (.cnv)',
    'fullcast': 'Processed fullcast (.cnv)',
}
_SOURCE_ORDER = list(SOURCE_LABELS)


def _sources_for(cruise):
    """Data sources that have rows for this cruise, in display order."""
    if not HAS_SOURCE:
        return ['raw']
    found = con.execute(f"SELECT DISTINCT data_source FROM {TABLE_NAME} WHERE cruise_id = ?", (cruise,)).df()['data_source'].tolist()
    return [x for x in _SOURCE_ORDER if x in found] or ['raw']


def _directions_for(cruise, source):
    """Cast directions stored for this cruise and source ('down' first)."""
    if not HAS_SOURCE:
        return ['down']
    found = con.execute(
        f"SELECT DISTINCT cast_direction FROM {TABLE_NAME} WHERE cruise_id = ? AND data_source = ?",
        (cruise, source)).df()['cast_direction'].tolist()
    return [x for x in ('down', 'up') if x in found] or ['down']


_init_sources = _sources_for(default_cruise)
source_select = pn.widgets.Select(
    name='Data source', options={SOURCE_LABELS[x]: x for x in _init_sources}, value=_init_sources[0])
_init_dirs = _directions_for(default_cruise, _init_sources[0])
direction_select = pn.widgets.Select(
    name='Cast direction', options={'Downcast': 'down', 'Upcast': 'up'}, value=_init_dirs[0])
direction_select.options = {{'down': 'Downcast', 'up': 'Upcast'}[x]: x for x in _init_dirs}
direction_select.value = _init_dirs[0]
direction_select.visible = HAS_SOURCE and len(_init_dirs) > 1
source_select.visible = HAS_SOURCE


def _T():
    """Table expression for the selected data source and cast direction."""
    if not HAS_SOURCE:
        return TABLE_NAME
    src = source_select.value if source_select.value in SOURCE_LABELS else 'raw'
    dirn = direction_select.value if direction_select.value in ('down', 'up') else 'down'
    return f"(SELECT * FROM {TABLE_NAME} WHERE data_source = '{src}' AND cast_direction = '{dirn}')"


# Initialize default stations for the first cruise
raw_stations = con.execute(f"SELECT DISTINCT station_id FROM {_T()} WHERE cruise_id = ?", (default_cruise,)).df()['station_id'].tolist()
stations = sorted(raw_stations, key=lambda x: int(re.findall(r'\d+', x)[-1]) if re.findall(r'\d+', x) else 0)

# 3. GLOBAL WIDGETS
cruise_select = pn.widgets.Select(name='Cruise ID', options=raw_cruises, value=default_cruise)
station_select = pn.widgets.Select(name='Station ID', options=stations, value=stations[0] if stations else None)
depth_slider = pn.widgets.RangeSlider(name='Depth Range (m)', start=0, end=1000, value=(0, 600), step=1.0)
qc_checkbox = pn.widgets.Checkbox(name='Filter QC (Flag < 3)', value=False)
soak_toggle = pn.widgets.Checkbox(name='Show Soak Data (Surface)', value=False)

# Callback to update stations when cruise changes
def update_stations(event):
    new_cruise = cruise_select.value
    new_stations = con.execute(f"SELECT DISTINCT station_id FROM {_T()} WHERE cruise_id = ?", (new_cruise,)).df()['station_id'].tolist()
    sorted_stations = sorted(new_stations, key=lambda x: int(re.findall(r'\d+', x)[-1]) if re.findall(r'\d+', x) else 0)
    keep = station_select.value
    station_select.options = sorted_stations
    if sorted_stations:
        station_select.value = keep if keep in sorted_stations else sorted_stations[0]

_refreshing = False


def _set_direction_options(cruise, source):
    dirs = _directions_for(cruise, source)
    direction_select.options = {{'down': 'Downcast', 'up': 'Upcast'}[x]: x for x in dirs}
    if direction_select.value not in dirs:
        direction_select.value = dirs[0]
    direction_select.visible = HAS_SOURCE and len(dirs) > 1


def _on_cruise_for_source(event):
    """A new cruise may offer different sources / directions."""
    global _refreshing
    _refreshing = True
    try:
        srcs = _sources_for(event.new)
        source_select.options = {SOURCE_LABELS[x]: x for x in srcs}
        if source_select.value not in srcs:
            source_select.value = srcs[0]
        _set_direction_options(event.new, source_select.value)
    finally:
        _refreshing = False


def _on_source_or_direction(event):
    """Source or direction changed: refresh everything that depends on the cruise."""
    if _refreshing:
        return
    if event.obj is source_select:
        _set_direction_options(cruise_select.value, source_select.value)
    # Re-fire the cruise dependency so every bound view, the station list and
    # the section station list re-query with the new source.
    cruise_select.param.trigger('value')


if HAS_SOURCE:
    # Registered first so the source/direction options are valid for the new cruise
    # before update_stations and the bound views query.
    cruise_select.param.watch(_on_cruise_for_source, 'value')
cruise_select.param.watch(update_stations, 'value')
if HAS_SOURCE:
    source_select.param.watch(_on_source_or_direction, 'value')
    direction_select.param.watch(_on_source_or_direction, 'value')

# 4. DATA LOGIC
@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak):
    if not target_id: return pd.DataFrame()
    qc_clause = "AND qc_flag < 3" if filter_qc else ""
    soak_clause = "" if show_soak else "AND is_soak = 0"
    query = f"""
        SELECT * FROM {_T()}
        WHERE cruise_id = ?
        AND station_id = ?
        AND dbar_bin BETWEEN ? AND ?
        {soak_clause}
        {qc_clause} ORDER BY dbar_bin ASC
    """
    df = con.execute(query, (target_cruise, target_id, z_range[0], z_range[1])).df()
    if df.empty or 'theta' not in df.columns: return df

    # EOS-80 Analytics
    df['sigma'] = df['rho'] - 1000
    # theta is stored as IPTS-68 (used by EOS-80 equations); gsw functions
    # expect ITS-90 potential temperature, so convert here for derived quantities.
    theta_90 = df['theta'] / 1.00024
    df['sat_o2'] = gsw.O2sol_SP_pt(df['SP'], theta_90)
    df['AOU'] = df['sat_o2'] - df['o2_final']

    # Metabolic Index (Phi) — uses ITS-90 potential temperature in Arrhenius term
    k, Eo = 8.617e-5, 0.45
    df['phi'] = (df['o2_final'] / np.exp(-Eo / (k * (theta_90 + 273.15)))) / 1e6

    # CHL cannot be negative — truncate to 0 (Gaussian smoothing can push
    # near-zero values slightly below zero at the base of the DCM).
    if 'chl_final' in df.columns:
        df['chl_final'] = df['chl_final'].clip(lower=0.0)

    return df

def download_csv():
    df = get_clean_df(cruise_select.value, station_select.value, depth_slider.value, qc_checkbox.value, soak_toggle.value)
    sio = BytesIO()
    df.to_csv(sio, index=False); sio.seek(0)
    return sio

csv_button = pn.widgets.FileDownload(callback=download_csv, filename='CTD_Export.csv', label='Export CSV', button_type='primary', sizing_mode='stretch_width')

# 5. TAB FUNCTIONS
def _cruise_summary_impl(target_cruise):
    query = f"""
        SELECT station_id as "Station ID", wf_cast as "WF #", sb_cast as "SB #",
        MIN(lat) as "Lat", MIN(lon) as "Lon", MIN(time_iso)::TIMESTAMP as "Start Time",
        CAST(MAX(depth_m) AS DECIMAL(10,1)) as "Max Depth (m)",
        ROUND((SUM(CASE WHEN qc_flag = 1 THEN 1 ELSE 0 END) * 100.0) / COUNT(*), 1) as "Health %"
        FROM {_T()} WHERE cruise_id = ?
        GROUP BY station_id, wf_cast, sb_cast ORDER BY "Start Time" ASC
    """
    df_sum = con.execute(query, (target_cruise,)).df()
    config = {'columns': [{'field': 'Health %', 'formatter': 'progress', 'formatterParams': {'color': '#28a745', 'legend': True}}]}
    table = pn.widgets.Tabulator(df_sum, theme='midnight', show_index=False, sizing_mode='stretch_both', configuration=config)
    return pn.Column("# Cruise Summary", table, sizing_mode='stretch_both')

view_cruise_summary = pn.Column(
    pn.bind(_cruise_summary_impl, cruise_select),
    sizing_mode='stretch_both'
)

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_profiles(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("Data Pending...")
    v_opts = dict(invert_yaxis=True, height=550, show_grid=True, xaxis='top', tools=['hover'], xticks=3, padding=0.05,
                  line_width=2.5, fontsize={'labels': '8pt', 'xticks': '7pt', 'yticks': '7pt', 'legend': '7pt'},
                  hooks=[_white_background])

    p1 = hv.Curve(df, 'theta', 'depth_m', label='Pot. Temp').opts(**v_opts, color='cyan', width=175, xlabel='theta (°C)')
    p6 = hv.Curve(df, 'in_situ_temp', 'depth_m', label='In-Situ Temp').opts(**v_opts, color='blue', width=140, yaxis=None, xlabel='T (°C)')
    p2 = hv.Curve(df, 'SP', 'depth_m', label='Prac. Sal').opts(**v_opts, color='red', width=140, yaxis=None, xlabel='SP (PSU)')
    p3 = hv.Curve(df, 'o2_final', 'depth_m', label='O2').opts(**v_opts, color='black', width=155, yaxis=None, xlabel='O2 (µmol/kg)')
    p4 = hv.Curve(df, 'ph_final', 'depth_m', label='pH').opts(**v_opts, color='goldenrod', width=125, yaxis=None, xlabel='pH')
    p5 = hv.Curve(df, 'chl_final', 'depth_m', label='Chl').opts(**v_opts, color='green', width=125, yaxis=None, xlabel='Chl (mg/m³)')

    layout = (p1 + p6 + p2 + p3 + p4 + p5).cols(6).opts(shared_axes=True, merge_tools=True)
    # The merged toolbar sits in the grid's own header strip, outside every figure, so the per-figure hook
    # cannot reach it and the exported PNG shows a transparent (checkerboard) header.  The grid's export
    # fills with its CSS background, so render to a bokeh GridPlot and give that a white background.
    grid = hv.render(layout, backend='bokeh')
    grid.background = 'white'
    grid.toolbar.styles = {'background-color': 'white'}   # the toolbar box (upper right) too
    return pn.pane.Bokeh(grid)

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_multi_profile(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("Data Pending...")

    source = ColumnDataSource(df)

    def get_range(col):
        m, M = df[col].min(), df[col].max()
        if pd.isna(m) or pd.isna(M):
            return Range1d(0, 1)
        if m == M:
            return Range1d(m - 1, m + 1)
        padding = (M - m) * 0.05
        return Range1d(m - padding, M + padding)

    # Base figure
    p = figure(height=700, width=800,
               y_axis_label='Depth (m)',
               y_range=Range1d(df['depth_m'].max(), df['depth_m'].min()),
               toolbar_location="right",
               tools="pan,wheel_zoom,box_zoom,reset,save")

    p.xaxis.visible = False # Hide default xaxis

    # Define extra ranges
    p.extra_x_ranges = {
        "ph": get_range('ph_final'),
        "o2": get_range('o2_final'),
        "sal": get_range('SP'),
        "temp": get_range('in_situ_temp'),
        "chl": get_range('chl_final'),
    }

    # Add lines
    p.line('ph_final', 'depth_m', source=source, x_range_name="ph", color='goldenrod', line_width=2.5, legend_label='pH')
    p.line('o2_final', 'depth_m', source=source, x_range_name="o2", color='black', line_width=2.5, legend_label='Oxygen')
    p.line('SP', 'depth_m', source=source, x_range_name="sal", color='red', line_width=2.5, legend_label='Salinity')
    p.line('in_situ_temp', 'depth_m', source=source, x_range_name="temp", color='blue', line_width=2.5, legend_label='In-Situ Temp')
    p.line('chl_final', 'depth_m', source=source, x_range_name="chl", color='green', line_width=2.5, legend_label='Chlorophyll')

    # Top axes (from top to bottom: pH, Oxygen, Salinity)
    # Bokeh stacks axes outward from the plot.
    # To get pH (top), Oxygen (middle), Salinity (bottom/closest to plot) on top of the plot:
    # 1. Salinity (added first, closest)
    # 2. Oxygen
    # 3. pH (added last, furthest)
    p.add_layout(LinearAxis(x_range_name="sal", axis_label="Salinity (PSU)",
                            axis_label_text_color="red", axis_line_color="red",
                            major_label_text_color="red", major_tick_line_color="red"), 'above')
    p.add_layout(LinearAxis(x_range_name="o2", axis_label="Oxygen (µmol/kg)",
                            axis_label_text_color="black", axis_line_color="black",
                            major_label_text_color="black", major_tick_line_color="black"), 'above')
    p.add_layout(LinearAxis(x_range_name="ph", axis_label="pH",
                            axis_label_text_color="goldenrod", axis_line_color="goldenrod",
                            major_label_text_color="goldenrod", major_tick_line_color="goldenrod"), 'above')

    # Bottom axes (from top to bottom: Temperature, Chlorophyll)
    # "top to bottom" for bottom axes means Temperature is closer to the plot than Chlorophyll.
    # 1. Temperature (added first, closest)
    # 2. Chlorophyll (added last, furthest)
    p.add_layout(LinearAxis(x_range_name="temp", axis_label="Temperature (°C)",
                            axis_label_text_color="blue", axis_line_color="blue",
                            major_label_text_color="blue", major_tick_line_color="blue"), 'below')
    p.add_layout(LinearAxis(x_range_name="chl", axis_label="Chlorophyll (mg/m³)",
                            axis_label_text_color="green", axis_line_color="green",
                            major_label_text_color="green", major_tick_line_color="green"), 'below')

    hover = HoverTool(tooltips=[
        ("Depth", "@depth_m{0.1} m"),
        ("pH", "@ph_final{0.00}"),
        ("Oxygen", "@o2_final{0.1}"),
        ("Salinity", "@SP{0.00}"),
        ("Temp", "@in_situ_temp{0.2}"),
        ("Chl", "@chl_final{0.2}"),
    ], mode='vline')
    p.add_tools(hover)

    p.legend.location = "top_left"
    p.legend.click_policy = "hide"
    p.legend.label_text_font_size = "8pt"
    p.legend.background_fill_alpha = 0.5

    _white_figure(p)
    return p

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_ts_analysis(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("Data Null")
    return hv.Points(df, ['SP', 'theta'], ['depth_m', 'sigma']).opts(
        color='depth_m', cmap='Viridis_r', width=600, height=500, colorbar=True, title="T-S Analysis (EOS-80)", tools=['hover'],
        hooks=[_white_background]
    )

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_aou(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("No Data")
    opts = dict(invert_yaxis=True, height=550, width=600, show_grid=True, tools=['hover'])
    sat_l = hv.Curve(df, 'sat_o2', 'depth_m', label='Sat. Cap').opts(**opts, color='black', line_dash='dashed')
    o2_l = hv.Curve(df, 'o2_final', 'depth_m', label='Observed').opts(**opts, color='cyan')
    fill = hv.Area(df, ('sat_o2', 'o2_final'), 'depth_m', label='AOU').opts(**opts, color='orange', alpha=0.3)
    return (fill * sat_l * o2_l).opts(title="Apparent Oxygen Utilization (AOU)", hooks=[_white_background])

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_stability(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("No Data")
    surf = df['sigma'].iloc[0]
    opts = dict(invert_yaxis=True, height=500, width=400, tools=['hover'], hooks=[_white_background])
    density_curve = hv.Curve(df, 'sigma', 'depth_m', label='Density').opts(**opts, color='blue')
    # Guard against fully-mixed profiles: only draw MLD line if threshold is crossed
    over_threshold = (df['sigma'] - surf) > 0.03
    if over_threshold.any():
        mld_v = df.loc[over_threshold.idxmax(), 'depth_m']
        density_panel = (density_curve * hv.HLine(mld_v).opts(color='red')).opts(hooks=[_white_background])
    else:
        density_panel = density_curve
    return pn.Row(density_panel,
                  hv.Area(df, 'o2_final', 'depth_m', label='Oxygen Concentration').opts(**opts, color='magenta', alpha=0.2))

@pn.depends(cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle)
def view_metabolic_index(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty: return pn.pane.Alert("No Data")
    return (hv.Curve(df, 'phi', 'depth_m', label='Φ').opts(color='#e67e22', invert_yaxis=True, height=550, width=500, tools=['hover']) * hv.VLine(1.0).opts(color='red', line_dash='dashed')).opts(hooks=[_white_background])

STATION_COLORS = {'selected station': '#ff1a1a', 'other stations': '#ffb000'}


@pn.depends(cruise_select, station_select)
def view_map_geolocation(target_cruise, target_id):
    """Station positions on the Esri Ocean Base map: the selected station in red, the others in amber."""
    st = con.execute(f"SELECT station_id, AVG(lat) AS lat, AVG(lon) AS lon FROM {_T()} "
                     "WHERE cruise_id = ? AND lat IS NOT NULL AND lon IS NOT NULL GROUP BY station_id", (target_cruise,)).df()
    if st.empty:
        return pn.pane.Alert('No station positions for this cruise.', alert_type='warning')
    st['x'], st['y'] = _to_mercator(st['lon'].to_numpy(float), st['lat'].to_numpy(float))
    st['status'] = np.where(st['station_id'] == target_id, 'selected station', 'other stations')
    st = st.sort_values('status', key=lambda c: c.map({'other stations': 0, 'selected station': 1})).reset_index(drop=True)   # selected drawn last
    pts = hv.Points(st, kdims=['x', 'y'], vdims=['station_id', 'lat', 'lon', 'status']).opts(
        color='status', cmap=STATION_COLORS, size=13, line_color='white', line_width=1.5,
        tools=['hover'], show_legend=True, legend_position='bottom_left')
    # Start with a sensible view: all stations, and at least about 80 km around them so that a single
    # station does not zoom in beyond the imagery ("Map data not yet available").
    xs, ys = st['x'].to_numpy(), st['y'].to_numpy()
    half_min = 80000.0 / np.cos(np.radians(float(st['lat'].mean())))
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    hx, hy = max((xs.max() - xs.min()) * 0.6, half_min), max((ys.max() - ys.min()) * 0.6, half_min)
    plot = (gvts.EsriOceanBase * gvts.EsriOceanReference * pts).opts(
        responsive=True, min_height=620, xaxis=None, yaxis=None, active_tools=['wheel_zoom'],
        xlim=(cx - hx, cx + hx), ylim=(cy - hy, cy + hy),
        bgcolor='#0b1a2b',   # dark backdrop, shown if the map tiles cannot load
        title='Station positions', hooks=[_white_border, _limit_map_zoom])
    return pn.pane.HoloViews(plot, sizing_mode='stretch_both')

# ── Section plot helpers ───────────────────────────────────────────────────────
def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two coordinate pairs in kilometres."""
    R = 6371.0
    dlat = np.radians(lat2 - lat1)
    dlon = np.radians(lon2 - lon1)
    a = (np.sin(dlat / 2) ** 2
         + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon / 2) ** 2)
    return 2 * R * np.arcsin(np.sqrt(a))

_SECTION_VARS = {
    'Pot. Temperature (°C)': ('theta',        'RdBu_r',  '°C'),
    'In-Situ Temp (°C)':     ('in_situ_temp', 'RdBu_r',  '°C'),
    'Practical Salinity':    ('SP',           'viridis', 'PSU'),
    'Density σ (kg/m³)':     ('sigma',        'viridis', 'kg/m³'),
    'Oxygen (µmol/kg)':      ('o2_final',     'plasma',  'µmol/kg'),
    'pH':                    ('ph_final',     'RdYlBu',  ''),
    'Chlorophyll (mg/m³)':   ('chl_final',    'Greens',  'mg/m³'),
}

section_var_select = pn.widgets.Select(
    name='Section Variable',
    options=list(_SECTION_VARS.keys()),
    value='Pot. Temperature (°C)',
    width=230,
)

# Section geometry, in the spirit of Ocean Data View: choose the stations, the x axis, and how far to grid across gaps.
_SECTION_AXES = {
    'Distance along section (km)':       'distance',   # stations projected onto the best-fit line through them
    'Longitude (°)':                     'lon',
    'Latitude (°)':                      'lat',
    'Time (days since first station)':   'time',
    'Distance Along Track (km)':         'track',      # the original view: time order, summed hops between stations
}
_SECTION_GRIDS = {'Weighted average (ODV-style)': 'wavg', 'Linear triangulation': 'linear'}
section_grid_select = pn.widgets.Select(name='Gridding', options=list(_SECTION_GRIDS), value='Weighted average (ODV-style)', width=230)
section_lx_slider = pn.widgets.FloatSlider(name='Horizontal scale (% of x range)', start=0.5, end=30, value=5, step=0.5, width=230)
section_ly_slider = pn.widgets.FloatSlider(name='Depth scale (% of depth range)', start=0.5, end=20, value=2, step=0.5, width=230)


def _section_grid_visibility(event=None):
    on = _SECTION_GRIDS[section_grid_select.value] == 'wavg'
    section_lx_slider.visible = on
    section_ly_slider.visible = on


section_grid_select.param.watch(_section_grid_visibility, 'value')
section_axis_select = pn.widgets.Select(name='X axis', options=list(_SECTION_AXES), value='Distance along section (km)', width=230)
section_gap_slider = pn.widgets.IntSlider(name='Blank gaps wider than (km; 0 = off)', start=0, end=500, value=100, step=10, width=230)
section_station_select = pn.widgets.MultiSelect(name='Stations in section', options=stations, value=list(stations), size=10, width=230)
section_all_btn = pn.widgets.Button(name='All', width=70)
section_none_btn = pn.widgets.Button(name='None', width=70)

# Narrow a long station list: by name and by date.  Applying a filter lists only the
# matching stations and selects them all; "All" then selects the stations listed.
section_name_filter = pn.widgets.TextInput(name='Name contains', placeholder='type, then press Enter', width=230)
section_date_from = pn.widgets.DatePicker(name='From date (UTC)', width=112)
section_date_to = pn.widgets.DatePicker(name='To date (UTC)', width=112)
_section_filter_busy = False


def _station_sort_key(x):
    n = re.findall(r'\d+', x)
    return int(n[-1]) if n else 0


def _cruise_station_info(cruise):
    """One row per station of the cruise (current source): station_id, station_name, first time."""
    return con.execute(
        f"SELECT station_id, ANY_VALUE(station_name) AS station_name, MIN(time_iso) AS t "
        f"FROM {_T()} WHERE cruise_id = ? GROUP BY station_id", (cruise,)).df()


def _cruise_station_list(cruise):
    ids = _cruise_station_info(cruise)['station_id'].tolist()
    return sorted(ids, key=_station_sort_key)


def _filtered_station_list(cruise):
    """Station ids of the cruise that pass the name and date filters, in station order."""
    info = _cruise_station_info(cruise)
    keep = pd.Series(True, index=info.index)
    name = (section_name_filter.value or '').strip()
    if name:
        keep &= (info['station_name'].astype(str).str.contains(name, case=False, regex=False)
                 | info['station_id'].astype(str).str.contains(name, case=False, regex=False))
    t = pd.to_datetime(info['t'], utc=True, errors='coerce').dt.tz_localize(None)
    if section_date_from.value:
        keep &= t >= pd.Timestamp(section_date_from.value)
    if section_date_to.value:
        keep &= t < pd.Timestamp(section_date_to.value) + pd.Timedelta(days=1)
    return sorted(info.loc[keep, 'station_id'].tolist(), key=_station_sort_key)


def _apply_section_filter(event=None):
    if _section_filter_busy:
        return
    ids = _filtered_station_list(cruise_select.value)
    # One update, so the section and its map redraw once.
    section_station_select.param.update(options=ids, value=list(ids))


def _section_stations_for_cruise(event):
    """A new cruise (or source) clears the filters and starts with every station."""
    global _section_filter_busy
    _section_filter_busy = True
    try:
        info = _cruise_station_info(event.new)
        t = pd.to_datetime(info['t'], utc=True, errors='coerce').dt.tz_localize(None).dropna()
        lo = t.min().date() if len(t) else None
        hi = t.max().date() if len(t) else None
        section_name_filter.value = ''
        section_date_from.param.update(start=lo, end=hi, value=None)
        section_date_to.param.update(start=lo, end=hi, value=None)
    finally:
        _section_filter_busy = False
    ids = sorted(info['station_id'].tolist(), key=_station_sort_key)
    section_station_select.param.update(options=ids, value=list(ids))


def _section_select_all(event):
    section_station_select.value = list(section_station_select.options)


def _section_select_none(event):
    section_station_select.value = []


cruise_select.param.watch(_section_stations_for_cruise, 'value')
section_name_filter.param.watch(_apply_section_filter, 'value')
section_date_from.param.watch(_apply_section_filter, 'value')
section_date_to.param.watch(_apply_section_filter, 'value')
section_all_btn.on_click(_section_select_all)
section_none_btn.on_click(_section_select_none)


def _section_positions(sta, mode):
    """x position of each station (rows of ``sta``: lat, lon, t) for one x-axis mode, in that axis's units."""
    if mode == 'lon':
        return sta['lon'].astype(float)
    if mode == 'lat':
        return sta['lat'].astype(float)
    if mode == 'time':
        t = pd.to_datetime(sta['t'], utc=True, errors='coerce')
        return (t - t.min()).dt.total_seconds() / 86400.0
    if mode == 'track':                                # original behaviour: time order, summed hops between stations
        ordered = sta.assign(_t=pd.to_datetime(sta['t'], utc=True, errors='coerce')).sort_values('_t')
        lats, lons = ordered['lat'].to_numpy(float), ordered['lon'].to_numpy(float)
        cum = np.zeros(len(ordered))
        for i in range(1, len(ordered)):
            cum[i] = cum[i - 1] + _haversine_km(lats[i - 1], lons[i - 1], lats[i], lons[i])
        return pd.Series(cum, index=ordered.index)
    # 'distance': project the stations onto the straight line that fits them best, measured from one end
    lat0, lon0 = float(sta['lat'].mean()), float(sta['lon'].mean())
    yk = (sta['lat'].to_numpy(float) - lat0) * 111.19
    xk = (sta['lon'].to_numpy(float) - lon0) * 111.19 * np.cos(np.radians(lat0))
    pts = np.column_stack([xk, yk])
    _, _, vt = np.linalg.svd(pts - pts.mean(axis=0), full_matrices=False)
    v = vt[0]
    if (abs(v[1]) >= abs(v[0]) and v[1] < 0) or (abs(v[1]) < abs(v[0]) and v[0] < 0):
        v = -v                                          # start at the southern end (or western end for an east-west line)
    proj = pts @ v
    return pd.Series(proj - proj.min(), index=sta.index)


# Rows for the section, fetched only for the chosen stations and kept for the next few redraws.
# Changing the variable, x axis or gap setting reuses them instead of querying again.
_SECTION_CACHE = collections.OrderedDict()
_SECTION_CACHE_MAX = 4


def _section_rows(cruise, stations, z0, z1, qc):
    """Rows (without soak) of the chosen stations, with sigma added.  ``stations`` is a sorted
    tuple, or None for every station of the cruise.  Treat the result as read-only."""
    key = (_T(), cruise, stations, z0, z1, qc)
    if key in _SECTION_CACHE:
        _SECTION_CACHE.move_to_end(key)
        return _SECTION_CACHE[key]
    qc_clause = "AND qc_flag < 3" if qc else ""
    station_clause = "AND list_contains(?, station_id)" if stations is not None else ""
    params = [cruise, z0, z1] + ([list(stations)] if stations is not None else [])
    df = con.execute(f"""
        SELECT station_id, station_name, lat, lon, time_iso, depth_m, dbar_bin,
               theta, in_situ_temp, SP, rho, o2_final, ph_final, chl_final
        FROM {_T()}
        WHERE cruise_id = ?
        AND dbar_bin BETWEEN ? AND ?
        AND is_soak = 0
        {station_clause}
        {qc_clause}
        ORDER BY station_id, dbar_bin ASC
    """, params).df()
    # Always compute sigma — needed for isopycnal contours regardless of variable
    df['sigma'] = df['rho'] - 1000
    _SECTION_CACHE[key] = df
    while len(_SECTION_CACHE) > _SECTION_CACHE_MAX:
        _SECTION_CACHE.popitem(last=False)
    return df


def _section_impl(target_cruise, z_range, filter_qc, section_var_label, chosen_stations, axis_label, gap_km,
                  grid_label='Weighted average (ODV-style)', lx_pct=5.0, ly_pct=2.0):
    col, cmap, unit = _SECTION_VARS[section_var_label]
    if not chosen_stations:
        return pn.pane.Alert("Choose at least two stations for the section.", alert_type='warning')

    # Fetch only the chosen stations.  A stale list from another cruise matches nothing: use every station.
    chosen_key = tuple(sorted(chosen_stations))
    df = _section_rows(target_cruise, chosen_key, z_range[0], z_range[1], bool(filter_qc))
    if df.empty:
        df = _section_rows(target_cruise, None, z_range[0], z_range[1], bool(filter_qc))
    if df.empty:
        return pn.pane.Alert("No data available for section plot.")
    df = df.copy()                                  # the cached rows stay untouched

    if col not in df.columns:
        return pn.pane.Alert(f"Column '{col}' not found in data.")

    if df['station_id'].nunique() < 2:
        return pn.pane.Alert("Choose at least two stations for the section.", alert_type='warning')

    # Position of every station along the chosen x axis, and the order they fall in
    mode = _SECTION_AXES[axis_label]
    sta = df.groupby('station_id').agg(lat=('lat', 'first'), lon=('lon', 'first'), t=('time_iso', 'min'))
    x_sta = _section_positions(sta, mode).dropna()
    sta = sta.loc[x_sta.index]
    if len(x_sta) < 2 or x_sta.nunique() < 2:
        return pn.pane.Alert("These stations do not span a range on that x axis; choose another axis or more stations.",
                             alert_type='warning')
    station_order = x_sta.sort_values().index.tolist()
    cum_dist = x_sta.loc[station_order].to_numpy(float)          # x position of each station, in order
    df['dist_km'] = df['station_id'].map(x_sta.to_dict())

    # Stretches between neighbouring stations that are too far apart to grid across
    lats_o, lons_o = sta.loc[station_order, 'lat'].to_numpy(float), sta.loc[station_order, 'lon'].to_numpy(float)
    gaps = []
    if gap_km and gap_km > 0:
        for i in range(len(station_order) - 1):
            if _haversine_km(lats_o[i], lons_o[i], lats_o[i + 1], lons_o[i + 1]) > gap_km:
                gaps.append((cum_dist[i], cum_dist[i + 1]))

    # Base (x, y) grid — shared by main variable and sigma
    x_all = df['dist_km'].values.astype(float)
    y_all = df['depth_m'].values.astype(float)
    base_mask = ~(np.isnan(x_all) | np.isnan(y_all))

    # ── Main variable ─────────────────────────────────────────────────────────
    z = df[col].values.astype(float)
    mask = base_mask & ~np.isnan(z)
    xm, ym, zm = x_all[mask], y_all[mask], z[mask]

    if len(xm) < 10:
        return pn.pane.Alert("Insufficient data for section interpolation.")

    # Regular 300 × 200 grid
    xi = np.linspace(xm.min(), xm.max(), 300)
    yi = np.linspace(ym.min(), ym.max(), 200)
    Xi, Yi = np.meshgrid(xi, yi)
    # Scale both axes to 0..1 for the triangulation, so a tiny range (degrees) is not squashed against metres.
    sx, sy = max(float(np.ptp(xm)), 1e-9), max(float(np.ptp(ym)), 1e-9)
    grid_method = _SECTION_GRIDS.get(grid_label, 'wavg')
    if grid_method == 'wavg':
        # ODV-style weighted average on the section grid (see section_grid.py).
        st_index = {s_id: i for i, s_id in enumerate(station_order)}
        row_st = df['station_id'].map(st_index).to_numpy(dtype=float)
        row_st = np.where(np.isnan(row_st), -1, row_st).astype(int)
        lx = section_grid.effective_horizontal_scale(cum_dist, np.ptp(xm), lx_pct)
        ly = max(float(np.ptp(ym)) * float(ly_pct) / 100.0, 1e-9)

        def _grid_field(vals, ok):
            return section_grid.weighted_average_grid(
                cum_dist, row_st[ok], y_all[ok], vals[ok], xi, yi, lx, ly)
        Zi = _grid_field(z, mask)
    else:
        Zi = griddata((xm / sx, ym / sy), zm, (Xi / sx, Yi / sy), method='linear')

    def _blank_gaps(Z):
        for g0, g1 in gaps:
            Z[:, (xi > g0) & (xi < g1)] = np.nan
        return Z
    Zi = _blank_gaps(Zi)

    vmin = np.nanpercentile(zm, 2)
    vmax = np.nanpercentile(zm, 98)
    label = section_var_label + (f' [{unit}]' if unit else '')

    img = hv.Image(
        (xi, yi, Zi),
        kdims=[axis_label, 'Depth (m)'],
        vdims=[label],
    ).opts(
        cmap=cmap, colorbar=True, clim=(vmin, vmax),
        width=900, height=500, invert_yaxis=True,
        tools=['hover'],
        title=f"{section_var_label} Section — {target_cruise}",
        fontsize={'title': '10pt', 'labels': '9pt', 'xticks': '8pt', 'yticks': '8pt'},
    )

    # ── Isopycnal contours (σθ, every 0.5 kg/m³) ─────────────────────────────
    s_vals = df['sigma'].values.astype(float)
    s_mask = base_mask & ~np.isnan(s_vals)
    if grid_method == 'wavg':
        Zi_sigma = _blank_gaps(_grid_field(s_vals, s_mask))
    else:
        Zi_sigma = _blank_gaps(griddata(
            (x_all[s_mask] / sx, y_all[s_mask] / sy), s_vals[s_mask], (Xi / sx, Yi / sy), method='linear'
        ))
    s_clean = Zi_sigma[~np.isnan(Zi_sigma)]
    if len(s_clean) > 0:
        lvl_min = np.ceil(s_clean.min() * 2) / 2
        lvl_max = np.floor(s_clean.max() * 2) / 2
        levels = np.arange(lvl_min, lvl_max + 0.5, 0.5).tolist()
    else:
        levels = 10

    sigma_img = hv.Image(
        (xi, yi, Zi_sigma),
        kdims=[axis_label, 'Depth (m)'],
        vdims=['sigma'],
    )
    iso = hv_contours(sigma_img, levels=levels).opts(
        line_color='black', line_width=0.9, show_legend=False
    )

    # ── Station marker lines ──────────────────────────────────────────────────
    # One element for all stations (one VLine per station took tens of seconds with 1,500 stations).
    sta_lines = hv.VLines(list(map(float, cum_dist))).opts(
        color='white', line_width=0.8, line_dash='dashed', alpha=0.5)

    # ── Station hover markers (triangle at surface, shows name on hover) ────────
    sta_names = df.groupby('station_id')['station_name'].first()
    marker_depth = yi.min() + (yi.max() - yi.min()) * 0.02
    sta_hover = hv.Points(
        pd.DataFrame({
            axis_label:                  cum_dist,
            'Depth (m)':                 np.full(len(station_order), marker_depth),
            'Station':                   [sta_names.get(s, s) for s in station_order],
        }),
        kdims=[axis_label, 'Depth (m)'],
        vdims=['Station'],
    ).opts(
        color='white', size=7, marker='triangle', show_legend=False,
        tools=[HoverTool(tooltips=[
            ('Station',                   '@{Station}'),
            (axis_label,                  '@{' + axis_label + '}'),
            ('Depth (m)',                 '@{Depth (m)}'),
        ])],
    )

    return (img * iso * sta_lines * sta_hover).opts(show_grid=False, hooks=[_white_background])

SECTION_MAP_COLORS = {'other stations': '#8a8a8a', 'in section': '#ffb000', 'section start': '#2ca02c'}
SECTION_MAP_W, SECTION_MAP_H = 440, 520


def _section_map_impl(target_cruise, chosen_stations, axis_label):
    """Map of the section: every station of the cruise, the ones in the section, and the line joining them in section order."""
    st = con.execute(f"SELECT station_id, MIN(lat) AS lat, MIN(lon) AS lon, MIN(time_iso) AS t FROM {_T()} "
                     "WHERE cruise_id = ? AND lat IS NOT NULL AND lon IS NOT NULL GROUP BY station_id",
                     (target_cruise,)).df()
    if st.empty:
        return pn.pane.Alert('No station positions for this cruise.', alert_type='warning')
    st = st.set_index('station_id')
    chosen = [c for c in (chosen_stations or []) if c in st.index]
    if chosen_stations and not chosen:
        chosen = list(st.index)                       # a stale list from another cruise means "all of them", as in the section
    order = []
    if len(chosen) >= 2:
        x_sta = _section_positions(st.loc[chosen], _SECTION_AXES[axis_label]).dropna()
        if x_sta.nunique() >= 2:
            order = x_sta.sort_values().index.tolist()    # the order the section draws them in
    st['x'], st['y'] = _to_mercator(st['lon'].to_numpy(float), st['lat'].to_numpy(float))
    st['status'] = 'other stations'
    st.loc[chosen, 'status'] = 'in section'
    if order:
        st.loc[order[0], 'status'] = 'section start'
    st = st.sort_values('status', key=lambda c: c.map({'other stations': 0, 'in section': 1, 'section start': 2}))
    pts = hv.Points(st.reset_index(), kdims=['x', 'y'], vdims=['station_id', 'lat', 'lon', 'status']).opts(
        color='status', cmap=SECTION_MAP_COLORS, size=11, line_color='white', line_width=1.2,
        tools=['hover'], show_legend=True, legend_position='bottom_left')
    layers = gvts.EsriOceanBase * gvts.EsriOceanReference
    if order:
        line = st.loc[order, ['x', 'y']].to_numpy(float)
        layers = layers * hv.Path([line]).opts(color='#d62728', line_width=2.5, show_legend=False)
    layers = layers * pts
    # Start view: the stations of the section (or of the cruise), padded, at least about 70 km across, same shape as the plot.
    sel = st[st['status'] != 'other stations'] if (st['status'] != 'other stations').any() else st
    xs, ys = sel['x'].to_numpy(), sel['y'].to_numpy()
    half_min = 35000.0 / np.cos(np.radians(float(sel['lat'].mean())))
    cx, cy = (xs.min() + xs.max()) / 2, (ys.min() + ys.max()) / 2
    hx, hy = max((xs.max() - xs.min()) * 0.65, half_min), max((ys.max() - ys.min()) * 0.65, half_min)
    aspect = SECTION_MAP_W / SECTION_MAP_H
    if hx / hy < aspect:
        hx = hy * aspect
    else:
        hy = hx / aspect
    plot = layers.opts(
        width=SECTION_MAP_W, height=SECTION_MAP_H, xaxis=None, yaxis=None, active_tools=['wheel_zoom'],
        xlim=(cx - hx, cx + hx), ylim=(cy - hy, cy + hy), bgcolor='#0b1a2b',
        title='Section line (red) and stations', hooks=[_white_border, _limit_map_zoom])
    return pn.pane.HoloViews(plot)


view_section = pn.Column(
    pn.Row(section_var_select, section_axis_select, section_gap_slider, margin=(8, 0, 4, 10)),
    pn.Row(section_grid_select, section_lx_slider, section_ly_slider, margin=(0, 0, 4, 10), align='start'),
    pn.Row(
        pn.Column(section_name_filter, pn.Row(section_date_from, section_date_to),
                  section_station_select, pn.Row(section_all_btn, section_none_btn), margin=(0, 10, 0, 10)),
        pn.bind(_section_impl, cruise_select, depth_slider, qc_checkbox, section_var_select,
                section_station_select, section_axis_select, section_gap_slider,
                section_grid_select, section_lx_slider, section_ly_slider),
        pn.bind(_section_map_impl, cruise_select, section_station_select, section_axis_select),
    ),
    sizing_mode='stretch_both',
)

# ── Tabular data ───────────────────────────────────────────────────────────────
def _tabular_impl(target_cruise, target_id, z_range, filter_qc, show_soak):
    df = get_clean_df(target_cruise, target_id, z_range, filter_qc, show_soak)
    if df.empty:
        return pn.pane.Alert("No data for the current selection.")
    return pn.widgets.Tabulator(df, pagination='remote', page_size=15, theme='midnight', sizing_mode='stretch_both')

view_tabular_data = pn.Column(
    pn.bind(_tabular_impl, cruise_select, station_select, depth_slider, qc_checkbox, soak_toggle),
    sizing_mode='stretch_both'
)

# 6. ASSEMBLY
tabs = pn.Tabs(
    ("Cruise Summary", view_cruise_summary),
    ("Map", view_map_geolocation),
    ("Vertical Section", view_section),
    ("Vertical Profiles", view_profiles),
    ("Multi-Axis Profile", view_multi_profile),
    ("T-S Analysis", view_ts_analysis),
    ("Stability & MLD", view_stability),
    ("Oxygen Utilization (AOU)", view_aou),
    ("Metabolic Index", view_metabolic_index),
    ("Tabular Data", view_tabular_data),
    dynamic=True, active=3
)

dashboard = pn.template.FastListTemplate(
    title="R/V Western Flyer - CTD (SBE 19plus V2)",
    sidebar=[cruise_select, source_select, direction_select, station_select, depth_slider, qc_checkbox, soak_toggle, pn.pane.Markdown("---"), csv_button],
    main=[tabs], accent_base_color="#00f2ff", header_background="#1a1a1a"
)

dashboard.servable()
