# the PointHistory object requires a highly particular format
# all of the data is ultimately embedded in the initial camera array configuration
# and the calibration point data. These functions transform those two
# things into a PointHistory object that can be used to optimize the CaptureVolume
from pathlib import Path

import numpy as np
import pandas as pd

import caliscope.logger
from caliscope.cameras.camera_array import CameraArray
from caliscope.packets import FramePacket, PointPacket, SyncPacket
from caliscope.triangulate.array_stereo_triangulator import ArrayStereoTriangulator
from caliscope.triangulate.stereo_points_builder import (
    StereoPointsBuilder,
    StereoPointsPacket,
    SynchedStereoPointsPacket,
)

logger = caliscope.logger.get(__name__)


def get_stereotriangulated_table_original(camera_array: CameraArray, point_data_path: Path) -> pd.DataFrame:
    """
    Creates a table of stereotriangulated points from 2D point data stored in a CSV file.

    This function:
    1. Loads 2D point data from a CSV file
    2. Processes all sync indices to find point correspondences between camera pairs
    3. Triangulates corresponding points to get 3D coordinates
    4. Returns a DataFrame with the triangulated points data

    Args:
        camera_array: Contains camera parameters used for triangulation
        point_data_path: Path to the CSV file containing 2D point data

    Returns:
        pd.DataFrame: Table containing triangulated 3D points
    """
    logger.info(f"Beginning to create stereotriangulated points from data stored at {point_data_path}")
    point_data = pd.read_csv(point_data_path)

    xy_sync_indices = point_data["sync_index"].to_numpy()
    sync_indices = np.unique(xy_sync_indices)

    ports = [key for key in camera_array.port_index.keys()]

    # Pre-group data by sync_index to avoid repeated filtering operations
    # This creates a dictionary where keys are sync_indices and values are DataFrame subsets
    # Much more efficient than repeatedly filtering with point_data.query() in the loop
    sync_groups = {}
    for sync_index in sync_indices:
        # Create boolean mask for this sync_index (faster than .loc or .query)
        mask = point_data["sync_index"] == sync_index
        # Use the mask to get data for this sync_index
        sync_groups[sync_index] = point_data[mask]

    paired_point_builder = StereoPointsBuilder(ports)

    # Create the infrastructure for the pairwise triangulation
    array_triangulator = ArrayStereoTriangulator(camera_array)
    stereotriangulated_table = None

    # Calculate total number of sync indices for progress reporting
    total_sync_indices = len(sync_indices)

    logger.info("Begin reconstructing SyncPackets and SynchedStereoPairs... ")

    for i, sync_index in enumerate(sync_indices):
        # Report progress every 25 sync indices
        if i % 25 == 0:
            # More detailed progress report with percentage complete
            logger.info(
                            f"Processing stereotriangulation estimates...  {i}/{total_sync_indices} "
                            f"({i/total_sync_indices*100:.1f}%)"
                        )

        # Get pre-filtered data for this sync_index
        # This is faster than filtering the entire dataset each time
        port_points = sync_groups[sync_index]

        # initialize a dict to hold all the frame packets
        frame_packets = {}


        # Create frame packet for each port
        for port in ports:
            # Filter points for this port using boolean mask
            # This is faster than chained .loc operations
            port_mask = port_points["port"] == port
            port_data = port_points[port_mask]

            # Only create frame packet if there are points for this port
            if not port_data.empty:
                # Extract metadata - these are scalar values so iloc[0] is appropriate
                frame_time = port_data["frame_time"].iloc[0]
                frame_index = port_data["frame_index"].iloc[0]

                point_id = port_data["point_id"].to_numpy()

                img_loc_x = port_data["img_loc_x"].to_numpy()
                img_loc_y = port_data["img_loc_y"].to_numpy()
                img_loc = np.vstack([img_loc_x, img_loc_y]).T

                obj_loc_x = port_data["obj_loc_x"].to_numpy()
                obj_loc_y = port_data["obj_loc_y"].to_numpy()
                obj_loc = np.vstack([obj_loc_x, obj_loc_y]).T

                point_packet = PointPacket(point_id, img_loc, obj_loc)
                frame_packet = FramePacket(
                    port=port,
                    frame_index=frame_index,
                    frame_time=frame_time,
                    frame=None,
                    points=point_packet,
                )
                frame_packets[port] = frame_packet
            else:
                frame_packets[port] = None

        # create the sync packet for this sync index
        sync_packet = SyncPacket(sync_index, frame_packets)

        # get the paired point packets for all port pairs at this sync index
        synched_stereo_points: SynchedStereoPointsPacket = paired_point_builder.get_synched_paired_points(sync_packet)
        # print(synched_paired_points)
        array_triangulator.triangulate_synched_points(synched_stereo_points)

        for pair in synched_stereo_points.pairs:
            triangulated_pair: StereoPointsPacket = synched_stereo_points.stereo_points_packets[pair]
            if triangulated_pair is not None:
                if stereotriangulated_table is None:
                    stereotriangulated_table = triangulated_pair.to_table()
                else:
                    new_table = triangulated_pair.to_table()
                    for key, value in new_table.items():
                        stereotriangulated_table[key].extend(value)

    logger.info(f"Saving stereotriangulated_points.csv to {point_data_path.parent} for inspection")
    stereotriangulated_table = pd.DataFrame(stereotriangulated_table)
    stereotriangulated_table.to_csv(Path(point_data_path.parent, "stereotriangulated_points.csv"))

    logger.info("Returning dataframe of stereotriangulated points to caller")

    return stereotriangulated_table


def get_stereotriangulated_table(camera_array: CameraArray, point_data_path: Path) -> pd.DataFrame:
    """
    Creates a table of stereotriangulated points from 2D point data stored in a CSV file.
    - processing all sync indices at once.

    This function:
    1. Loads 2D point data from a CSV file
    2. Processes all sync indices to find point correspondences between camera pairs
    3. Triangulates corresponding points to get 3D coordinates
    4. Returns a DataFrame with the triangulated points data

    Args:
        camera_array: Contains camera parameters used for triangulation
        point_data_path: Path to the CSV file containing 2D point data

    Returns:
        pd.DataFrame: Table containing triangulated 3D points
    """
    logger.info(f"Beginning to create stereotriangulated points from data stored at {point_data_path}")
    point_data = pd.read_csv(point_data_path)

    # Store original values
    point_data['original_sync_index'] = point_data['sync_index']
    point_data['original_point_id'] = point_data['point_id']

    # Create unique point IDs by combining sync_index and point_id
    logger.info("Converting point_data to mimic 'single sync index' format")
    max_point_id = point_data['point_id'].max()
    point_id_multiplier = max_point_id + 1
    point_data['point_id'] = point_data['sync_index'] * point_id_multiplier + point_data['point_id']

    # Set all sync indices to 0 (treating all points as from the same virtual frame)
    point_data['sync_index'] = 0

    ports = [key for key in camera_array.port_index.keys()]

    # Process all cameras and points at once
    frame_packets = {}
    for port in ports:
        logger.info(f"Creating data for port {port}")
        port_data = point_data[point_data['port'] == port]
        if not port_data.empty:
            # Use any frame time since we're combining all frames
            frame_time = port_data['frame_time'].iloc[0]
            frame_index = 0

            point_id = port_data['point_id'].to_numpy()
            img_loc_x = port_data['img_loc_x'].to_numpy()
            img_loc_y = port_data['img_loc_y'].to_numpy()
            img_loc = np.vstack([img_loc_x, img_loc_y]).T

            obj_loc_x = port_data['obj_loc_x'].to_numpy()
            obj_loc_y = port_data['obj_loc_y'].to_numpy()
            obj_loc = np.vstack([obj_loc_x, obj_loc_y]).T

            point_packet = PointPacket(point_id, img_loc, obj_loc)
            frame_packet = FramePacket(
                port=port,
                frame_index=frame_index,
                frame_time=frame_time,
                frame=None,
                points=point_packet,
            )
            frame_packets[port] = frame_packet
        else:
            frame_packets[port] = None

    # Single triangulation pass for all points
    sync_packet = SyncPacket(0, frame_packets)
    paired_point_builder = StereoPointsBuilder(ports)
    array_triangulator = ArrayStereoTriangulator(camera_array)

    synched_stereo_points = paired_point_builder.get_synched_paired_points(sync_packet)
    array_triangulator.triangulate_synched_points(synched_stereo_points)

    # Collect and process results
    stereotriangulated_table = None
    for pair in synched_stereo_points.pairs:
        triangulated_pair = synched_stereo_points.stereo_points_packets[pair]
        if triangulated_pair is not None:
            if stereotriangulated_table is None:
                stereotriangulated_table = triangulated_pair.to_table()
            else:
                new_table = triangulated_pair.to_table()
                for key, value in new_table.items():
                    stereotriangulated_table[key].extend(value)

    # Convert to DataFrame and restore original values
    stereotriangulated_table = pd.DataFrame(stereotriangulated_table)

    # Decompose combined point_id back to original sync_index and point_id
    stereotriangulated_table['original_sync_index'] = stereotriangulated_table['point_id'] // point_id_multiplier
    stereotriangulated_table['original_point_id'] = stereotriangulated_table['point_id'] % point_id_multiplier

    # Update to original values
    stereotriangulated_table['sync_index'] = stereotriangulated_table['original_sync_index']
    stereotriangulated_table['point_id'] = stereotriangulated_table['original_point_id']
    stereotriangulated_table.drop(['original_sync_index', 'original_point_id'], axis=1, inplace=True)

    logger.info(f"Saving stereotriangulated_points.csv to {point_data_path.parent}")
    stereotriangulated_table.to_csv(Path(point_data_path.parent, "stereotriangulated_points.csv"))

    return stereotriangulated_table
