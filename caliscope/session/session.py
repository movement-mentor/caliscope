# filepath: /home/rohan/movement-mentour/caliscope/caliscope/session/session.py
# Environment for managing all created objects and the primary interface for the GUI.
# This version is focused on single camera recording for Caliscope
import caliscope.logger

from PySide6.QtCore import QObject, Signal, QThread
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from time import sleep
from queue import Queue
import cv2
from datetime import datetime

from caliscope.cameras.camera import Camera
from caliscope.cameras.live_stream import LiveStream
from caliscope.gui.frame_emitters.frame_emitter import FrameEmitter
from caliscope.configurator import Configurator

logger = caliscope.logger.get(__name__)

# Maximum number of camera ports to check when auto-detecting cameras
MAX_CAMERA_PORT_CHECK = 10

class LiveSession(QObject):
    """
    LiveSession handles camera discovery, initialization, and streaming.
    Focused on single camera support for intrinsic calibration recording.
    """
    stream_tools_loaded_signal = Signal()
    stream_tools_disconnected_signal = Signal()
    fps_target_updated = Signal()
    recording_started_signal = Signal()  # renamed from single_recording_started
    recording_stopped_signal = Signal()  # renamed from single_recording_complete
    
    def __init__(self, config: Configurator, parent=None):
        super().__init__(parent)
        self.config = config
        self.path = self.config.workspace_path

        # dictionaries of streaming related objects. key = port
        self.cameras = {}
        self.streams = {}
        self.frame_emitters = {}
        self.active_port = None
        self.stream_tools_in_process = False
        self.stream_tools_loaded = False
        self.is_recording = False
        self.video_writer = None

        # Default FPS if not specified in config
        self.fps_target = self.config.get_fps_target() if hasattr(self.config, 'get_fps_target') else 30
        logger.info(f"Default FPS target set to {self.fps_target}")

    def disconnect_cameras(self):
        """
        Shut down the streams and close the camera captures
        """
        for port, stream in self.streams.items():
            if hasattr(stream, 'stop_event'):
                stream.stop_event.set()
        self.streams = {}
        
        for port, cam in self.cameras.items():
            cam.disconnect()
        self.cameras = {}
        
        self.stream_tools_loaded = False
        self.stream_tools_disconnected_signal.emit()

    def is_camera_setup_eligible(self):
        """
        Check if there are any cameras available
        """
        return len(self.cameras) > 0

    def set_fps(self, fps_target: int):
        """
        Update the FPS for all streams
        """
        self.fps_target = fps_target
        logger.info(f"Updating streams fps to {fps_target}")
        for stream in self.streams.values():
            stream.set_fps_target(fps_target)
        
        # Save to config if method exists
        if hasattr(self.config, 'save_fps'):
            self.config.save_fps(fps_target)
        
        # Signal to update any UI elements showing FPS
        self.fps_target_updated.emit()

    def set_active_stream(self, port):
        """
        Set the active camera port and connect its frame emitter
        """
        if port not in self.streams:
            logger.error(f"Port {port} not available in streams")
            return False
            
        self.active_port = port
        
        # Unsubscribe all frame emitters first
        self.unsubscribe_all_frame_emitters()
        
        # Subscribe only the active port's frame emitter
        if port in self.frame_emitters:
            self.frame_emitters[port].subscribe()
            logger.info(f"Active stream set to port {port}")
            return True
        
        logger.error(f"No frame emitter for port {port}")
        return False

    def get_configured_camera_count(self):
        """
        Count the number of configured cameras
        """
        count = 0
        if hasattr(self.config, 'dict'):
            for key, params in self.config.dict.copy().items():
                if key.startswith("cam_") and not params.get("ignore", False):
                    count += 1
        return count

    def _find_cameras(self):
        """
        Detect available cameras using multiple threads
        Will populate self.cameras
        """
        def add_cam(port):
            try:
                logger.info(f"Trying port {port}")
                cam = Camera(port)
                logger.info(f"Success at port {port}")
                self.cameras[port] = cam
                
                # Save camera to config if method exists
                if hasattr(self.config, 'save_camera'):
                    self.config.save_camera(cam)
                
                logger.info(f"Loading stream at port {port}")
                self.streams[port] = LiveStream(cam, fps_target=self.fps_target)
            except Exception as e:
                logger.warning(f"No camera at port {port}: {e}")

        with ThreadPoolExecutor() as executor:
            for i in range(0, MAX_CAMERA_PORT_CHECK):
                if i in self.cameras.keys():
                    # don't try to connect to an already connected camera
                    pass
                else:
                    executor.submit(add_cam, i)

    def load_stream_tools(self):
        """
        Load cameras, create streams and frame emitters
        """
        def worker():
            self.stream_tools_in_process = True
            
            # Get cameras from config if available
            if hasattr(self.config, 'get_cameras'):
                self.cameras = self.config.get_cameras()
            
            # If no cameras found, scan for available ones
            if self.get_configured_camera_count() == 0:
                self._find_cameras()

            # Create streams and frame emitters for each camera
            for port, cam in self.cameras.items():
                if port not in self.streams:
                    logger.info(f"Loading Stream for port {port}")
                    stream = LiveStream(cam, fps_target=self.fps_target)
                    self.streams[port] = stream
                    
                    pixmap_edge_length = 500  # Default size for display
                    frame_emitter = FrameEmitter(stream, pixmap_edge_length=pixmap_edge_length)
                    self.frame_emitters[port] = frame_emitter

            # Adjust camera resolutions if needed
            self._adjust_resolutions()

            # Set first camera as active if none selected
            if not self.active_port and self.streams:
                self.active_port = list(self.streams.keys())[0]
                self.set_active_stream(self.active_port)
            
            self.stream_tools_loaded = True
            self.stream_tools_in_process = False

        # Run in a separate thread to avoid blocking the UI
        self.load_stream_tools_thread = QThread()
        self.load_stream_tools_thread.run = worker
        self.load_stream_tools_thread.finished.connect(self.stream_tools_loaded_signal.emit)
        self.load_stream_tools_thread.start()

    def unsubscribe_all_frame_emitters(self):
        """
        Unsubscribe all frame emitters from their streams
        """
        for emitter in self.frame_emitters.values():
            if hasattr(emitter, 'unsubscribe'):
                emitter.unsubscribe()
    
    def subscribe_all_frame_emitters(self):
        """
        Subscribe all frame emitters to their streams
        """
        for emitter in self.frame_emitters.values():
            if hasattr(emitter, 'subscribe'):
                emitter.subscribe()

    def start_recording(self, port: int, destination_directory: Path = None, 
                       fps: int = None, codec: str = 'mp4v'):
        """
        Start recording from a specific camera port
        """
        if self.is_recording:
            logger.warning("Recording already in progress")
            return False
            
        if port not in self.streams:
            logger.error(f"No stream available for port {port}")
            return False
            
        # Use provided fps or active stream's target fps
        if fps is None:
            fps = self.fps_target
        
        # Set destination directory
        if destination_directory is None:
            destination_directory = self.path / "intrinsic_calibration"
        
        # Ensure directory exists
        destination_directory.mkdir(parents=True, exist_ok=True)
        
        # Create filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"port_{port}_{timestamp}.mp4"
        filepath = destination_directory / filename
        
        # Get stream and camera
        stream = self.streams[port]
        cam = self.cameras.get(port)
        
        if not cam:
            logger.error(f"No camera object for port {port}")
            return False
            
        # Get camera resolution
        resolution = cam.size
        
        # Set stream fps target to match recording fps
        stream.set_fps_target(fps)
        
        try:
            # Initialize video writer
            self.video_writer = cv2.VideoWriter(
                str(filepath), 
                cv2.VideoWriter_fourcc(*codec), 
                fps, 
                resolution
            )
            
            if not self.video_writer.isOpened():
                logger.error(f"Failed to open VideoWriter for {filepath}")
                return False
                
            # Create recording queue and subscribe to stream
            self.recording_queue = Queue(maxsize=fps * 5 + 20)  # Buffer for ~5 seconds
            stream.subscribe(self.recording_queue)
            
            # Set recording flag
            self.is_recording = True
            self.recording_port = port
            self.recording_path = filepath
            
            # Start frame recording thread
            self._start_recording_thread()
            
            logger.info(f"Recording started on port {port}, saving to {filepath}")
            self.recording_started_signal.emit()
            return True
            
        except Exception as e:
            logger.error(f"Error starting recording: {e}")
            if self.video_writer and self.video_writer.isOpened():
                self.video_writer.release()
            self.video_writer = None
            return False

    def _start_recording_thread(self):
        """
        Start a thread to write frames from the queue to the video file
        """
        def recording_worker():
            logger.info(f"Recording thread started for port {self.recording_port}")
            frames_written = 0
            
            while self.is_recording:
                try:
                    frame_packet = self.recording_queue.get(timeout=1)
                    if frame_packet is None:  # Sentinel value
                        break
                        
                    self.video_writer.write(frame_packet.frame)
                    frames_written += 1
                    
                except Queue.Empty:
                    continue
                except Exception as e:
                    logger.error(f"Error writing frame: {e}")
                    break
                    
            # Clean up
            if self.video_writer and self.video_writer.isOpened():
                self.video_writer.release()
                
            logger.info(f"Recording completed. Wrote {frames_written} frames to {self.recording_path}")
            self.is_recording = False
            self.recording_stopped_signal.emit()
            
        self.recording_thread = QThread()
        self.recording_thread.run = recording_worker
        self.recording_thread.start()

    def stop_recording(self):
        """
        Stop the current recording if active
        """
        if not self.is_recording:
            logger.warning("No active recording to stop")
            return False
            
        logger.info("Stopping recording...")
        
        # Signal recording thread to stop
        self.is_recording = False
        
        # Add sentinel value to queue
        try:
            self.recording_queue.put_nowait(None)
        except Exception as e:
            logger.warning(f"Error adding sentinel to recording queue: {e}")
            
        # Unsubscribe queue from stream
        if hasattr(self, 'recording_port') and self.recording_port in self.streams:
            stream = self.streams[self.recording_port]
            if hasattr(self, 'recording_queue'):
                stream.unsubscribe(self.recording_queue)
                
        return True

    def _adjust_resolutions(self):
        """
        Changes the camera resolution to the value in the configuration, as
        long as it is not configured for the default resolution
        """
        def adjust_res_worker(port):
            if port not in self.streams or port not in self.cameras:
                return
                
            # Check if configuration has resolution settings for this camera
            if not hasattr(self.config, 'dict') or f"cam_{port}" not in self.config.dict:
                return
                
            stream = self.streams[port]
            size = self.config.dict[f"cam_{port}"].get("size")
            if not size:
                return
                
            default_size = self.cameras[port].default_resolution
            
            if size[0] != default_size[0] or size[1] != default_size[1]:
                logger.info(
                    f"Beginning to change resolution at port {port} from {default_size[0:2]} to {size[0:2]}"
                )
                stream.change_resolution(size)
                logger.info(
                    f"Completed change of resolution at port {port} from {default_size[0:2]} to {size[0:2]}"
                )

        with ThreadPoolExecutor() as executor:
            for port in self.cameras.keys():
                executor.submit(adjust_res_worker, port)
