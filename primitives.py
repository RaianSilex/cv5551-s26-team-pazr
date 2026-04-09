"""
Robot primitive actions and perception for the beverage-making robot.

Contains:
- ContainerDetector: AprilTag-based pose detection for containers
- Motion primitives: pick, place, move, pour, stir
- High-level task sequences: execute_add_ingredient, execute_stir
"""

import cv2, numpy, time
from pupil_apriltags import Detector

from checkpoint0 import get_transform_camera_robot
from checkpoint1 import grasp_cube, CUBE_TAG_FAMILY, CUBE_TAG_SIZE
from config import (
    INGREDIENT_TAG_MAP, STIRRER_TAG_ID, MAIN_CUP_POSITION,
    PRE_GRASP_HEIGHT, POUR_HEIGHT, STIR_DEPTH, STIR_CYCLES, POUR_TILT_ANGLE,
)


def _get_cup_xyz_mm():
    """Return main cup position in mm (already in mm from config)."""
    return (
        MAIN_CUP_POSITION['x'],
        MAIN_CUP_POSITION['y'],
        MAIN_CUP_POSITION['z'],
    )


# ──────────────────────────────────────────────
# AprilTag Detection
# ──────────────────────────────────────────────
class ContainerDetector:
    """Detects containers/objects via their AprilTags and returns poses in robot frame."""

    def __init__(self, camera_intrinsic):
        self.camera_intrinsic = camera_intrinsic
        self.detector = Detector(families=CUBE_TAG_FAMILY)

    def detect_all(self, observation):
        """
        Detect all AprilTags (ID >= 5) and return a dict mapping tag_id to a
        4x4 pose in the robot base frame (meters).
        """
        t_cam_robot = get_transform_camera_robot(observation, self.camera_intrinsic)
        if t_cam_robot is None:
            print('Could not compute camera-to-robot transform.')
            return None

        if len(observation.shape) > 2:
            gray = cv2.cvtColor(observation, cv2.COLOR_BGRA2GRAY)
        else:
            gray = observation

        fx = self.camera_intrinsic[0, 0]
        fy = self.camera_intrinsic[1, 1]
        cx = self.camera_intrinsic[0, 2]
        cy = self.camera_intrinsic[1, 2]

        tags = self.detector.detect(
            gray, estimate_tag_pose=True,
            camera_params=[fx, fy, cx, cy],
            tag_size=CUBE_TAG_SIZE,
        )

        poses = {}
        for tag in tags:
            if tag.tag_id < 5:
                continue
            t_cam_obj = numpy.eye(4)
            t_cam_obj[:3, :3] = tag.pose_R
            t_cam_obj[:3, 3] = tag.pose_t.flatten()
            t_robot_obj = numpy.linalg.inv(t_cam_robot) @ t_cam_obj
            poses[tag.tag_id] = t_robot_obj

        return poses


# ──────────────────────────────────────────────
# Motion Primitives
# ──────────────────────────────────────────────
def pick_container(arm, container_pose):
    """Pick up a container at the given 4x4 pose (meters, robot frame)."""
    grasp_cube(arm, container_pose)


def place_container(arm, container_pose):
    """Place a container back at its original 4x4 pose (meters, robot frame)."""
    x = container_pose[0, 3] * 1000
    y = container_pose[1, 3] * 1000
    z = container_pose[2, 3] * 1000

    x_axis = container_pose[:3, 0]
    yaw = numpy.degrees(numpy.arctan2(x_axis[1], x_axis[0]))
    roll, pitch = 180, 0

    arm.set_position(x, y, z + PRE_GRASP_HEIGHT, roll, pitch, yaw, wait=True)
    arm.set_position(x, y, z + 2, roll, pitch, yaw, wait=True)

    arm.open_lite6_gripper()
    time.sleep(1.5)
    arm.stop_lite6_gripper()

    arm.set_position(x, y, z + PRE_GRASP_HEIGHT, roll, pitch, yaw, wait=True)


def move_above_cup(arm):
    """Move the held container above the main cup at pouring height."""
    x, y, z = _get_cup_xyz_mm()
    arm.set_position(x, y, z + PRE_GRASP_HEIGHT + POUR_HEIGHT, 180, 0, 0, wait=True)


def pour(arm):
    """Tilt the held container to pour its contents into the main cup, then return upright."""
    x, y, z = _get_cup_xyz_mm()
    pour_z = z + POUR_HEIGHT

    # Tilt to pour
    arm.set_position(x, y, pour_z, 180, POUR_TILT_ANGLE, 0, wait=True)
    time.sleep(2.0)

    # Return to upright
    arm.set_position(x, y, pour_z, 180, 0, 0, wait=True)
    time.sleep(0.5)

    # Lift back up
    arm.set_position(x, y, pour_z + PRE_GRASP_HEIGHT, 180, 0, 0, wait=True)


def stir(arm):
    """With stirrer held, perform a circular stirring motion inside the main cup."""
    x, y, z = _get_cup_xyz_mm()

    top_z = z + POUR_HEIGHT
    bottom_z = z + STIR_DEPTH

    # Move above cup
    arm.set_position(x, y, top_z, 180, 0, 0, wait=True)

    # Descend into cup
    arm.set_position(x, y, bottom_z, 180, 0, 0, wait=True)

    # Stir: small circular motions
    for _ in range(STIR_CYCLES):
        arm.set_position(x + 10, y, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x, y + 10, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x - 10, y, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x, y - 10, bottom_z, 180, 0, 0, wait=True)

    # Return to center and lift out
    arm.set_position(x, y, bottom_z, 180, 0, 0, wait=True)
    arm.set_position(x, y, top_z + PRE_GRASP_HEIGHT, 180, 0, 0, wait=True)


# ──────────────────────────────────────────────
# High-Level Task Sequences
# ──────────────────────────────────────────────
def execute_add_ingredient(arm, ingredient_name, poses):
    """
    Full sequence: pick ingredient container -> move to main cup -> pour -> return container.
    """
    tag_id = INGREDIENT_TAG_MAP[ingredient_name]
    if tag_id not in poses:
        print(f'[ERROR] AprilTag {tag_id} for "{ingredient_name}" not detected.')
        return False

    container_pose = poses[tag_id]

    print(f'  Picking up {ingredient_name} container (tag {tag_id})...')
    pick_container(arm, container_pose)

    print(f'  Moving above main cup...')
    move_above_cup(arm)

    print(f'  Pouring {ingredient_name}...')
    pour(arm)

    print(f'  Returning {ingredient_name} container...')
    place_container(arm, container_pose)

    return True


def execute_stir(arm, poses):
    """
    Full sequence: pick stirrer -> stir in main cup -> return stirrer.
    """
    if STIRRER_TAG_ID not in poses:
        print(f'[ERROR] Stirrer (tag {STIRRER_TAG_ID}) not detected.')
        return False

    stirrer_pose = poses[STIRRER_TAG_ID]

    print(f'  Picking up stirrer (tag {STIRRER_TAG_ID})...')
    pick_container(arm, stirrer_pose)

    print(f'  Stirring...')
    stir(arm)

    print(f'  Returning stirrer...')
    place_container(arm, stirrer_pose)

    return True
