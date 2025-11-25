import os
import arcade
import numpy as np

# Kept these as "default" starting sizes, but they are no longer hard limits
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1200
SCREEN_TITLE = "F1 Replay"

def build_track_from_example_lap(example_lap, track_width: int = 200):
    """
    Build track geometry from an example lap.
    
    Args:
        example_lap: Telemetry data from FastF1 containing X, Y coordinates
        track_width: Width of the track in meters
    
    Returns:
        Tuple of track geometry data (x_ref, y_ref, x_inner, y_inner, x_outer, y_outer, x_min, x_max, y_min, y_max)
    """
    plot_x_ref = example_lap["X"].to_numpy()
    plot_y_ref = example_lap["Y"].to_numpy()

    # compute tangents
    dx = np.gradient(plot_x_ref)
    dy = np.gradient(plot_y_ref)

    norm = np.sqrt(dx**2 + dy**2)
    norm[norm == 0] = 1.0
    dx /= norm
    dy /= norm

    nx = -dy
    ny = dx

    x_outer = plot_x_ref + nx * (track_width / 2)
    y_outer = plot_y_ref + ny * (track_width / 2)
    x_inner = plot_x_ref - nx * (track_width / 2)
    y_inner = plot_y_ref - ny * (track_width / 2)

    # world bounds
    x_min = min(plot_x_ref.min(), x_inner.min(), x_outer.min())
    x_max = max(plot_x_ref.max(), x_inner.max(), x_outer.max())
    y_min = min(plot_y_ref.min(), y_inner.min(), y_outer.min())
    y_max = max(plot_y_ref.max(), y_inner.max(), y_outer.max())

    return (plot_x_ref, plot_y_ref, x_inner, y_inner, x_outer, y_outer,
            x_min, x_max, y_min, y_max)


class F1ReplayWindow(arcade.Window):
    def __init__(self, frames, example_lap, drivers, title,
                 playback_speed=1.0, driver_colors=None):
        # Set resizable to True so the user can adjust mid-sim
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, title, resizable=True)

        self.frames = frames
        self.n_frames = len(frames)
        self.drivers = list(drivers)
        self.playback_speed = playback_speed
        self.driver_colors = driver_colors or {}
        self.frame_index = 0
        self.paused = False
        
        # New features: follow camera, show speeds, show labels
        self.follow_driver = None  # Driver code to follow
        self.show_speeds = False  # Toggle speed display
        self.show_labels = True  # Toggle driver labels
        self.follow_offset_x = 0  # Camera offset for following
        self.follow_offset_y = 0

        # Build track geometry (Raw World Coordinates)
        (self.plot_x_ref, self.plot_y_ref,
         self.x_inner, self.y_inner,
         self.x_outer, self.y_outer,
         self.x_min, self.x_max,
         self.y_min, self.y_max) = build_track_from_example_lap(example_lap)
        
        # Calculate track tangents for car orientation (must be after track geometry is built)
        self._calculate_track_tangents()

        # Pre-calculate interpolated world points ONCE (optimization)
        # We store these as 'world' coordinates, not screen coordinates
        self.world_inner_points = self._interpolate_points(self.x_inner, self.y_inner)
        self.world_outer_points = self._interpolate_points(self.x_outer, self.y_outer)

        # These will hold the actual screen coordinates to draw
        self.screen_inner_points = []
        self.screen_outer_points = []
        
        # Scaling parameters (initialized to 0, calculated in update_scaling)
        self.world_scale = 1.0
        self.tx = 0
        self.ty = 0

        # Load Background
        bg_path = os.path.join("resources", "background.png")
        self.bg_texture = arcade.load_texture(bg_path) if os.path.exists(bg_path) else None

        arcade.set_background_color(arcade.color.BLACK)

        # Trigger initial scaling calculation
        self.update_scaling(self.width, self.height)

    def _interpolate_points(self, xs, ys, interp_points=2000):
        """Generates smooth points in WORLD coordinates."""
        t_old = np.linspace(0, 1, len(xs))
        t_new = np.linspace(0, 1, interp_points)
        xs_i = np.interp(t_new, t_old, xs)
        ys_i = np.interp(t_new, t_old, ys)
        return list(zip(xs_i, ys_i))
    
    def _calculate_track_tangents(self):
        """Calculate track direction at each point for car orientation."""
        dx = np.gradient(self.plot_x_ref)
        dy = np.gradient(self.plot_y_ref)
        # Store as angles for easy lookup
        self.track_angles = np.arctan2(dy, dx)
        self.track_points = list(zip(self.plot_x_ref, self.plot_y_ref))
    
    def _get_nearest_track_angle(self, x, y):
        """Get track direction angle at nearest point to (x, y)."""
        if not hasattr(self, 'track_points'):
            return 0.0
        # Find nearest track point
        distances = [np.sqrt((x - tx)**2 + (y - ty)**2) for tx, ty in self.track_points]
        nearest_idx = np.argmin(distances)
        if nearest_idx < len(self.track_angles):
            return self.track_angles[nearest_idx]
        return 0.0
    
    def _speed_to_color(self, speed, min_speed=0, max_speed=350):
        """Convert speed (km/h) to color (red=fast, blue=slow)."""
        # Normalize speed to 0-1 range
        normalized = max(0, min(1, (speed - min_speed) / (max_speed - min_speed)))
        # Create gradient: blue (slow) -> green -> yellow -> red (fast)
        if normalized < 0.33:
            # Blue to green
            t = normalized / 0.33
            r = 0
            g = int(255 * t)
            b = int(255 * (1 - t))
        elif normalized < 0.66:
            # Green to yellow
            t = (normalized - 0.33) / 0.33
            r = int(255 * t)
            g = 255
            b = 0
        else:
            # Yellow to red
            t = (normalized - 0.66) / 0.34
            r = 255
            g = int(255 * (1 - t))
            b = 0
        return (r, g, b)
    
    def _draw_rotated_rectangle(self, center_x, center_y, width, height, angle_degrees, color):
        """Draw a rotated rectangle using polygon."""
        # Convert angle to radians
        angle_rad = np.radians(angle_degrees)
        
        # Calculate half dimensions
        half_w = width / 2
        half_h = height / 2
        
        # Define rectangle corners relative to center
        corners = [
            (-half_w, -half_h),
            (half_w, -half_h),
            (half_w, half_h),
            (-half_w, half_h)
        ]
        
        # Rotate corners
        cos_a = np.cos(angle_rad)
        sin_a = np.sin(angle_rad)
        rotated_corners = []
        for x, y in corners:
            rx = x * cos_a - y * sin_a
            ry = x * sin_a + y * cos_a
            rotated_corners.append((center_x + rx, center_y + ry))
        
        # Draw filled polygon
        arcade.draw_polygon_filled(rotated_corners, color)

    def update_scaling(self, screen_w, screen_h):
        """
        Recalculates the scale and translation to fit the track 
        perfectly within the new screen dimensions while maintaining aspect ratio.
        """
        padding = 0.05
        world_w = max(1.0, self.x_max - self.x_min)
        world_h = max(1.0, self.y_max - self.y_min)
        
        usable_w = screen_w * (1 - 2 * padding)
        usable_h = screen_h * (1 - 2 * padding)

        # Calculate scale to fit whichever dimension is the limiting factor
        scale_x = usable_w / world_w
        scale_y = usable_h / world_h
        self.world_scale = min(scale_x, scale_y)

        # Center the world in the screen
        world_cx = (self.x_min + self.x_max) / 2
        world_cy = (self.y_min + self.y_max) / 2
        screen_cx = screen_w / 2
        screen_cy = screen_h / 2

        self.tx = screen_cx - self.world_scale * world_cx
        self.ty = screen_cy - self.world_scale * world_cy

        # Update the polyline screen coordinates based on new scale
        self.screen_inner_points = [self.world_to_screen(x, y) for x, y in self.world_inner_points]
        self.screen_outer_points = [self.world_to_screen(x, y) for x, y in self.world_outer_points]

    def on_resize(self, width, height):
        """Called automatically by Arcade when window is resized."""
        super().on_resize(width, height)
        self.update_scaling(width, height)

    def world_to_screen(self, x, y):
        """Convert world coordinates to screen coordinates with follow camera offset."""
        sx = self.world_scale * x + self.tx - self.follow_offset_x
        sy = self.world_scale * y + self.ty - self.follow_offset_y
        return sx, sy
    
    def _update_follow_camera(self):
        """Update camera offset to follow selected driver."""
        if self.follow_driver is None:
            self.follow_offset_x = 0
            self.follow_offset_y = 0
            return
        
        frame = self.frames[self.frame_index]
        if self.follow_driver in frame["drivers"]:
            driver_pos = frame["drivers"][self.follow_driver]
            # Calculate offset to center followed driver
            driver_world_x = driver_pos["x"]
            driver_world_y = driver_pos["y"]
            # Center this position on screen
            world_cx = (self.x_min + self.x_max) / 2
            world_cy = (self.y_min + self.y_max) / 2
            screen_cx = self.width / 2
            screen_cy = self.height / 2
            
            # Calculate offset needed
            self.follow_offset_x = self.world_scale * (driver_world_x - world_cx)
            self.follow_offset_y = self.world_scale * (driver_world_y - world_cy)

    def on_draw(self):
        self.clear()

        # 1. Draw Background (stretched to fit new window size)
        if self.bg_texture:
            arcade.draw_lrbt_rectangle_textured(
                left=0, right=self.width,
                bottom=0, top=self.height,
                texture=self.bg_texture
            )

        # 2. Draw Track (using pre-calculated screen points)
        track_color = (150, 150, 150)
        if len(self.screen_inner_points) > 1:
            arcade.draw_line_strip(self.screen_inner_points, track_color, 4)
        if len(self.screen_outer_points) > 1:
            arcade.draw_line_strip(self.screen_outer_points, track_color, 4)

        # Update follow camera offset
        self._update_follow_camera()
        
        # 3. Draw Cars
        frame = self.frames[self.frame_index]
        for code, pos in frame["drivers"].items():
            if pos.get("rel_dist", 0) == 1:
                continue
            
            sx, sy = self.world_to_screen(pos["x"], pos["y"])
            speed = pos.get("speed", 0)  # Speed may not exist in old cached data
            
            # Use speed-based color if speed is available, otherwise use driver color
            driver_color = self.driver_colors.get(code, arcade.color.WHITE)
            if speed > 0:
                speed_color = self._speed_to_color(speed)
                # Blend speed color with driver color (50/50 mix)
                if isinstance(driver_color, tuple) and len(driver_color) == 3:
                    mixed_color = (
                        (speed_color[0] + driver_color[0]) // 2,
                        (speed_color[1] + driver_color[1]) // 2,
                        (speed_color[2] + driver_color[2]) // 2
                    )
                    color = mixed_color
                else:
                    color = speed_color
            else:
                color = driver_color
            
            # Draw car as a small rotated rectangle (better than circle)
            angle = self._get_nearest_track_angle(pos["x"], pos["y"])
            angle_degrees = np.degrees(angle)
            self._draw_rotated_rectangle(sx, sy, 8, 4, angle_degrees, color)
            
            # Draw driver label if enabled
            if self.show_labels:
                arcade.draw_text(code, sx + 8, sy + 8, color, 10, bold=True)
            
            # Draw speed if enabled
            if self.show_speeds and speed > 0:
                speed_text = f"{int(speed)}"
                arcade.draw_text(speed_text, sx, sy - 15, arcade.color.WHITE, 8)

        # --- UI ELEMENTS (Dynamic Positioning) ---
        
        # Determine Leader info
        leader_code = max(
            frame["drivers"],
            key=lambda c: (frame["drivers"][c].get("lap", 1), frame["drivers"][c].get("dist", 0))
        )
        leader_lap = frame["drivers"][leader_code].get("lap", 1)

        # Time Calculation
        t = frame["t"]
        hours = int(t // 3600)
        minutes = int((t % 3600) // 60)
        seconds = int(t % 60)
        time_str = f"{hours:02}:{minutes:02}:{seconds:02}"

        # Draw HUD - Top Left
        arcade.draw_text(f"Lap: {leader_lap}", 
                         20, self.height - 40, 
                         arcade.color.WHITE, 24, anchor_y="top")
        
        arcade.draw_text(f"Race Time: {time_str}", 
                         20, self.height - 80, 
                         arcade.color.WHITE, 20, anchor_y="top")
        
        # Display playback speed
        speed_text = f"Speed: {self.playback_speed:.1f}x"
        arcade.draw_text(speed_text,
                         20, self.height - 110,
                         arcade.color.LIGHT_GRAY, 16, anchor_y="top")
        
        # Display follow status
        if self.follow_driver:
            arcade.draw_text(f"Following: {self.follow_driver}",
                             20, self.height - 140,
                             arcade.color.YELLOW, 14, anchor_y="top")

        # Draw Leaderboard - Top Right
        leaderboard_x = self.width - 20
        leaderboard_y = self.height - 40
        
        arcade.draw_text("Leaderboard", leaderboard_x, leaderboard_y, 
                         arcade.color.WHITE, 20, bold=True, anchor_x="right", anchor_y="top")

        driver_list = []
        for code, pos in frame["drivers"].items():
            color = self.driver_colors.get(code, arcade.color.WHITE)
            driver_list.append((code, color, pos))
        
        # Sort by distance
        driver_list.sort(key=lambda x: x[2].get("dist", 999), reverse=True)

        row_height = 25
        for i, (code, color, pos) in enumerate(driver_list):
            current_pos = i + 1
            if pos.get("rel_dist", 0) == 1:
                text = f"{current_pos}. {code}   OUT"
            else:
                # Show gap to car ahead (if available)
                gap_to_ahead = pos.get("gap_to_ahead")
                if gap_to_ahead is not None:
                    if current_pos == 1:
                        gap_text = "---"
                    else:
                        gap_text = f"+{gap_to_ahead:.3f}" if gap_to_ahead >= 0 else f"{gap_to_ahead:.3f}"
                    text = f"{current_pos}. {code}   {gap_text}s"
                else:
                    # Old format without gaps
                    text = f"{current_pos}. {code}"
            
            arcade.draw_text(
                text,
                leaderboard_x,
                leaderboard_y - 30 - (i * row_height),
                color,
                14,  # Slightly smaller to fit gap
                anchor_x="right", anchor_y="top"
            )

        # Draw Timeline Scrubber at very bottom
        timeline_y = 15
        timeline_height = 18
        timeline_padding = 20
        
        timeline_left = timeline_padding
        timeline_right = self.width - timeline_padding
        timeline_width = timeline_right - timeline_left
        
        # Draw timeline background
        arcade.draw_lrbt_rectangle_filled(
            timeline_left,
            timeline_right,
            timeline_y - timeline_height / 2,
            timeline_y + timeline_height / 2,
            (50, 50, 50)
        )
        
        # Draw timeline progress
        if self.n_frames > 0:
            progress = self.frame_index / (self.n_frames - 1) if self.n_frames > 1 else 0
            progress_right = timeline_left + (timeline_width * progress)
            arcade.draw_lrbt_rectangle_filled(
                timeline_left,
                progress_right,
                timeline_y - timeline_height / 2,
                timeline_y + timeline_height / 2,
                (100, 150, 255)
            )
        
        # Draw timeline handle
        handle_x = timeline_left + (timeline_width * (self.frame_index / max(1, self.n_frames - 1)) if self.n_frames > 1 else 0)
        arcade.draw_circle_filled(handle_x, timeline_y, 8, arcade.color.WHITE)
        
        # Controls Legend - Bottom Left (positioned above timeline)
        legend_x = 20
        legend_lines = [
            "Controls:",
            "[SPACE]  Pause/Resume",
            "[←/→]    Rewind / FastForward",
            "[↑/↓]    Speed +/-",
            "[1-4]    Set Speed (0.5x, 1x, 2x, 4x)",
            "[F]      Toggle Follow Camera",
            "[S]      Toggle Speed Display",
            "[L]      Toggle Labels",
        ]
        
        # Position legend above timeline (timeline is at y=15, height=18, so top is at y=24)
        # Leave some space and position legend above
        legend_spacing = 15  # Space between timeline and legend
        legend_start_y = timeline_y + timeline_height / 2 + legend_spacing + (len(legend_lines) * 22)
        
        # Draw legend (lines go downward from start_y)
        for i, line in enumerate(legend_lines):
            arcade.draw_text(
                line,
                legend_x,
                legend_start_y - (i * 22),
                arcade.color.LIGHT_GRAY if i > 0 else arcade.color.WHITE,
                12,
                bold=(i == 0)
            )

    def on_update(self, delta_time: float):
        if self.paused:
            return
        step = max(1, int(self.playback_speed))
        self.frame_index += step
        if self.frame_index >= self.n_frames:
            self.frame_index = self.n_frames - 1
        
        # Update follow camera each frame
        if self.follow_driver:
            self._update_follow_camera()

    def on_key_press(self, symbol: int, modifiers: int):
        if symbol == arcade.key.SPACE:
            self.paused = not self.paused
        elif symbol == arcade.key.RIGHT:
            self.frame_index = min(self.frame_index + 10, self.n_frames - 1)
        elif symbol == arcade.key.LEFT:
            self.frame_index = max(self.frame_index - 10, 0)
        elif symbol == arcade.key.UP:
            self.playback_speed *= 2.0
            self.playback_speed = min(self.playback_speed, 8.0)  # Cap at 8x
        elif symbol == arcade.key.DOWN:
            self.playback_speed = max(0.1, self.playback_speed / 2.0)
        elif symbol == arcade.key.KEY_1:
            self.playback_speed = 0.5
        elif symbol == arcade.key.KEY_2:
            self.playback_speed = 1.0
        elif symbol == arcade.key.KEY_3:
            self.playback_speed = 2.0
        elif symbol == arcade.key.KEY_4:
            self.playback_speed = 4.0
        elif symbol == arcade.key.F:
            # Toggle follow camera mode
            if self.follow_driver is None:
                # Start following leader
                frame = self.frames[self.frame_index]
                if frame["drivers"]:
                    leader_code = max(
                        frame["drivers"],
                        key=lambda c: (frame["drivers"][c].get("lap", 1), frame["drivers"][c].get("dist", 0))
                    )
                    self.follow_driver = leader_code
            else:
                # Stop following
                self.follow_driver = None
        elif symbol == arcade.key.S:
            # Toggle speed display
            self.show_speeds = not self.show_speeds
        elif symbol == arcade.key.L:
            # Toggle driver labels
            self.show_labels = not self.show_labels
        # Number keys 1-9 to follow specific drivers
        elif symbol == arcade.key.KEY_5:
            self._follow_driver_by_position(5)
        elif symbol == arcade.key.KEY_6:
            self._follow_driver_by_position(6)
        elif symbol == arcade.key.KEY_7:
            self._follow_driver_by_position(7)
        elif symbol == arcade.key.KEY_8:
            self._follow_driver_by_position(8)
        elif symbol == arcade.key.KEY_9:
            self._follow_driver_by_position(9)
    
    def _follow_driver_by_position(self, position: int):
        """Follow driver at specific position (1-9)."""
        frame = self.frames[self.frame_index]
        driver_list = []
        for code, pos in frame["drivers"].items():
            if pos.get("rel_dist", 0) != 1:
                driver_list.append((code, pos))
        driver_list.sort(key=lambda x: x[1].get("dist", 999), reverse=True)
        
        if 1 <= position <= len(driver_list):
            self.follow_driver = driver_list[position - 1][0]
    
    def on_mouse_press(self, x: float, y: float, button: int, modifiers: int):
        """Handle mouse clicks for timeline scrubber."""
        if button == arcade.MOUSE_BUTTON_LEFT:
            timeline_y = 30
            timeline_padding = 20
            timeline_left = timeline_padding
            timeline_right = self.width - timeline_padding
            timeline_width = timeline_right - timeline_left
            
            # Check if click is on timeline
            if timeline_left <= x <= timeline_right and timeline_y - 10 <= y <= timeline_y + 10:
                # Calculate frame index from x position
                progress = (x - timeline_left) / timeline_width
                progress = max(0, min(1, progress))  # Clamp to 0-1
                self.frame_index = int(progress * (self.n_frames - 1))
                self.frame_index = max(0, min(self.n_frames - 1, self.frame_index))

def run_arcade_replay(frames, example_lap, drivers, title: str, playback_speed: float = 1.0, driver_colors: dict = None):
    """
    Run the F1 replay visualization window.
    
    Args:
        frames: List of frame data dictionaries containing telemetry for each time step
        example_lap: Telemetry data for building track geometry
        drivers: List of driver numbers
        title: Window title
        playback_speed: Initial playback speed multiplier
        driver_colors: Dictionary mapping driver codes to RGB colors
    """
    window = F1ReplayWindow(
        frames=frames,
        example_lap=example_lap,
        drivers=drivers,
        playback_speed=playback_speed,
        driver_colors=driver_colors,
        title=title
    )
    arcade.run()