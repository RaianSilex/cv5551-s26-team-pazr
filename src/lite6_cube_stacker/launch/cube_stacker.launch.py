"""
cube_stacker.launch.py
-----------------------
Launches everything needed for Project 1:
  1. ZED camera driver
  2. xArm / Lite6 hardware driver (real robot)   ← set USE_SIM to use Gazebo
  3. MoveIt2 move_group + RViz
  4. Camera-to-robot calibration (static TF)
  5. ArUco detector
  6. Cube stacker logic

Environment variables:
  ROBOT_IP   – IP address of the Lite6 controller  (default 192.168.1.185)
  USE_SIM    – set to 'true' to launch Gazebo instead of real hardware
"""

import os
from launch import LaunchDescription
from launch.actions import (IncludeLaunchDescription, DeclareLaunchArgument,
                             GroupAction, TimerAction)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare
from ament_index_python.packages import get_package_share_directory


def generate_launch_description():

    robot_ip_arg = DeclareLaunchArgument(
        'robot_ip', default_value='192.168.1.185',
        description='IP of the Lite6 controller')
    use_sim_arg  = DeclareLaunchArgument(
        'use_sim', default_value='false',
        description='Use Gazebo simulation instead of real hardware')
    rviz_arg     = DeclareLaunchArgument(
        'rviz', default_value='true',
        description='Launch RViz')

    robot_ip = LaunchConfiguration('robot_ip')
    use_sim  = LaunchConfiguration('use_sim')
    rviz     = LaunchConfiguration('rviz')

    # ── 1. ZED Camera ─────────────────────────────────────────────────────────
    zed_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('zed_wrapper'), 'launch', 'zed_camera.launch.py'])),
        launch_arguments={
            'camera_model': 'zed2',
            'publish_tf':   'true',
        }.items()
    )

    # ── 2a. Real Lite6 hardware ───────────────────────────────────────────────
    lite6_hw_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('xarm_api'), 'launch',
                'lite6_driver.launch.py'])),
        launch_arguments={'robot_ip': robot_ip}.items(),
        condition=UnlessCondition(use_sim)
    )

    # ── 2b. Gazebo simulation ─────────────────────────────────────────────────
    lite6_sim_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('xarm_gazebo'), 'launch',
                'lite6_beside_table_gazebo.launch.py'])),
        condition=IfCondition(use_sim)
    )

    # ── 3. MoveIt2 move_group ─────────────────────────────────────────────────
    moveit_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('lite6_moveit_config'), 'launch',
                'move_group.launch.py'])),
        launch_arguments={
            'robot_ip':   robot_ip,
            'use_sim':    use_sim,
            'load_gripper': 'true',
        }.items()
    )

    # ── 3b. RViz ──────────────────────────────────────────────────────────────
    rviz_node = Node(
        package='rviz2', executable='rviz2',
        name='rviz2',
        arguments=['-d', PathJoinSubstitution([
            FindPackageShare('lite6_cube_stacker'),
            'config', 'cube_stacker.rviz'])],
        condition=IfCondition(rviz)
    )

    # ── 4. Camera calibration (static TF) ────────────────────────────────────
    calibration_node = Node(
        package='lite6_cube_stacker',
        executable='camera_robot_calibration',
        name='camera_robot_calibration',
        parameters=[{
            'mode': 'static',
            # !! MEASURE THESE ON YOUR ACTUAL SETUP !!
            # tx/ty/tz: ZED camera optical frame origin in world (robot base) frame
            'tx': 0.55,    # 55 cm in front of robot base
            'ty': -0.35,   # 35 cm to the left
            'tz': 0.62,    # 62 cm above table
            # Camera tilted ~30° downward toward table
            'rx': 0.5236,  # 30 degrees in radians
            'ry': 0.0,
            'rz': 3.1416,  # 180° – camera faces toward robot
        }]
    )

    # ── 5. ArUco detector ────────────────────────────────────────────────────
    aruco_node = Node(
        package='lite6_cube_stacker',
        executable='aruco_detector',
        name='aruco_detector',
        parameters=[{
            'marker_size':   0.04,
            'cube_size':     0.05,
            'camera_frame':  'zed_left_camera_optical_frame',
        }],
        remappings=[
            ('/zed/zed_node/rgb/image_rect_color',   '/zed/zed_node/rgb/image_rect_color'),
            ('/zed/zed_node/depth/depth_registered',  '/zed/zed_node/depth/depth_registered'),
            ('/zed/zed_node/rgb/camera_info',          '/zed/zed_node/rgb/camera_info'),
        ]
    )

    # ── 6. Cube stacker (delayed to let MoveIt2 fully init) ───────────────────
    stacker_node = TimerAction(
        period=8.0,
        actions=[Node(
            package='lite6_cube_stacker',
            executable='cube_stacker',
            name='cube_stacker',
            parameters=[{
                'stack_base_x': 0.30,
                'stack_base_y': 0.00,
                'stack_base_z': 0.01,
                'cube_height':  0.05,
                'safe_z':       0.25,
            }],
            output='screen',
        )]
    )

    return LaunchDescription([
        robot_ip_arg,
        use_sim_arg,
        rviz_arg,
        zed_launch,
        lite6_hw_launch,
        lite6_sim_launch,
        moveit_launch,
        rviz_node,
        calibration_node,
        aruco_node,
        stacker_node,
    ])
