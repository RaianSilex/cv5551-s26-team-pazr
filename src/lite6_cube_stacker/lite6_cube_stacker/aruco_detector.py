#!/usr/bin/env python3


import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy

import cv2
import numpy as np
from cv_bridge import CvBridge

from sensor_msgs.msg import Image, CameraInfo
from geometry_msgs.msg import PoseArray, Pose
from std_msgs.msg import Header

import tf2_ros
from geometry_msgs.msg import TransformStamped
from scipy.spatial.transform import Rotation as R

# ── ArUco dictionary ──────────────────────────────────────────────────────────
ARUCO_DICT   = cv2.aruco.DICT_4X4_50   # 4×4 markers, IDs 0-49
MARKER_SIZE  = 0.04                     # metres – measure your printed marker
CUBE_SIZE    = 0.05                     # metres – side length of one cube
# ─────────────────────────────────────────────────────────────────────────────

class ArucoDetector(Node):

    def __init__(self):
        super().__init__('aruco_detector')

        # Parameters
        self.declare_parameter('marker_size',  MARKER_SIZE)
        self.declare_parameter('cube_size',    CUBE_SIZE)
        self.declare_parameter('aruco_dict',   ARUCO_DICT)
        self.declare_parameter('camera_frame', 'zed_left_camera_optical_frame')

        self.marker_size  = self.get_parameter('marker_size').value
        self.cube_size    = self.get_parameter('cube_size').value
        self.camera_frame = self.get_parameter('camera_frame').value

        # ArUco setup (OpenCV ≥ 4.7 API)
        aruco_dict_id     = self.get_parameter('aruco_dict').value
        self.aruco_dict   = cv2.aruco.getPredefinedDictionary(aruco_dict_id)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.aruco_detector = cv2.aruco.ArucoDetector(
            self.aruco_dict, self.aruco_params)

        # Camera intrinsics (filled when CameraInfo arrives)
        self.camera_matrix = None
        self.dist_coeffs   = None
        self.bridge        = CvBridge()

        # TF broadcaster
        self.tf_broadcaster = tf2_ros.TransformBroadcaster(self)

        # QoS
        sensor_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            depth=1)

        # Subscriptions
        self.sub_info  = self.create_subscription(
            CameraInfo, '/zed/zed_node/rgb/camera_info',
            self._cb_camera_info, 1)
        self.sub_rgb   = self.create_subscription(
            Image, '/zed/zed_node/rgb/image_rect_color',
            self._cb_rgb, sensor_qos)
        self.sub_depth = self.create_subscription(
            Image, '/zed/zed_node/depth/depth_registered',
            self._cb_depth, sensor_qos)

        # Publishers
        self.pub_poses = self.create_publisher(PoseArray, '/detected_cubes', 10)
        self.pub_debug = self.create_publisher(Image,     '/aruco_debug',    10)

        self._latest_depth = None
        self.get_logger().info('ArucoDetector ready.')

    # ── callbacks ─────────────────────────────────────────────────────────────

    def _cb_camera_info(self, msg: CameraInfo):
        if self.camera_matrix is None:
            self.camera_matrix = np.array(msg.k).reshape(3, 3)
            self.dist_coeffs   = np.array(msg.d)
            self.get_logger().info('Camera intrinsics received.')

    def _cb_depth(self, msg: Image):
        self._latest_depth = self.bridge.imgmsg_to_cv2(msg, '32FC1')

    def _cb_rgb(self, msg: Image):
        if self.camera_matrix is None or self._latest_depth is None:
            return

        frame = self.bridge.imgmsg_to_cv2(msg, 'bgr8')
        gray  = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        corners, ids, _ = self.aruco_detector.detectMarkers(gray)

        pose_array        = PoseArray()
        pose_array.header = Header(
            stamp=msg.header.stamp, frame_id=self.camera_frame)

        if ids is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners, ids)

            rvecs, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
                corners, self.marker_size,
                self.camera_matrix, self.dist_coeffs)

            for i, marker_id in enumerate(ids.flatten()):
                rvec = rvecs[i][0]
                tvec = tvecs[i][0]

                # Refine Z from depth image at marker centre
                cx = int(np.mean([c[0] for c in corners[i][0]]))
                cy = int(np.mean([c[1] for c in corners[i][0]]))
                h, w = self._latest_depth.shape
                if 0 <= cx < w and 0 <= cy < h:
                    depth_val = float(self._latest_depth[cy, cx])
                    if np.isfinite(depth_val) and depth_val > 0.0:
                        # Override Z with measured depth (more accurate)
                        tvec[2] = depth_val

                pose = self._rvec_tvec_to_pose(rvec, tvec)
                pose_array.poses.append(pose)

                # Broadcast TF
                self._broadcast_tf(
                    msg.header.stamp, marker_id, rvec, tvec)

                # Draw axis on debug image
                cv2.drawFrameAxes(
                    frame, self.camera_matrix, self.dist_coeffs,
                    rvec, tvec, self.marker_size * 0.5)

                # Label
                cv2.putText(
                    frame, f'ID:{marker_id}  Z:{tvec[2]:.3f}m',
                    (cx - 40, cy - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        self.pub_poses.publish(pose_array)
        self.pub_debug.publish(
            self.bridge.cv2_to_imgmsg(frame, 'bgr8'))

    # ── helpers ───────────────────────────────────────────────────────────────

    def _rvec_tvec_to_pose(self, rvec, tvec) -> Pose:
        pose = Pose()
        pose.position.x = float(tvec[0])
        pose.position.y = float(tvec[1])
        pose.position.z = float(tvec[2])
        rot = R.from_rotvec(rvec)
        q   = rot.as_quat()   # x y z w
        pose.orientation.x = float(q[0])
        pose.orientation.y = float(q[1])
        pose.orientation.z = float(q[2])
        pose.orientation.w = float(q[3])
        return pose

    def _broadcast_tf(self, stamp, marker_id, rvec, tvec):
        t = TransformStamped()
        t.header.stamp    = stamp
        t.header.frame_id = self.camera_frame
        t.child_frame_id  = f'cube_{marker_id}'
        t.transform.translation.x = float(tvec[0])
        t.transform.translation.y = float(tvec[1])
        t.transform.translation.z = float(tvec[2])
        rot = R.from_rotvec(rvec)
        q   = rot.as_quat()
        t.transform.rotation.x = float(q[0])
        t.transform.rotation.y = float(q[1])
        t.transform.rotation.z = float(q[2])
        t.transform.rotation.w = float(q[3])
        self.tf_broadcaster.sendTransform(t)


def main(args=None):
    rclpy.init(args=args)
    node = ArucoDetector()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
