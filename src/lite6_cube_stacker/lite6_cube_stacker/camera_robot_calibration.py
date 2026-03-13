#!/usr/bin/env python3


import rclpy
from rclpy.node import Node
from geometry_msgs.msg import TransformStamped
import tf2_ros
import numpy as np
from scipy.spatial.transform import Rotation as R


class CameraRobotCalibration(Node):

    def __init__(self):
        super().__init__('camera_robot_calibration')

        self.declare_parameter('mode', 'static')
        # Static transform parameters (world → camera_optical_frame)
        self.declare_parameter('tx', 0.50)   # metres
        self.declare_parameter('ty', -0.30)
        self.declare_parameter('tz', 0.60)
        self.declare_parameter('rx', 0.0)    # radians (extrinsic XYZ)
        self.declare_parameter('ry', 1.5708)
        self.declare_parameter('rz', 0.0)

        mode = self.get_parameter('mode').value

        self.static_broadcaster = tf2_ros.StaticTransformBroadcaster(self)

        if mode == 'static':
            self._broadcast_static()
        else:
            self.get_logger().warn(
                'Automatic hand-eye not yet implemented; '
                'falling back to static.')
            self._broadcast_static()

    def _broadcast_static(self):
        tx = self.get_parameter('tx').value
        ty = self.get_parameter('ty').value
        tz = self.get_parameter('tz').value
        rx = self.get_parameter('rx').value
        ry = self.get_parameter('ry').value
        rz = self.get_parameter('rz').value

        rot = R.from_euler('XYZ', [rx, ry, rz])
        q   = rot.as_quat()   # x y z w

        t = TransformStamped()
        t.header.stamp            = self.get_clock().now().to_msg()
        t.header.frame_id         = 'world'
        t.child_frame_id          = 'zed_left_camera_optical_frame'
        t.transform.translation.x = tx
        t.transform.translation.y = ty
        t.transform.translation.z = tz
        t.transform.rotation.x    = q[0]
        t.transform.rotation.y    = q[1]
        t.transform.rotation.z    = q[2]
        t.transform.rotation.w    = q[3]

        self.static_broadcaster.sendTransform(t)
        self.get_logger().info(
            f'Static TF broadcast: world → zed_left_camera_optical_frame  '
            f't=[{tx:.3f},{ty:.3f},{tz:.3f}]  '
            f'rpy=[{rx:.3f},{ry:.3f},{rz:.3f}]')


def main(args=None):
    rclpy.init(args=args)
    node = CameraRobotCalibration()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
