from src.f1_data import get_race_telemetry, get_driver_colors, load_race_session
from src.arcade_replay import run_arcade_replay
import argparse
import sys
from typing import Optional

def main(year: int, round_number: int, session_type: str = 'R', 
         playback_speed: float = 1.0, refresh_data: bool = False) -> None:
    """
    Main function to load and display F1 race replay.
    
    Args:
        year: Year of the race
        round_number: Round number of the race
        session_type: Type of session ('R' for Race, 'Q' for Qualifying, 'FP1', 'FP2', 'FP3' for Practice)
        playback_speed: Initial playback speed multiplier
        refresh_data: If True, force re-computation of telemetry data
    """
    try:
        # Store refresh_data flag in sys.argv for f1_data.py to access
        if refresh_data and "--refresh-data" not in sys.argv:
            sys.argv.append("--refresh-data")
        
        session = load_race_session(year, round_number, session_type)
        print(f"Loaded session: {session.event['EventName']} - Round {session.event['RoundNumber']}")
        
        # Get the drivers who participated in the session
        race_telemetry = get_race_telemetry(session)
        
        # Get example lap for track layout
        example_lap = session.laps.pick_fastest().get_telemetry()
        
        drivers = session.drivers
        
        driver_codes = {
            num: session.get_driver(num)["Abbreviation"]
            for num in drivers
        }
        
        driver_colors = get_driver_colors(session)
        
        # Determine session name for title
        session_names = {'R': 'Race', 'Q': 'Qualifying', 'FP1': 'Practice 1', 
                        'FP2': 'Practice 2', 'FP3': 'Practice 3'}
        session_name = session_names.get(session_type, 'Session')
        
        run_arcade_replay(
            frames=race_telemetry,
            example_lap=example_lap,
            drivers=drivers,
            playback_speed=playback_speed,
            driver_colors=driver_colors,
            title=f"{session.event['EventName']} - {session_name}"
        )
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="F1 Race Replay - Visualize Formula 1 race telemetry with interactive controls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py --year 2024 --round 1
  python main.py --year 2024 --round 5 --session-type Q
  python main.py --year 2023 --round 10 --refresh-data
        """
    )
    
    parser.add_argument(
        "--year",
        type=int,
        default=2025,
        help="Year of the race (default: 2025)"
    )
    
    parser.add_argument(
        "--round",
        type=int,
        default=12,
        help="Round number of the race (default: 12)"
    )
    
    parser.add_argument(
        "--session-type",
        type=str,
        default='R',
        choices=['R', 'Q', 'FP1', 'FP2', 'FP3'],
        help="Session type: R=Race, Q=Qualifying, FP1/FP2/FP3=Practice (default: R)"
    )
    
    parser.add_argument(
        "--playback-speed",
        type=float,
        default=1.0,
        help="Initial playback speed multiplier (default: 1.0)"
    )
    
    parser.add_argument(
        "--refresh-data",
        action="store_true",
        help="Force re-computation of telemetry data (ignore cached data)"
    )
    
    args = parser.parse_args()
    
    main(
        year=args.year,
        round_number=args.round,
        session_type=args.session_type,
        playback_speed=args.playback_speed,
        refresh_data=args.refresh_data
    )