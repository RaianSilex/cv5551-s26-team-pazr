#!/usr/bin/env python3


import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

import numpy as np
import time

from geometry_msgs.msg import PoseArray, Pose, PoseStamped
from std_msgs.msg import Bool

import tf2_ros
import tf2_geometry_msgs          # registers Pose/PoseStamped transforms

# MoveIt2 Python bindings (moveit_py)
from moveit.planning import MoveItPy
from moveit.core.robot_state import RobotState

# xArm gripper service
from xarm_msgs.srv import SetInt16
from xarm_msgs.msg import RobotMsg

# ── Constants ─────────────────────────────────────────────────────────────────
PLANNING_FRAME   = 'world'
ARM_GROUP        = 'lite6'
GRIPPER_OPEN_POS = 850       # encoder counts  (0 = fully closed, 850 = open)
GRIPPER_CLOSE_POS = 200      # adjust for cube size
GRIPPER_SPEED    = 2000

APPROACH_OFFSET  = 0.08      # m above cube before descending
GRASP_OFFSET     = 0.005     # m – how deep into the cube top to grasp
STACK_BASE_X     = 0.30      # m in world frame – where to build the stack
STACK_BASE_Y     = 0.00
STACK_BASE_Z     = 0.01      # table surface Z in world frame
CUBE_HEIGHT      = 0.05      # metres
SAFE_Z           = 0.25      # m – safe travel height above table
# ─────────────────────────────────────────────────────────────────────────────


class CubeStacker(Node):

    def __init__(self):
        super().__init__('cube_stacker')

        # MoveIt2
        self.moveit  = MoveItPy(node_name='cube_stacker_moveit')
        self.arm     = self.moveit.get_planning_component(ARM_GROUP)
        self.get_logger().info('MoveIt2 component loaded.')

        # TF
        self.tf_buffer   = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        # Gripper service (xarm_ros2)
        self.gripper_cli = self.create_client(
            SetInt16, '/xarm/gripper_move')
        self.get_logger().info('Waiting for gripper service...')
        self.gripper_cli.wait_for_service()
        self.get_logger().info('Gripper service ready.')

        # Cube poses subscription
        self.detected_cubes: list[Pose] = []
        self.sub_cubes = self.create_subscription(
            PoseArray, '/detected_cubes',
            self._cb_cubes, 10)

        # Track how many cubes are already stacked
        self.stack_count = 0

        # Run stacking loop at 2 Hz
        self.timer = self.create_timer(0.5, self._stacking_loop)
        self._busy = False

        self.get_logger().info('CubeStacker ready.')

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _cb_cubes(self, msg: PoseArray):
        """Store latest detected cube poses (camera frame)."""
        self.detected_cubes = msg.poses

    # ── main loop ─────────────────────────────────────────────────────────────

    def _stacking_loop(self):
        if self._busy or not self.detected_cubes:
            return
        self._busy = True

        try:
            # Convert all poses to world frame
            world_poses = []
            for pose in self.detected_cubes:
                ps = PoseStamped()
                ps.header.frame_id = 'zed_left_camera_optical_frame'
                ps.header.stamp    = self.get_clock().now().to_msg()
                ps.pose            = pose
                try:
                    world_ps = self.tf_buffer.transform(
                        ps, PLANNING_FRAME, timeout=rclpy.duration.Duration(seconds=1))
                    world_poses.append(world_ps.pose)
                except Exception as e:
                    self.get_logger().warn(f'TF transform failed: {e}')

            if not world_poses:
                return

            # Filter: skip cubes already near the stack location
            remaining = [p for p in world_poses
                         if not self._is_at_stack(p)]
            if not remaining:
                self.get_logger().info('All visible cubes are already stacked.')
                return

            # Sort by distance to arm base (nearest = easier to reach)
            remaining.sort(key=lambda p: p.position.x**2 + p.position.y**2)

            # Pick the nearest cube
            target = remaining[0]
            self.get_logger().info(
                f'Picking cube at ({target.position.x:.3f},'
                f'{target.position.y:.3f},{target.position.z:.3f})')

            # Execute pick-and-place
            success = self._pick_and_place(target)
            if success:
                self.stack_count += 1
                self.get_logger().info(
                    f'Stack height: {self.stack_count} cubes.')

        finally:
            self._busy = False

    # ── pick & place ──────────────────────────────────────────────────────────

    def _pick_and_place(self, cube_pose: Pose) -> bool:
        """
        Full pick-and-place sequence:
          pre-grasp → grasp → lift → move to stack → place → retreat
        """
        # ── 1. Open gripper ──────────────────────────────────────────────────
        self._set_gripper(GRIPPER_OPEN_POS)

        # ── 2. Pre-grasp: above the cube ─────────────────────────────────────
        pre_grasp = self._make_pose(
            cube_pose.position.x,
            cube_pose.position.y,
            cube_pose.position.z + APPROACH_OFFSET,
            downward_orientation=True)
        if not self._move_to_pose(pre_grasp, 'pre-grasp'):
            return False

        # ── 3. Descend to grasp ───────────────────────────────────────────────
        grasp_pose = self._make_pose(
            cube_pose.position.x,
            cube_pose.position.y,
            cube_pose.position.z + GRASP_OFFSET,
            downward_orientation=True)
        if not self._move_to_pose(grasp_pose, 'grasp', velocity_scale=0.2):
            return False

        # ── 4. Close gripper ─────────────────────────────────────────────────
        self._set_gripper(GRIPPER_CLOSE_POS)
        time.sleep(0.5)

        # ── 5. Lift ───────────────────────────────────────────────────────────
        lift_pose = self._make_pose(
            cube_pose.position.x,
            cube_pose.position.y,
            SAFE_Z,
            downward_orientation=True)
        if not self._move_to_pose(lift_pose, 'lift'):
            self._set_gripper(GRIPPER_OPEN_POS)
            return False

        # ── 6. Move to above stack ────────────────────────────────────────────
        stack_z   = STACK_BASE_Z + self.stack_count * CUBE_HEIGHT
        above_stack = self._make_pose(
            STACK_BASE_X, STACK_BASE_Y, SAFE_Z,
            downward_orientation=True)
        if not self._move_to_pose(above_stack, 'above-stack'):
            self._emergency_drop()
            return False

        # ── 7. Descend to place ───────────────────────────────────────────────
        place_pose = self._make_pose(
            STACK_BASE_X, STACK_BASE_Y,
            stack_z + CUBE_HEIGHT + GRASP_OFFSET,
            downward_orientation=True)
        if not self._move_to_pose(place_pose, 'place', velocity_scale=0.2):
            self._emergency_drop()
            return False

        # ── 8. Release ────────────────────────────────────────────────────────
        self._set_gripper(GRIPPER_OPEN_POS)
        time.sleep(0.3)

        # ── 9. Retreat ────────────────────────────────────────────────────────
        retreat = self._make_pose(
            STACK_BASE_X, STACK_BASE_Y, SAFE_Z,
            downward_orientation=True)
        self._move_to_pose(retreat, 'retreat')

        return True

    # ── MoveIt helpers ────────────────────────────────────────────────────────

    def _move_to_pose(self, pose: PoseStamped,
                      label: str,
                      velocity_scale: float = 0.5,
                      accel_scale: float = 0.4) -> bool:
        self.arm.set_start_state_to_current_state()
        self.arm.set_goal_state(pose_stamped_msg=pose, pose_link='link_eef')

        plan = self.arm.plan()
        if not plan:
            self.get_logger().error(f'Planning FAILED for: {label}')
            return False

        robot_traj = plan.trajectory
        ok = self.moveit.execute(robot_traj, controllers=[])
        if not ok:
            self.get_logger().error(f'Execution FAILED for: {label}')
            return False

        self.get_logger().info(f'Motion OK: {label}')
        return True

    def _make_pose(self, x: float, y: float, z: float,
                   downward_orientation: bool = True) -> PoseStamped:
        ps = PoseStamped()
        ps.header.frame_id = PLANNING_FRAME
        ps.header.stamp    = self.get_clock().now().to_msg()
        ps.pose.position.x = x
        ps.pose.position.y = y
        ps.pose.position.z = z
        if downward_orientation:
            # Gripper pointing straight down  (end-effector Z = world -Z)
            # Quaternion for 180° around X: (1,0,0,0) rotated
            ps.pose.orientation.x = 1.0
            ps.pose.orientation.y = 0.0
            ps.pose.orientation.z = 0.0
            ps.pose.orientation.w = 0.0
        else:
            ps.pose.orientation.w = 1.0
        return ps

    # ── Gripper helpers ───────────────────────────────────────────────────────

    def _set_gripper(self, position: int):
        req          = SetInt16.Request()
        req.data     = position
        future       = self.gripper_cli.call_async(req)
        rclpy.spin_until_future_complete(self, future, timeout_sec=3.0)
        if future.result() is None:
            self.get_logger().warn('Gripper service call timed out.')

    def _emergency_drop(self):
        """Open gripper and retreat to safe height – used on planning failure."""
        self.get_logger().warn('Emergency drop!')
        self._set_gripper(GRIPPER_OPEN_POS)
        safe = self._make_pose(0.25, 0.0, SAFE_Z, downward_orientation=False)
        self._move_to_pose(safe, 'emergency-retreat')

    # ── misc ──────────────────────────────────────────────────────────────────

    def _is_at_stack(self, pose: Pose, tol: float = 0.05) -> bool:
        dx = abs(pose.position.x - STACK_BASE_X)
        dy = abs(pose.position.y - STACK_BASE_Y)
        return dx < tol and dy < tol


def main(args=None):
    rclpy.init(args=args)
    node = CubeStacker()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
