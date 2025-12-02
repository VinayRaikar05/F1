from src.f1_data import get_race_telemetry, load_race_session, enable_cache, get_circuit_rotation
from src.arcade_replay import run_arcade_replay
import sys

def main(year=None, round_number=None, playback_speed=1, session_type='R'):
  # Enable cache for fastf1 before loading session to optimize API calls
  enable_cache()

  session = load_race_session(year, round_number, session_type)
  print(f"Loaded session: {session.event['EventName']} - {session.event['RoundNumber']}")

  # Get the drivers who participated in the race
  try:
    race_telemetry = get_race_telemetry(session, session_type=session_type)
  except Exception as e:
    print(f"Error retrieving race telemetry: {e}")
    raise

  # Get example lap for track layout
  try:
    example_lap = session.laps.pick_fastest().get_telemetry()
  except Exception as e:
    print(f"Error retrieving example lap: {e}")
    raise

  try:
    drivers = session.drivers

    # Get circuit rotation
    circuit_rotation = get_circuit_rotation(session)
  except Exception as e:
    print(f"Error retrieving session data: {e}")
    raise

  # Run the arcade replay
  try:
    run_arcade_replay(
    frames=race_telemetry['frames'],
    track_statuses=race_telemetry['track_statuses'],
    example_lap=example_lap,
    drivers=drivers,
    playback_speed=1.0,
    driver_colors=race_telemetry['driver_colors'],
    title=f"{session.event['EventName']} - {'Sprint' if session_type == 'S' else 'Race'}",
    total_laps=race_telemetry['total_laps'],
    circuit_rotation=circuit_rotation,
    )
  except Exception as e:
    print(f"Error running arcade replay: {e}")
    raise

def parse_arguments():
  """Parse command-line arguments with better maintainability."""
  year = 2025
  round_number = 12
  session_type = 'R'
  
  if "--year" in sys.argv:
    try:
      year = int(sys.argv[sys.argv.index("--year") + 1])
    except (ValueError, IndexError):
      print("Invalid --year argument, using default: 2025")
  
  if "--round" in sys.argv:
    try:
      round_number = int(sys.argv[sys.argv.index("--round") + 1])
    except (ValueError, IndexError):
      print("Invalid --round argument, using default: 12")
  
  if "--sprint" in sys.argv:
    session_type = 'S'
  
  return year, round_number, session_type

if __name__ == "__main__":
  try:
    year, round_number, session_type = parse_arguments()
    main(year, round_number, playback_speed=1, session_type=session_type)
  except Exception as e:
    print(f"Fatal error: {e}")
    sys.exit(1)