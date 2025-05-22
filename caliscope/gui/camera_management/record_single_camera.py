import cv2
import numpy as np
from PySide6.QtCore import Qt, QTimer, Slot, Signal, QThread, QSize, QObject, QUrl 
from PySide6.QtGui import QImage, QPixmap, QTransform
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QComboBox,
    QSpinBox,
    QPushButton,
    QGroupBox,
    QGridLayout,
    QSizePolicy,
)
from pathlib import Path
from datetime import datetime
from enum import Enum
from threading import Event

import time

from caliscope.session.session import LiveSession 
from caliscope.cameras.live_stream import LiveStream
from caliscope.gui.frame_emitters.frame_emitter import FrameEmitter # Adjusted import path
from caliscope.interface import FramePacket 
import caliscope.logger 

logger = caliscope.logger.get(__name__)

_RENDER_FPS = 6
_RECORD_FPS = 30

class NextRecordingActions(Enum):
    SELECT_CAMERA = "Select a Camera"
    START_RECORDING = "Start Recording"
    COUNTDOWN = "Cancel Countdown" 
    STOP_RECORDING = "Stop Recording"
    SAVING = "--Saving--"

class RecordingThread(QThread):
    finished_saving = Signal()
    error_signal = Signal(str)

    def __init__(self, stream : LiveStream, video_writer: cv2.VideoWriter, port: int, parent=None):
        super().__init__(parent)
        self.stream = stream
        self.video_writer = video_writer
        self.port = port
        self._is_running = True

    def run(self):
        logger.info(f"RecordingThread for port {self.port} started.")
        frames_written = 0
        try:
            while self._is_running:
                try:
                    self.stream.frame_updated.wait()
                    frame_packet: FramePacket = self.stream.latest_frame_packet
                    if frame_packet is None: 
                        logger.info(f"RecordingThread for port {self.port} received sentinel. Stopping.")
                        break
                    self.video_writer.write(frame_packet.frame)
                    frames_written += 1
                except Exception as e:
                    logger.error(f"Error writing frame in RecordingThread for port {self.port}: {e}")
                    self.error_signal.emit(f"Error writing frame: {e}")
                    break
            logger.info(f"RecordingThread for port {self.port}: Main loop exited. Frames written: {frames_written}")
        finally:
            if self.video_writer.isOpened():
                self.video_writer.release()
            logger.info(f"RecordingThread for port {self.port}: VideoWriter released.")
            self.finished_saving.emit()

    def stop(self):
        logger.info(f"RecordingThread for port {self.port}: Stop called.")
        self._is_running = False



class RecordSingleCameraWidget(QWidget):
    def __init__(self, live_session: LiveSession, parent=None):
        super().__init__(parent)
        self.live_session = live_session
        self.selected_port = None
        self.active_stream = None 
        self.frame_emitter = None 
        self.video_writer = None
        self.recording_thread = None
        self.recording_subscriber_id = "RecordingThread"

        self.current_action = NextRecordingActions.SELECT_CAMERA

        # Sound Effects - User needs to provide these sound files
        self.countdown_beep_effect = QSoundEffect(self)
        self.countdown_beep_effect.setSource(QUrl.fromLocalFile("sounds/countdown_beep.wav"))
        
        self.final_beep_effect = QSoundEffect(self)
        self.final_beep_effect.setSource(QUrl.fromLocalFile("sounds/final_beep.wav"))

        self.stop_beep_effect = QSoundEffect(self)
        self.stop_beep_effect.setSource(QUrl.fromLocalFile("sounds/final_beep.wav"))

        
        self._init_ui()
        self._connect_widgets()
        self.populate_camera_ports() 

    def _init_ui(self):
        main_layout = QHBoxLayout(self)
        
        left_panel = QVBoxLayout()
        self.live_view_label = QLabel("Select a camera to start the live stream.")
        self.live_view_label.setAlignment(Qt.AlignCenter)
        self.live_view_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.live_view_label.setMinimumSize(640, 480) 
        self.live_view_label.setStyleSheet("border: 1px solid gray; background-color: black;")
        left_panel.addWidget(self.live_view_label)
        main_layout.addLayout(left_panel, 2) 

        right_panel = QVBoxLayout()
        right_panel.setAlignment(Qt.AlignTop)

        cam_select_group = QGroupBox("Camera Selection")
        cam_select_layout = QVBoxLayout()
        self.port_selector_combo = QComboBox()
        self.port_selector_combo.setPlaceholderText("No cameras available")
        cam_select_layout.addWidget(QLabel("Camera Port:"))
        cam_select_layout.addWidget(self.port_selector_combo)
        
        # Add resolution selector
        cam_select_layout.addWidget(QLabel("Resolution:"))
        self.resolution_selector_combo = QComboBox()
        self.resolution_selector_combo.setPlaceholderText("No resolutions available")
        self.resolution_selector_combo.setEnabled(False)
        cam_select_layout.addWidget(self.resolution_selector_combo)
        
        self.resolution_label = QLabel("Current Resolution: -")
        cam_select_layout.addWidget(self.resolution_label)
        
        cam_select_group.setLayout(cam_select_layout)
        right_panel.addWidget(cam_select_group)

        fps_group = QGroupBox("FPS Control")
        fps_layout = QGridLayout()
        self.record_fps_spin = QSpinBox()
        self.record_fps_spin.setMinimum(1)
        self.record_fps_spin.setMaximum(120)
        self.record_fps_spin.setValue(_RECORD_FPS)
        fps_layout.addWidget(QLabel("Record FPS:"), 0, 0)
        fps_layout.addWidget(self.record_fps_spin, 0, 1)
        
        self.render_fps_spin = QSpinBox()
        self.render_fps_spin.setMinimum(1)
        self.render_fps_spin.setMaximum(60)
        self.render_fps_spin.setValue(_RENDER_FPS)
        fps_layout.addWidget(QLabel("Render FPS (View):"), 1, 0)
        fps_layout.addWidget(self.render_fps_spin, 1, 1)
        fps_group.setLayout(fps_layout)
        right_panel.addWidget(fps_group)

        recording_group = QGroupBox("Recording Controls")
        recording_layout = QGridLayout()
        self.start_stop_button = QPushButton(self.current_action.value)
        recording_layout.addWidget(self.start_stop_button, 0, 0, 1, 2)

        self.countdown_duration_spin = QSpinBox()
        self.countdown_duration_spin.setMinimum(0) 
        self.countdown_duration_spin.setMaximum(60) 
        self.countdown_duration_spin.setValue(0)
        self.countdown_duration_spin.setToolTip("Countdown duration (seconds). 0 for immediate start.")
        recording_layout.addWidget(QLabel("Countdown (s):"), 1, 0)
        recording_layout.addWidget(self.countdown_duration_spin, 1, 1)

        self.record_length_spin = QSpinBox()
        self.record_length_spin.setMinimum(0) 
        self.record_length_spin.setMaximum(3600) 
        self.record_length_spin.setValue(10) 
        self.record_length_spin.setToolTip("Recording duration (seconds). 0 for indefinite (manual stop).")
        recording_layout.addWidget(QLabel("Record Length (s):"), 2, 0)
        recording_layout.addWidget(self.record_length_spin, 2, 1)
        
        self.record_duration_label = QLabel("Duration: 0s")
        recording_layout.addWidget(self.record_duration_label, 3, 0)
        self.record_duration_remaining_label = QLabel("Remaining: N/A")
        self.record_duration_remaining_label.setVisible(False)
        recording_layout.addWidget(self.record_duration_remaining_label, 3, 1)
        recording_group.setLayout(recording_layout)
        right_panel.addWidget(recording_group)
        main_layout.addLayout(right_panel, 1) 

        self.countdown_timer = QTimer(self)
        self.countdown_timer.setSingleShot(False) 
        self.current_countdown_value = 0

        self.recording_duration_timer = QTimer(self)
        self.current_record_duration_s = 0
        self.target_record_length_s = 0

    def _connect_widgets(self):
        self.port_selector_combo.currentIndexChanged.connect(self.on_port_selected)
        self.resolution_selector_combo.currentIndexChanged.connect(self.on_resolution_selected)
        self.record_fps_spin.valueChanged.connect(self.on_record_fps_changed)
        self.render_fps_spin.valueChanged.connect(self.on_render_fps_changed)
        self.start_stop_button.clicked.connect(self.toggle_start_stop)
        self.countdown_timer.timeout.connect(self.update_countdown_display)
        self.recording_duration_timer.timeout.connect(self.update_recording_duration)

    def populate_camera_ports(self):
        self.port_selector_combo.blockSignals(True) 
        self.port_selector_combo.clear()
        
        if not self.live_session or not hasattr(self.live_session, 'cameras') or not hasattr(self.live_session, 'streams') or not self.live_session.cameras or not self.live_session.streams:
            self.port_selector_combo.setPlaceholderText("No cameras/streams ready")
            self.port_selector_combo.setEnabled(False)
            self.current_action = NextRecordingActions.SELECT_CAMERA
            self._set_inputs_enabled(False) 
            self.update_button_state()
            self.port_selector_combo.blockSignals(False)
            return

        self.port_selector_combo.setEnabled(True)
        available_ports = sorted([p for p in self.live_session.cameras if p in self.live_session.streams])

        if not available_ports:
            self.port_selector_combo.setPlaceholderText("No usable camera streams")
            self.port_selector_combo.setEnabled(False)
            self.current_action = NextRecordingActions.SELECT_CAMERA
            self._set_inputs_enabled(False)
            self.update_button_state()
            self.port_selector_combo.blockSignals(False)
            return

        for port in available_ports:
            self.port_selector_combo.addItem(f"Port {port}", userData=port)
        
        self.port_selector_combo.blockSignals(False)
        if available_ports:
            # currentIndexChanged will fire if index is different or if it's the first time items are added (and index becomes 0)
            if self.port_selector_combo.currentIndex() != 0:
                 self.port_selector_combo.setCurrentIndex(0)
            else: # Manually trigger if index is already 0 but items were just populated
                 self.on_port_selected(0)
        else: 
            self.on_port_selected(-1) 

    @Slot(int)
    def on_port_selected(self, index):
        if self.frame_emitter: 
            self.frame_emitter.keep_collecting.clear()
            self.frame_emitter.unsubscribe()
            self.frame_emitter.stop()
            self.frame_emitter.ImageBroadcast.disconnect(self.update_live_view)
            self.frame_emitter = None
        
        self.live_view_label.setText("Connecting to camera...")
        self.live_view_label.setPixmap(QPixmap()) 

        # Clear resolution selector
        self.resolution_selector_combo.blockSignals(True)
        self.resolution_selector_combo.clear()
        self.resolution_selector_combo.setEnabled(False)
        self.resolution_selector_combo.blockSignals(False)

        if index < 0 or not self.live_session or not self.live_session.cameras:
            self.selected_port = None
            self.active_stream = None
            self.live_view_label.setText("No camera selected or camera unavailable.")
            self.resolution_label.setText("Current Resolution: -")
            self.current_action = NextRecordingActions.SELECT_CAMERA
            self._set_inputs_enabled(False) 
            self.update_button_state()
            return

        self.selected_port = self.port_selector_combo.itemData(index)
        logger.info(f"Camera port {self.selected_port} selected.")

        if self.selected_port not in self.live_session.streams:
            logger.error(f"No live stream available for port {self.selected_port} in session.")
            self.live_view_label.setText(f"Stream for port {self.selected_port} not ready.")
            self.active_stream = None
            self.current_action = NextRecordingActions.SELECT_CAMERA
            self._set_inputs_enabled(False)
            self.update_button_state()
            return

        self.active_stream = self.live_session.streams[self.selected_port]
        
        cam_obj = self.live_session.cameras.get(self.selected_port)
        if cam_obj:
            # Get current resolution
            width, height = cam_obj.size
            self.resolution_label.setText(f"Current Resolution: {width}x{height}")
            
            # Populate available resolutions
            self.populate_available_resolutions(cam_obj)
        else:
            self.resolution_label.setText("Current Resolution: Unknown")

        try:
            # The FrameEmitter constructor doesn't directly take an FPS value,
            # but accepts a pixmap_edge_length. We'll subscribe to the stream in its constructor.
            self.frame_emitter = FrameEmitter(self.active_stream, _RENDER_FPS, self.live_view_label.width()) # Defualt to 6 FPS for rendering
            self.frame_emitter.subscribe()
            self.frame_emitter.ImageBroadcast.connect(self.update_live_view)
            # The frame_emitter already calls start() in its constructor
            logger.info(f"FrameEmitter started for port {self.selected_port} at {self.render_fps_spin.value()} FPS for rendering.")
        except Exception as e:
            logger.error(f"Failed to create or start FrameEmitter: {e}")
            self.live_view_label.setText(f"Error starting live view: {e}")
            self.current_action = NextRecordingActions.SELECT_CAMERA # Revert state
            self._set_inputs_enabled(False)
            self.update_button_state()
            return

        self.on_record_fps_changed(self.record_fps_spin.value()) 
        
        self.current_action = NextRecordingActions.START_RECORDING
        self._set_inputs_enabled(True)
        self.update_button_state()
        
    def populate_available_resolutions(self, camera):
        """Populate the resolution selector dropdown with available camera resolutions"""
        self.resolution_selector_combo.blockSignals(True)
        self.resolution_selector_combo.clear()
        
        try:
            # Use the new method to get all available resolutions
            available_resolutions = camera.get_all_available_resolutions()
            
            if not available_resolutions:
                logger.warning(f"No available resolutions found for camera {camera.port}")
                self.resolution_selector_combo.setPlaceholderText("No resolutions found")
                self.resolution_selector_combo.setEnabled(False)
                self.resolution_selector_combo.blockSignals(False)
                return
                
            # Add current resolution first if not in the list
            current_resolution = camera.size
            current_in_list = False
            
            for res in available_resolutions:
                width, height = res
                self.resolution_selector_combo.addItem(f"{width}x{height}", userData=res)
                if res == current_resolution:
                    current_in_list = True
            
            if not current_in_list:
                self.resolution_selector_combo.insertItem(0, f"{current_resolution[0]}x{current_resolution[1]} (current)", userData=current_resolution)
            
            # Select current resolution in dropdown
            for i in range(self.resolution_selector_combo.count()):
                if self.resolution_selector_combo.itemData(i) == current_resolution:
                    self.resolution_selector_combo.setCurrentIndex(i)
                    break
            
            self.resolution_selector_combo.setEnabled(True)
        except Exception as e:
            logger.error(f"Error populating resolutions: {e}")
            self.resolution_selector_combo.setPlaceholderText("Error getting resolutions")
            self.resolution_selector_combo.setEnabled(False)
        
        self.resolution_selector_combo.blockSignals(False)
    
    @Slot(int)
    def on_resolution_selected(self, index):
        """Handle resolution selection change"""
        if index < 0 or not self.live_session or self.selected_port is None:
            logger.error("Invalid resolution index or no camera selected.")
            logger.info(f"Index: {index}, Selected Port: {self.selected_port}, Live Session: {self.live_session}")
            return
            
        selected_resolution = self.resolution_selector_combo.itemData(index)
        if not selected_resolution:
            logger.error("Selected resolution is invalid.")
            return
            
        width, height = selected_resolution
        
        # Get camera object
        cam_obj = self.live_session.cameras.get(self.selected_port)
        if not cam_obj:
            logger.error(f"Camera object for port {self.selected_port} not found.")
            return
            
        # Get current resolution
        current_width, current_height = cam_obj.size
        
        # If resolution is already set to the selected one, do nothing
        if (current_width, current_height) == (width, height):
            logger.info(f"Camera already at resolution {width}x{height}. No change needed.")
            return
            
        logger.info(f"Changing camera resolution to {width}x{height}")
        self.live_view_label.setText(f"Changing resolution to {width}x{height}...")
        
        # Temporarily disable UI during resolution change
        self._set_inputs_enabled(False)
        self.resolution_selector_combo.setEnabled(False)
        
        try:
            # Stop frame emitter
            if self.frame_emitter:
                self.frame_emitter.keep_collecting.clear()
                self.frame_emitter.unsubscribe()
                self.frame_emitter.stop()
                self.frame_emitter.ImageBroadcast.disconnect(self.update_live_view)
                self.frame_emitter = None
            
            # Change resolution
            actual_resolution = cam_obj.change_resolution(width, height)
            logger.info(f"Resolution changed to {actual_resolution}")
            
            # Update UI with actual resolution
            self.resolution_label.setText(f"Current Resolution: {actual_resolution[0]}x{actual_resolution[1]}")
            
            # Also need to recreate the stream as resolution changed
            if self.selected_port in self.live_session.streams:
                # Reconnect to the stream
                self.active_stream = self.live_session.streams[self.selected_port]
                
                # Restart frame emitter
                try:
                    self.frame_emitter = FrameEmitter(self.active_stream, _RENDER_FPS, self.live_view_label.width())
                    self.frame_emitter.subscribe()
                    self.frame_emitter.ImageBroadcast.connect(self.update_live_view)
                    logger.info(f"FrameEmitter restarted after resolution change at {self.render_fps_spin.value()} FPS.")
                except Exception as e:
                    logger.error(f"Failed to restart FrameEmitter after resolution change: {e}")
                    self.live_view_label.setText(f"Error restarting view: {e}")
        except Exception as e:
            logger.error(f"Error changing resolution: {e}")
            self.live_view_label.setText(f"Error changing resolution: {e}")
        
        # Re-enable UI
        self._set_inputs_enabled(True)
        self.resolution_selector_combo.setEnabled(True)

    @Slot(QPixmap)
    def update_live_view(self, pixmap: QPixmap):
        if not self.live_session or not self.active_stream or not self.isVisible():
            return 
        
        # Create a transformation to flip the image
        transform = QTransform()
        
        # For horizontal flip (mirroring left to right)
        transform.scale(-1, 1)
        
        # For vertical flip (mirroring top to bottom)
        # transform.scale(1, -1)
        
        # For both horizontal and vertical flip
        # transform.scale(-1, -1)
        
        # Apply the transformation
        flipped_pixmap = pixmap.transformed(transform)
        
        # Set the flipped pixmap to the label
        self.live_view_label.setPixmap(flipped_pixmap)

    @Slot(int)
    def on_record_fps_changed(self, value):
        if self.active_stream:
            self.active_stream.set_fps_target(value)
            logger.info(f"Record FPS for port {self.selected_port} set to {value}.")

    @Slot(int)
    def on_render_fps_changed(self, value):
        if self.frame_emitter:
            # Note: This functionality isn't directly supported by FrameEmitter
            # You may want to modify the FrameEmitter class to support this
            logger.info(f"Render FPS for port {self.selected_port} view set to {value}.")

            try:
                old_emitter = self.frame_emitter
                self.frame_emitter = FrameEmitter(self.active_stream, value, self.live_view_label.width())
                self.frame_emitter.ImageBroadcast.connect(self.update_live_view)
                self.frame_emitter.subscribe()
                
                # Clean up the old emitter
                old_emitter.keep_collecting.clear()
                old_emitter.ImageBroadcast.disconnect(self.update_live_view)
                old_emitter.unsubscribe()
                old_emitter.stop()
            except Exception as e:
                logger.error(f"Error updating render FPS: {e}")

    def toggle_start_stop(self):
        logger.info(f"toggle_start_stop called. Current action: {self.current_action}")
        if self.current_action == NextRecordingActions.START_RECORDING:
            countdown_s = self.countdown_duration_spin.value()
            if countdown_s > 0:
                self.current_countdown_value = countdown_s
                self.current_action = NextRecordingActions.COUNTDOWN
                self.update_button_state() 
                self.start_stop_button.setText(f"{NextRecordingActions.COUNTDOWN.value} ({self.current_countdown_value}s)")
                self.countdown_timer.start(1000) 
            else:
                self._start_actual_recording()
        
        elif self.current_action == NextRecordingActions.COUNTDOWN:
            self.countdown_timer.stop()
            self.current_action = NextRecordingActions.START_RECORDING
            self.update_button_state()

        elif self.current_action == NextRecordingActions.STOP_RECORDING:
            self._stop_actual_recording()

        elif self.current_action == NextRecordingActions.SAVING:
            logger.info("Recording is currently saving. Please wait.")

        elif self.current_action == NextRecordingActions.SELECT_CAMERA:
            logger.warning("No camera selected. Cannot start recording.")

    def update_countdown_display(self):
        self.current_countdown_value -= 1
        if self.current_countdown_value > 0:
            self.start_stop_button.setText(f"{NextRecordingActions.COUNTDOWN.value} ({self.current_countdown_value}s)")
            # Play countdown beep for the last 3 seconds
            if self.current_countdown_value <= 3:
                self.countdown_beep_effect.play()
        else:
            self.countdown_timer.stop()
            self._start_actual_recording()

    def _start_actual_recording(self):
        if not self.active_stream or self.selected_port is None:
            logger.error("Cannot start recording: No active stream or port selected.")
            self.current_action = NextRecordingActions.START_RECORDING 
            self.update_button_state()
            return

        # Play sound effect when recording starts
        self.final_beep_effect.play()
        
        logger.info(f"Starting actual recording for port {self.selected_port}.")
        self.current_action = NextRecordingActions.STOP_RECORDING
        self._set_inputs_enabled(False) 
        self.update_button_state()

        if not self.live_session or not hasattr(self.live_session, 'config') or not hasattr(self.live_session.config, 'workspace_path') or self.live_session.config.workspace_path is None:
            logger.error("Live session, config, or workspace_path not properly initialized. Cannot determine save path.")
            self.on_recording_error("Session/config error.")
            return
            
        intrinsic_dir = self.live_session.config.workspace_path / "calibration/intrinsic"
        try:
            intrinsic_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logger.error(f"Could not create directory {intrinsic_dir}: {e}")
            self.on_recording_error(f"Directory creation failed: {e}")
            return

        filename = f"port_{self.selected_port}.mp4"
        filepath = intrinsic_dir / filename

        cam_obj = self.live_session.cameras.get(self.selected_port)
        if not cam_obj:
            logger.error(f"Camera object for port {self.selected_port} not found. Cannot start recording.")
            self.on_recording_error("Camera object not found.")
            return
            
        resolution = cam_obj.size 
        record_fps = self.record_fps_spin.value()
        
        self.active_stream.set_fps_target(record_fps) 
        logger.info(f"Ensured active stream ({self.selected_port}) FPS target is {record_fps} for recording.")

        try:
            self.video_writer = cv2.VideoWriter(str(filepath), cv2.VideoWriter_fourcc(*'mp4v'), record_fps, resolution)
            if not self.video_writer.isOpened():
                logger.error(f"Failed to open VideoWriter for {filepath}")
                self.on_recording_error("Failed to open VideoWriter.")
                return
        except Exception as e:
            logger.error(f"Exception creating VideoWriter for {filepath}: {e}")
            self.on_recording_error(f"VideoWriter creation error: {e}")
            return
        
        self.active_stream.subscribe(self.recording_subscriber_id)
        
        self.recording_thread = RecordingThread(self.active_stream, self.video_writer, self.selected_port, self)
        self.recording_thread.finished_saving.connect(self.on_recording_thread_finished)
        self.recording_thread.error_signal.connect(self.on_recording_error)
        self.recording_thread.start()

        logger.info(f"Recording started. Saving to {filepath} at {record_fps} FPS, resolution {resolution}.")

        self.current_record_duration_s = 0
        self.target_record_length_s = self.record_length_spin.value()
        self.record_duration_label.setText("Duration: 0s")
        self.record_duration_remaining_label.setVisible(True)
        if self.target_record_length_s > 0:
            self.record_duration_remaining_label.setText(f"Remaining: {self.target_record_length_s}s")
        else:
            self.record_duration_remaining_label.setText("Remaining: Indefinite")
        self.recording_duration_timer.start(1000)

    def update_recording_duration(self):
        self.current_record_duration_s += 1
        self.record_duration_label.setText(f"Duration: {self.current_record_duration_s}s")

        if self.target_record_length_s > 0:
            remaining_s = self.target_record_length_s - self.current_record_duration_s
            self.record_duration_remaining_label.setText(f"Remaining: {remaining_s}s")
            if remaining_s <= 0:
                self.toggle_start_stop() 
        else:
            self.record_duration_remaining_label.setText("Remaining: Indefinite")

    def _stop_actual_recording(self):
        logger.info("Stopping actual recording...")
        self.recording_duration_timer.stop()
        self.current_action = NextRecordingActions.SAVING
        self.update_button_state() 

        # Play sound effect when recording stops
        self.stop_beep_effect.play()

        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop() 
        else: 
            if self.video_writer and self.video_writer.isOpened():
                self.video_writer.release()
            self.on_recording_complete() 

        if self.active_stream and self.recording_subscriber_id:
            try: 
                self.active_stream.unsubscribe(self.recording_subscriber_id)
                logger.info(f"Unsubscribed recording from stream {self.selected_port}.")
            except Exception as e: 
                logger.warning(f"Could not unsubscribe recording from stream {self.selected_port} during stop: {e}")

    @Slot()
    def on_recording_thread_finished(self):
        logger.info("Recording thread finished saving.")
        self.recording_thread = None 
        self.on_recording_complete()

    @Slot(str)
    def on_recording_error(self, error_message):
        logger.error(f"Recording error: {error_message}")
        self.recording_duration_timer.stop()
        self.countdown_timer.stop()

        if self.recording_thread and self.recording_thread.isRunning():
            self.recording_thread.stop() 
        elif self.video_writer and self.video_writer.isOpened(): 
            self.video_writer.release()
        
        self.recording_thread = None
        self.video_writer = None
        if self.active_stream:
            try:
                self.active_stream.unsubscribe(self.recording_subscriber_id)
            except Exception: pass

        self.current_action = NextRecordingActions.START_RECORDING 
        self._set_inputs_enabled(True) 
        self.update_button_state()
        self.live_view_label.setText(f"Recording failed: {error_message}.\\nSelect camera or try again.")

    def on_recording_complete(self):
        logger.info("Recording complete and saved (or error handled).")
        self.current_action = NextRecordingActions.START_RECORDING
        self._set_inputs_enabled(True) 
        self.update_button_state()
        self.record_duration_label.setText("Duration: 0s")
        self.record_duration_remaining_label.setText("Remaining: N/A")
        self.record_duration_remaining_label.setVisible(False)

    def update_button_state(self):
        self.start_stop_button.setText(self.current_action.value)
        
        can_interact_with_button = True
        if self.current_action == NextRecordingActions.SAVING:
            can_interact_with_button = False
        elif self.current_action == NextRecordingActions.SELECT_CAMERA:
            can_interact_with_button = False
        elif self.current_action == NextRecordingActions.COUNTDOWN:
            self.start_stop_button.setText(f"{NextRecordingActions.COUNTDOWN.value} ({self.current_countdown_value}s)")

        self.start_stop_button.setEnabled(can_interact_with_button)

    def _set_inputs_enabled(self, enabled: bool):
        self.record_fps_spin.setEnabled(enabled)
        self.render_fps_spin.setEnabled(enabled)
        self.countdown_duration_spin.setEnabled(enabled)
        self.record_length_spin.setEnabled(enabled)
        self.resolution_selector_combo.setEnabled(enabled and self.selected_port is not None)
        
        # Port selector is enabled/disabled based on camera availability, not this general function
        # self.port_selector_combo.setEnabled(enabled) 

        if not enabled and self.selected_port is None:
            self.start_stop_button.setEnabled(False)
        elif enabled and self.selected_port is not None: 
             if self.current_action not in [NextRecordingActions.COUNTDOWN, NextRecordingActions.STOP_RECORDING, NextRecordingActions.SAVING]:
                self.current_action = NextRecordingActions.START_RECORDING 
             self.update_button_state() 

    def closeEvent(self, event):
        logger.info("RecordSingleCameraWidget close event triggered.")
        if self.frame_emitter:
            self.frame_emitter.keep_collecting.clear()
            self.frame_emitter.ImageBroadcast.disconnect(self.update_live_view)
            self.frame_emitter.unsubscribe()
            self.frame_emitter.stop()
            logger.info("Stopped frame emitter.")
        
        if self.recording_thread and self.recording_thread.isRunning():
            logger.warning("Recording in progress during close event. Attempting to stop and save.")
            self._stop_actual_recording() 
        elif self.video_writer and self.video_writer.isOpened(): 
             self.video_writer.release()
             logger.info("Released VideoWriter during close event.")

        super().closeEvent(event)
