import os
import fastf1
import fastf1.plotting
import numpy as np
import json
from datetime import timedelta
import re

from src.lib.tyres import get_tyre_compound_int

def enable_cache():
    """Enable fastf1 caching with atomic directory creation."""
    cache_dir = '.fastf1-cache'
    os.makedirs(cache_dir, exist_ok=True)
    fastf1.Cache.enable_cache(cache_dir)

FPS = 25
DT = 1 / FPS

def load_race_session(year, round_number, session_type='R'):
    # session_type: 'R' (Race), 'S' (Sprint) etc.
    session = fastf1.get_session(year, round_number, session_type)
    session.load(telemetry=True)
    return session


def get_driver_colors(session):
    color_mapping = fastf1.plotting.get_driver_color_mapping(session)
    
    # Convert hex colors to RGB tuples
    rgb_colors = {}
    for driver, hex_color in color_mapping.items():
        hex_color = hex_color.lstrip('#')
        rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        rgb_colors[driver] = rgb
    return rgb_colors

def get_circuit_rotation(session):
    circuit = session.get_circuit_info()
    return circuit.rotation

def get_race_telemetry(session, session_type='R'):

    # helpers ---------------------------------------------------------------
    def _sanitize_filename(name: str, max_len: int = 200) -> str:
        # Keep only safe characters for filenames
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
        return safe[:max_len]

    def _cached_filepath(event: str, suffix: str) -> str:
        filename = f"{_sanitize_filename(event)}_{suffix}_telemetry.json"
        return os.path.join("computed_data", filename)

    def _load_cached(event: str, suffix: str):
        path = _cached_filepath(event, suffix)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: failed to read cached telemetry {path}: {e}")
            return None

    def _save_cached(event: str, suffix: str, payload: dict):
        os.makedirs("computed_data", exist_ok=True)
        path = _cached_filepath(event, suffix)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as e:
            print(f"Warning: failed to write cached telemetry {path}: {e}")

    # main flow ------------------------------------------------------------
    event_name = _sanitize_filename(str(session))
    cache_suffix = 'sprint' if session_type == 'S' else 'race'

    # Attempt to load precomputed data unless explicitly requested to refresh
    if "--refresh-data" not in os.sys.argv:
        cached = _load_cached(event_name, cache_suffix)
        if cached:
            print(f"Loaded precomputed {cache_suffix} telemetry data.")
            print("The replay should begin in a new window shortly!")
            return cached

    drivers = session.drivers

    # Build mapping driver_no -> abbreviation defensively
    driver_codes = {}
    for num in drivers:
        try:
            driver_codes[num] = session.get_driver(num).get("Abbreviation")
        except Exception:
            driver_codes[num] = str(num)

    driver_data = {}
    global_t_min = None
    global_t_max = None
    max_lap_number = 0

    # 1. Extract per-driver telemetry and concatenate per-lap arrays
    for driver_no in drivers:
        code = driver_codes.get(driver_no, str(driver_no))
        print("Getting telemetry for driver:", code)

        try:
            laps_driver = session.laps.pick_drivers(driver_no)
        except Exception as e:
            print(f"Warning: failed to get laps for {code}: {e}")
            continue

        if laps_driver.empty:
            continue

        max_lap_number = max(max_lap_number, int(laps_driver.LapNumber.max()))

        parts = {
            't': [], 'x': [], 'y': [], 'dist': [], 'rel_dist': [],
            'lap': [], 'tyre': [], 'speed': [], 'gear': [], 'drs': []
        }

        total_dist_so_far = 0.0
        for _, lap in laps_driver.iterlaps():
            try:
                lap_tel = lap.get_telemetry()
            except Exception:
                continue

            lap_number = int(lap.LapNumber)
            tyre_compound_int = get_tyre_compound_int(getattr(lap, 'Compound', ''))

            if lap_tel.empty:
                continue

            t_lap = lap_tel["SessionTime"].dt.total_seconds().to_numpy()
            x_lap = lap_tel["X"].to_numpy()
            y_lap = lap_tel["Y"].to_numpy()
            d_lap = lap_tel["Distance"].to_numpy()
            rd_lap = lap_tel.get("RelativeDistance", lap_tel["Distance"]).to_numpy()
            speed_kph_lap = lap_tel.get("Speed", lap_tel.get("SpeedKph", None)).to_numpy()
            gear_lap = lap_tel.get("nGear", np.zeros_like(t_lap)).to_numpy()
            drs_lap = lap_tel.get("DRS", np.zeros_like(t_lap)).to_numpy()

            race_d_lap = total_dist_so_far + d_lap

            parts['t'].append(t_lap)
            parts['x'].append(x_lap)
            parts['y'].append(y_lap)
            parts['dist'].append(race_d_lap)
            parts['rel_dist'].append(rd_lap)
            parts['lap'].append(np.full_like(t_lap, lap_number))
            parts['tyre'].append(np.full_like(t_lap, tyre_compound_int))
            parts['speed'].append(speed_kph_lap)
            parts['gear'].append(gear_lap)
            parts['drs'].append(drs_lap)

            # Update cumulative distance for next lap
            total_dist_so_far = float(race_d_lap[-1]) if len(race_d_lap) else total_dist_so_far

        if not parts['t']:
            continue

        # Concatenate arrays and sort by time
        try:
            t_all = np.concatenate(parts['t'])
            order = np.argsort(t_all)

            def _concat_and_sort(key):
                arr = np.concatenate(parts[key])
                return arr[order]

            t_all = t_all[order]
            x_all = _concat_and_sort('x')
            y_all = _concat_and_sort('y')
            dist_all = _concat_and_sort('dist')
            rel_dist_all = _concat_and_sort('rel_dist')
            lap_all = _concat_and_sort('lap')
            tyre_all = _concat_and_sort('tyre')
            speed_all = _concat_and_sort('speed')
            gear_all = _concat_and_sort('gear')
            drs_all = _concat_and_sort('drs')
        except Exception as e:
            print(f"Warning: failed to concatenate telemetry for {code}: {e}")
            continue

        driver_data[code] = {
            't': t_all,
            'x': x_all,
            'y': y_all,
            'dist': dist_all,
            'rel_dist': rel_dist_all,
            'lap': lap_all,
            'tyre': tyre_all,
            'speed': speed_all,
            'gear': gear_all,
            'drs': drs_all,
        }

        t_min = float(t_all.min())
        t_max = float(t_all.max())
        global_t_min = t_min if global_t_min is None else min(global_t_min, t_min)
        global_t_max = t_max if global_t_max is None else max(global_t_max, t_max)

    if not driver_data or global_t_min is None or global_t_max is None:
        raise ValueError("No telemetry data available for this session")

    # 2. Create a timeline (start from zero)
    timeline = np.arange(global_t_min, global_t_max + DT, DT) - global_t_min

    # 3. Resample each driver's telemetry onto the common timeline
    resampled_data = {}
    for code, data in driver_data.items():
        try:
            t = data['t'] - global_t_min
            order = np.argsort(t)
            t_sorted = t[order]
            # helper to safe interp (requires sorted arrays)
            def _safe_interp(arr):
                return np.interp(timeline, t_sorted, arr[order])

            resampled_data[code] = {
                't': timeline,
                'x': _safe_interp(data['x']),
                'y': _safe_interp(data['y']),
                'dist': _safe_interp(data['dist']),
                'rel_dist': _safe_interp(data['rel_dist']),
                'lap': _safe_interp(data['lap']),
                'tyre': _safe_interp(data['tyre']),
                'speed': _safe_interp(data['speed']),
                'gear': _safe_interp(data['gear']),
                'drs': _safe_interp(data['drs']),
            }
        except Exception as e:
            print(f"Warning: failed to resample telemetry for {code}: {e}")

    # 4. Incorporate track status data into the timeline
    formatted_track_statuses = []
    try:
        track_status = getattr(session, 'track_status', None)
        if track_status is not None:
            for status in track_status.to_dict('records'):
                seconds = timedelta.total_seconds(status['Time'])
                start_time = seconds - global_t_min
                end_time = None
                if formatted_track_statuses:
                    formatted_track_statuses[-1]['end_time'] = start_time
                formatted_track_statuses.append({
                    'status': status.get('Status'),
                    'start_time': start_time,
                    'end_time': end_time,
                })
    except Exception as e:
        print(f"Warning: failed to process track status: {e}")

    # 5. Build frames
    frames = []
    for i, t in enumerate(timeline):
        frame_drivers = {}
        for code, d in resampled_data.items():
            try:
                frame_drivers[code] = {
                    'x': float(d['x'][i]),
                    'y': float(d['y'][i]),
                    'dist': float(d['dist'][i]),
                    'lap': int(round(d['lap'][i])),
                    'rel_dist': float(d['rel_dist'][i]),
                    'tyre': d['tyre'][i],
                    'speed': d['speed'][i],
                    'gear': int(round(d['gear'][i])),
                    'drs': int(round(d['drs'][i])),
                }
            except Exception:
                continue

        if not frame_drivers:
            continue

        # sort to find leader
        snapshot = sorted([
            {'code': c, 'dist': v['dist'], 'lap': v['lap'], 'x': v['x'], 'y': v['y'], 'rel_dist': v['rel_dist'], 'tyre': v['tyre'], 'speed': v['speed'], 'gear': v['gear'], 'drs': v['drs']}
            for c, v in frame_drivers.items()
        ], key=lambda r: r['dist'], reverse=True)

        leader = snapshot[0]
        leader_lap = leader['lap']

        frame_data = {}
        for idx, car in enumerate(snapshot):
            frame_data[car['code']] = {
                'x': car['x'],
                'y': car['y'],
                'dist': car['dist'],
                'lap': car['lap'],
                'rel_dist': round(car['rel_dist'], 4),
                'tyre': car['tyre'],
                'position': idx + 1,
                'speed': car['speed'],
                'gear': car['gear'],
                'drs': car['drs'],
            }

        frames.append({'t': float(t), 'lap': leader_lap, 'drivers': frame_data})

    print("completed telemetry extraction...")
    print("Saving to JSON file...")

    payload = {
        'frames': frames,
        'driver_colors': get_driver_colors(session),
        'track_statuses': formatted_track_statuses,
        'total_laps': int(max_lap_number),
    }

    try:
        _save_cached(event_name, cache_suffix, payload)
        print("Saved Successfully!")
    except Exception:
        print("Warning: failed to persist telemetry cache")

    print("The replay should begin in a new window shortly")
    return payload
