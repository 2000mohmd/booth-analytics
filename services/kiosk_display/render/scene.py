"""The kiosk's main window: a grid of overhead camera video panels (server-drawn tracking boxes
already burned into the JPEG - see services/ingestion/pipeline.py's _draw_tracks) with
client-side motion trails/pulses layered on top (render/effects.py), plus a stats sidebar (live
counter, today's totals, conversion rate) and branding footer.

Deliberately excludes the eye-level camera - see data_source.py's module docstring for why.
"""
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QGridLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

from services.kiosk_display.data_source import KioskDataSource
from services.kiosk_display.render import theme
from services.kiosk_display.render.effects import TrailTracker

log = logging.getLogger(__name__)


class CameraPanel(QWidget):
    """One overhead camera's video + trail overlay. Paints the latest JPEG frame (if any) and
    draws fading motion trails over it in the frame's own coordinate space, scaled to the
    widget's current size."""

    def __init__(self, camera_id: str):
        super().__init__()
        self.camera_id = camera_id
        self.trails = TrailTracker()
        self._pixmap: QPixmap | None = None
        self._frame_w = 0
        self._frame_h = 0

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self._label = QLabel(camera_id)
        self._label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 12px;")
        layout.addWidget(self._label)

    def update_tracks(self, frame_w: int, frame_h: int, tracks: list[dict]):
        """Called on the fast (state-poll) cadence - updates trail geometry, no imagery."""
        self._frame_w, self._frame_h = frame_w, frame_h
        self.trails.update(tracks)
        self.update()  # schedule repaint

    def update_video(self, jpg_bytes: bytes | None):
        """Called on the slower (video-poll) cadence, matching ingestion's publish rate."""
        if jpg_bytes is None:
            return
        pix = QPixmap()
        if pix.loadFromData(jpg_bytes, "JPG"):
            self._pixmap = pix
            self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(theme.PANEL_BACKGROUND))

        video_rect = self.rect().adjusted(0, 20, 0, 0)
        if self._pixmap is not None and not self._pixmap.isNull():
            scaled = self._pixmap.scaled(video_rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = video_rect.x() + (video_rect.width() - scaled.width()) // 2
            y = video_rect.y() + (video_rect.height() - scaled.height()) // 2
            painter.drawPixmap(x, y, scaled)

            if self._frame_w and self._frame_h and scaled.width():
                sx = scaled.width() / self._frame_w
                sy = scaled.height() / self._frame_h
                self._paint_trails(painter, x, y, sx, sy)
        else:
            painter.setPen(QColor(theme.TEXT_MUTED))
            painter.drawText(video_rect, Qt.AlignCenter, "no signal")

    def _paint_trails(self, painter: QPainter, ox: int, oy: int, sx: float, sy: float):
        for track_id in self.trails.active_track_ids():
            points = self.trails.trail(track_id)
            if len(points) < 2:
                continue
            for i in range(1, len(points)):
                x0, y0, _ = points[i - 1]
                x1, y1, a1 = points[i]
                color = QColor(theme.TRAIL_COLOR)
                color.setAlphaF(max(0.0, min(1.0, a1)) * 0.8)
                painter.setPen(QPen(color, 3))
                painter.drawLine(int(ox + x0 * sx), int(oy + y0 * sy), int(ox + x1 * sx), int(oy + y1 * sy))

            pulse = self.trails.pulse_alpha(track_id)
            if pulse > 0:
                x, y, _ = points[-1]
                glow = QColor(theme.NEW_TRACK_PULSE_COLOR)
                glow.setAlphaF(pulse)
                radius = 10 + int(20 * pulse)
                painter.setPen(QPen(glow, 3))
                painter.drawEllipse(int(ox + x * sx - radius), int(oy + y * sy - radius), radius * 2, radius * 2)


class StatsPanel(QWidget):
    """Big live counter + today's totals + conversion-rate/branding footer."""

    def __init__(self):
        super().__init__()
        self.setStyleSheet(f"background-color: {theme.PANEL_BACKGROUND};")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)

        self._current_label = self._big_stat(layout, "ON THE FLOOR NOW", theme.GREEN)
        self._today_label = self._big_stat(layout, "VISITORS TODAY", theme.CYAN)
        self._capture_label = self._big_stat(layout, "CAPTURE RATE", theme.AMBER)

        footer = QLabel("AI POWERED LIVE EVENT ANALYTICS")
        footer.setAlignment(Qt.AlignCenter)
        footer.setStyleSheet(f"color: {theme.TEXT_MUTED}; letter-spacing: 4px; margin-top: 40px;")
        footer.setFont(QFont(theme.FONT_FAMILY, 12))
        layout.addWidget(footer)

    def _big_stat(self, layout: QVBoxLayout, caption: str, color: str) -> QLabel:
        value = QLabel("--")
        value.setAlignment(Qt.AlignCenter)
        value.setStyleSheet(f"color: {color};")
        value.setFont(QFont(theme.FONT_FAMILY, 56, QFont.Bold))
        layout.addWidget(value)

        label = QLabel(caption)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(f"color: {theme.TEXT_MUTED}; letter-spacing: 2px; margin-bottom: 24px;")
        label.setFont(QFont(theme.FONT_FAMILY, 14))
        layout.addWidget(label)
        return value

    def update_stats(self, occupancy: dict | None, totals: dict | None):
        if occupancy is not None:
            self._current_label.setText(str(occupancy["current_count"]))
        if totals is not None:
            self._today_label.setText(str(totals["passersby"]))
            self._capture_label.setText(f"{round(totals['capture_rate'] * 100)}%")


class KioskWindow(QMainWindow):
    def __init__(self, data_source: KioskDataSource, poll_interval_ms: int = 150):
        super().__init__()
        self.data_source = data_source
        self.setWindowTitle("Booth Analytics - Live")
        self.setStyleSheet(f"background-color: {theme.BACKGROUND};")

        central = QWidget()
        self.setCentralWidget(central)
        outer = QGridLayout(central)

        self._panels: dict[str, CameraPanel] = {}
        cols = 2
        for i, camera_id in enumerate(sorted(data_source.overhead_camera_ids)):
            panel = CameraPanel(camera_id)
            self._panels[camera_id] = panel
            outer.addWidget(panel, i // cols, i % cols)

        self._stats = StatsPanel()
        outer.addWidget(self._stats, 0, cols, len(self._panels), 1)

        # Track/stats state polls fast (smooth trails); video polls at ingestion's own publish
        # rate (services/ingestion/pipeline.py's DEBUG_VIDEO_SAMPLE_EVERY_S) - polling video
        # faster than it's actually produced would just re-fetch the same bytes repeatedly.
        self._state_timer = QTimer(self)
        self._state_timer.timeout.connect(self._poll_state)
        self._state_timer.start(poll_interval_ms)

        self._video_timer = QTimer(self)
        self._video_timer.timeout.connect(self._poll_video)
        self._video_timer.start(200)

    def _poll_state(self):
        try:
            state = self.data_source.fetch_live_state()
        except Exception:
            log.exception("fetch_live_state failed - showing last-known state")
            return
        self._stats.update_stats(state.get("occupancy"), state.get("totals"))
        for camera_id, panel in self._panels.items():
            cam = state["cameras"].get(camera_id, {"frame_w": 0, "frame_h": 0, "tracks": []})
            panel.update_tracks(cam["frame_w"], cam["frame_h"], cam["tracks"])

    def _poll_video(self):
        for camera_id, panel in self._panels.items():
            try:
                jpg = self.data_source.fetch_frame(camera_id)
            except Exception:
                log.exception("fetch_frame failed for %s", camera_id)
                continue
            panel.update_video(jpg)
