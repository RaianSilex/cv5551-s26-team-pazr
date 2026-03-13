cmake_minimum_required(VERSION 3.8)
project(lite6_cube_stacker)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(rclpy REQUIRED)

# Install Python package
ament_python_install_package(${PROJECT_NAME})

# Install Python executables
install(PROGRAMS
  lite6_cube_stacker/aruco_detector.py
  lite6_cube_stacker/cube_stacker.py
  lite6_cube_stacker/camera_robot_calibration.py
  DESTINATION lib/${PROJECT_NAME}
)

# Rename executables (drop .py extension)
install(PROGRAMS
  lite6_cube_stacker/aruco_detector.py
  RENAME aruco_detector
  DESTINATION lib/${PROJECT_NAME}
)
install(PROGRAMS
  lite6_cube_stacker/cube_stacker.py
  RENAME cube_stacker
  DESTINATION lib/${PROJECT_NAME}
)
install(PROGRAMS
  lite6_cube_stacker/camera_robot_calibration.py
  RENAME camera_robot_calibration
  DESTINATION lib/${PROJECT_NAME}
)

# Install launch and config
install(DIRECTORY
  launch/
  DESTINATION share/${PROJECT_NAME}/launch
)
install(DIRECTORY
  config/
  DESTINATION share/${PROJECT_NAME}/config
)


if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  ament_lint_auto_find_test_dependencies()
endif()

ament_package()