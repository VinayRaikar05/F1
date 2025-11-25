import os
import fastf1
import fastf1.plotting
import numpy as np
import json

# Enable local cache (adjust path if you prefer)
cache_dir = '.fastf1-cache'
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
fastf1.Cache.enable_cache(cache_dir)

FPS = 25
DT = 1 / FPS

def load_race_session(year: int, round_number: int, session_type: str = 'R'):
    """
    Load F1 session data from FastF1.
    
    Args:
        year: Year of the race
        round_number: Round number of the race
        session_type: Type of session ('R' for Race, 'Q' for Qualifying, 'FP1', 'FP2', 'FP3' for Practice)
    
    Returns:
        FastF1 session object with loaded telemetry
    
    Raises:
        Exception: If session cannot be loaded
    """
    try:
        session = fastf1.get_session(year, round_number, session_type)
        print(f"Loading telemetry data...")
        session.load(telemetry=True)
        return session
    except Exception as e:
        raise Exception(f"Failed to load session {year} Round {round_number} ({session_type}): {str(e)}")


def get_driver_colors(session) -> dict:
    """
    Get driver color mapping from session.
    
    Args:
        session: FastF1 session object
    
    Returns:
        Dictionary mapping driver codes to RGB color tuples
    """
    try:
        color_mapping = fastf1.plotting.get_driver_color_mapping(session)
        
        # Convert hex colors to RGB tuples
        rgb_colors = {}
        for driver, hex_color in color_mapping.items():
            hex_color = hex_color.lstrip('#')
            rgb = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
            rgb_colors[driver] = rgb
        return rgb_colors
    except Exception as e:
        print(f"Warning: Could not load driver colors: {e}")
        return {}


def get_race_telemetry(session):

    event_name = str(session).replace(' ', '_')

    # Check if this data has already been computed

    try:
        if "--refresh-data" not in os.sys.argv:
            with open(f"computed_data/{event_name}_race_telemetry.json", "r") as f:
                frames = json.load(f)
                print("Loaded precomputed race telemetry data.")
                print("The replay should begin in a new window shortly!")
                return frames
    except FileNotFoundError:
        pass  # Need to compute from scratch


    drivers = session.drivers

    driver_codes = {
        num: session.get_driver(num)["Abbreviation"]
        for num in drivers
    }

    driver_data = {}

    global_t_min = None
    global_t_max = None

    # 1. Get all of the drivers telemetry data
    for driver_no in drivers:
        code = driver_codes[driver_no]

        print("Getting telemetry for driver:", code)

        laps_driver = session.laps.pick_drivers(driver_no)
        if laps_driver.empty:
            continue

        t_all = []
        x_all = []
        y_all = []
        race_dist_all = []
        rel_dist_all = []
        lap_numbers = []
        speed_all = []  # Speed in km/h

        total_dist_so_far = 0.0

        # iterate laps in order
        for _, lap in laps_driver.iterlaps():
            # get telemetry for THIS lap only
            lap_tel = lap.get_telemetry()
            lap_number = lap.LapNumber
            if lap_tel.empty:
                continue

            t_lap = lap_tel["SessionTime"].dt.total_seconds().to_numpy()
            x_lap = lap_tel["X"].to_numpy()
            y_lap = lap_tel["Y"].to_numpy()
            d_lap = lap_tel["Distance"].to_numpy()
            rd_lap = lap_tel["RelativeDistance"].to_numpy()
            # Extract speed if available, convert from m/s to km/h
            speed_lap = lap_tel["Speed"].to_numpy() * 3.6 if "Speed" in lap_tel.columns else np.zeros_like(t_lap)

            # normalise lap distance to start at 0
            d_lap = d_lap - d_lap.min()
            lap_length = d_lap.max()  # approx. circuit length for this lap

            # race distance = distance before this lap + distance within this lap
            race_d_lap = total_dist_so_far + d_lap

            total_dist_so_far += lap_length

            t_all.append(t_lap)
            x_all.append(x_lap)
            y_all.append(y_lap)
            race_dist_all.append(race_d_lap)
            rel_dist_all.append(rd_lap)
            lap_numbers.append(np.full_like(t_lap, lap_number))
            speed_all.append(speed_lap)

        if not t_all:
            continue

        t_all = np.concatenate(t_all)
        x_all = np.concatenate(x_all)
        y_all = np.concatenate(y_all)
        race_dist_all = np.concatenate(race_dist_all)
        rel_dist_all = np.concatenate(rel_dist_all)
        lap_numbers = np.concatenate(lap_numbers)
        speed_all = np.concatenate(speed_all)

        order = np.argsort(t_all)
        t_all = t_all[order]
        x_all = x_all[order]
        y_all = y_all[order]
        race_dist_all = race_dist_all[order]
        rel_dist_all = rel_dist_all[order]
        lap_numbers = lap_numbers[order]
        speed_all = speed_all[order]

        driver_data[code] = {
            "t": t_all,
            "x": x_all,
            "y": y_all,
            "dist": race_dist_all,
            "rel_dist": rel_dist_all,
            "lap": lap_numbers,
            "speed": speed_all,
        }

        t_min = t_all.min()
        t_max = t_all.max()
        global_t_min = t_min if global_t_min is None else min(global_t_min, t_min)
        global_t_max = t_max if global_t_max is None else max(global_t_max, t_max)

    # 3. Create a timeline (start from zero)
    timeline = np.arange(global_t_min, global_t_max, DT) - global_t_min

    # 4. Resample each driver's telemetry (x, y, gap) onto the common timeline
    resampled_data = {}

    for code, data in driver_data.items():
        t = data["t"] - global_t_min  # Shift
        x = data["x"]
        y = data["y"]
        dist = data["dist"]
        rel_dist = data["rel_dist"]
        speed = data["speed"]

        # ensure sorted by time
        order = np.argsort(t)
        t_sorted = t[order]
        x_sorted = x[order]
        y_sorted = y[order]
        dist_sorted = dist[order]
        rel_dist_sorted = rel_dist[order]
        lap_sorted = data["lap"][order]
        speed_sorted = speed[order]

        x_resampled = np.interp(timeline, t_sorted, x_sorted)
        y_resampled = np.interp(timeline, t_sorted, y_sorted)
        dist_resampled = np.interp(timeline, t_sorted, dist_sorted)
        rel_dist_resampled = np.interp(timeline, t_sorted, rel_dist_sorted)
        lap_resampled = np.interp(timeline, t_sorted, lap_sorted)
        speed_resampled = np.interp(timeline, t_sorted, speed_sorted)

        resampled_data[code] = {
            "t": timeline,
            "x": x_resampled,
            "y": y_resampled,
            "dist": dist_resampled,   # race distance (metres since Lap 1 start)
            "rel_dist": rel_dist_resampled,
            "lap": lap_resampled,
            "speed": speed_resampled,  # speed in km/h
        }

    # 5. Build the frames + LIVE LEADERBOARD
    frames = []

    for i, t in enumerate(timeline):
        snapshot = []
        for code, d in resampled_data.items():
          snapshot.append({
            "code": code,
            "dist": float(d["dist"][i]),
            "x": float(d["x"][i]),
            "y": float(d["y"][i]),
            "lap": int(round(d["lap"][i])),
            "rel_dist": float(d["rel_dist"][i]),
            "speed": float(d["speed"][i]),  # Speed in km/h
          })

        # If for some reason we have no drivers at this instant
        if not snapshot:
            continue

        # 5b. Sort by race distance to get POSITIONS (1–20)
        # Leader = largest race distance covered
        snapshot.sort(key=lambda r: r["dist"], reverse=True)

        leader = snapshot[0]
        leader_lap = leader["lap"]

        # 5c. Compute gap to car ahead in SECONDS and interval to leader
        frame_data = {}
        
        # Calculate gaps based on distance difference and average speed
        for idx, car in enumerate(snapshot):
            code = car["code"]
            position = idx + 1
            
            if idx == 0:
                # Leader - no gap
                gap_to_ahead = 0.0
                interval_to_leader = 0.0
            else:
                # Calculate gap to car ahead
                car_ahead = snapshot[idx - 1]
                dist_diff = car_ahead["dist"] - car["dist"]
                
                # Use average speed of both cars to estimate time gap
                avg_speed = (car["speed"] + car_ahead["speed"]) / 2.0
                if avg_speed > 10:  # Avoid division by zero for very slow speeds
                    gap_to_ahead = (dist_diff / 1000.0) / (avg_speed / 3600.0)  # Convert to seconds
                else:
                    gap_to_ahead = 0.0
                
                # Calculate interval to leader
                leader_dist_diff = leader["dist"] - car["dist"]
                if car["speed"] > 10:
                    interval_to_leader = (leader_dist_diff / 1000.0) / (car["speed"] / 3600.0)
                else:
                    interval_to_leader = 0.0

            frame_data[code] = {
                "x": car["x"],
                "y": car["y"],
                "dist": car["dist"],
                "lap": car["lap"],
                "rel_dist": round(car["rel_dist"], 6),
                "position": position,
                "speed": round(car["speed"], 1),  # Speed in km/h, rounded to 1 decimal
                "gap_to_ahead": round(gap_to_ahead, 3),  # Gap in seconds
                "interval_to_leader": round(interval_to_leader, 3),  # Interval in seconds
            }

        frames.append({
            "t": float(t),
            "lap": leader_lap,   # leader’s lap at this time
            "drivers": frame_data,
        })
    print("completed telemetry extraction...")
    print("Saving to JSON file...")
    # If computed_data/ directory doesn't exist, create it
    if not os.path.exists("computed_data"):
        os.makedirs("computed_data")

    # Save to file
    with open(f"computed_data/{event_name}_race_telemetry.json", "w") as f:
        json.dump(frames, f, indent=2)

    print("Saved Successfully!")
    print("The replay should begin in a new window shortly")
    return frames
