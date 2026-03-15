# cv5551-s26-team-dcml
This is for the Real Robot Challenge and Final Project for CSCI 5551 (Spring 2026).

Project Title: Pick-and-Place Task with Variable Target Positions and Obstacles


Team Members:

Amreen Hossain (hossa168@umn.edu)

Priya Kingsley (kings337@umn.edu)

Riley Zong (zong0043@umn.edu)

Raian Haider Chowdhury (chowd207@umn.edu) - Coordinator


# Lite6 Cube Stacker — ROS2 + MoveIt2 + ZED Camera

Autonomous cube stacking system using the **UFACTORY Lite6** robotic arm, a **ZED2 stereo camera**, and **ArUco markers** on cubes. The robot detects cube poses from the camera and stacks them as high as possible.

> **Assumes:** Ubuntu 22.04 + ROS2 Humble already installed.  
> **Needs:** NVIDIA GPU + CUDA for the ZED camera node.

---


## System Overview

```
ZED2 Camera
    │
    ├─ /zed/zed_node/rgb/color/rect/image
    ├─ /zed/zed_node/depth/depth_registered
    └─ /zed/zed_node/rgb/color/rect/camera_info
            │
            ▼
    [ aruco_detector ]
      Detects ArUco markers → publishes /detected_cubes (PoseArray)
      Broadcasts TF: zed_left_camera_optical → cube_<id>
            │
            ▼
    [ camera_robot_calibration ]
      Static TF: world → zed_left_camera_optical
            │
            ▼
    [ cube_stacker ]
      Transforms cube poses → world frame
      Plans pick & place via MoveIt2
      Controls gripper via xarm_msgs
            │
            ▼
    [ MoveIt2 move_group → ros2_control → Lite6 ]
```

---


## Step 1 — Install NVIDIA Driver and CUDA

### NVIDIA Driver

```bash
# Check your GPU
lspci | grep -i nvidia

# Install recommended driver
sudo add-apt-repository ppa:graphics-drivers/ppa -y
sudo apt update
sudo ubuntu-drivers autoinstall
sudo reboot
```

After reboot, verify:

```bash
nvidia-smi
# Should show GPU name and Driver Version: 535+
```

### CUDA Toolkit

```bash
# Add CUDA repo
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2204/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install cuda-toolkit-12-3 -y

# Add to PATH
echo 'export PATH=/usr/local/cuda/bin:$PATH' >> ~/.bashrc
echo 'export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH' >> ~/.bashrc
source ~/.bashrc

# Verify
nvcc --version
```

---

## Step 2 — Install ZED SDK

Download the **ZED SDK 4.x for Ubuntu 22 + CUDA 12** from:  
👉 https://www.stereolabs.com/developers/release

Then install:

```bash
cd ~/Downloads
chmod +x ZED_SDK_Ubuntu22_cuda*.run
./ZED_SDK_Ubuntu22_cuda*.run
# Accept license: y
# Install Python API: y
# Install samples: n  (optional)
# Optimize neural models now: n  (takes too long, skip)
```

Verify the SDK installed correctly:

```bash
/usr/local/zed/tools/ZED_Explorer
# Should open a GUI showing a live camera feed when ZED is plugged in
```

Install the ZED Python API:

```bash
cd /usr/local/zed
sudo python3 get_python_api.py
```

---

## Step 3 — Install ROS2 Dependencies

### MoveIt2

```bash
sudo apt install -y \
  ros-humble-moveit \
  ros-humble-moveit-py \
  ros-humble-moveit-ros-planning-interface \
  ros-humble-moveit-visual-tools \
  ros-humble-ros2-control \
  ros-humble-ros2-controllers \
  ros-humble-gripper-controllers \
  ros-humble-joint-trajectory-controller \
  ros-humble-controller-manager
```

### Python Libraries

```bash
sudo apt install -y \
  python3-pip \
  python3-scipy \
  python3-numpy \
  python3-opencv

pip3 install opencv-contrib-python scipy numpy
```

### Misc ROS tools

```bash
sudo apt install -y \
  ros-humble-cv-bridge \
  ros-humble-image-transport \
  ros-humble-image-transport-plugins \
  ros-humble-tf2-tools \
  ros-humble-tf2-geometry-msgs \
  ros-humble-rqt-image-view \
  ros-humble-ament-cmake-python \
  python3-colcon-common-extensions \
  python3-rosdep
```

---

## Step 4 — Clone the Repo and Set Up Workspace

```bash
# Clone the repo as your ROS2 workspace
git clone hhttps://github.com/RaianSilex/cv5551-s26-team-dcml.git ~/ros2_ws
cd ~/ros2_ws
```

> ⚠️ The repo is structured as a full ROS2 workspace. Your packages live inside `src/`.

---

## Step 5 — Clone Third-Party ROS2 Packages

These are not in the repo and must be cloned separately into `src/`.

```bash
cd ~/ros2_ws/src

# ZED ROS2 wrapper (match your ZED SDK major version — check available branches)
git clone --recursive https://github.com/stereolabs/zed-ros2-wrapper.git
cd zed-ros2-wrapper
git checkout humble-v4.1.x    # adjust if your SDK is a different minor version
cd ..

# xarm_ros2 — Lite6 driver + MoveIt config
git clone https://github.com/xArm-Developer/xarm_ros2.git --recursive -b humble
```

Your `src/` folder should now look like:

```
src/
├── lite6_cube_stacker/       ← from this repo
├── zed-ros2-wrapper/         ← cloned above
└── xarm_ros2/                ← cloned above
```

---

## Step 6 — Install All ROS Dependencies

```bash
cd ~/ros2_ws

# Initialise rosdep if not done yet
sudo rosdep init 2>/dev/null || true
rosdep update

# Install all dependencies declared in package.xml files
# zed_interfaces cannot be resolved via rosdep (installed via ZED SDK) — the -r flag skips it
rosdep install --from-paths src --ignore-src -r -y
```

---

## Step 7 — Build the Workspace

Build in dependency order: xarm first, then ZED, then the stacker.

```bash
cd ~/ros2_ws

# 1. Build xarm packages (lite6_cube_stacker depends on xarm_msgs)
colcon build --symlink-install \
  --packages-select \
    xarm_msgs xarm_sdk xarm_api \
    xarm_description xarm_moveit_config \
    lite6_moveit_config xarm_gazebo \
  --cmake-args -DCMAKE_BUILD_TYPE=Release

source install/setup.bash

# 2. Build ZED wrapper
colcon build --symlink-install \
  --packages-select zed_components zed_wrapper zed_ros2 \
  --cmake-args -DCMAKE_BUILD_TYPE=Release

source install/setup.bash

# 3. Build the stacker package
colcon build --symlink-install \
  --packages-select lite6_cube_stacker \
  --cmake-args -DCMAKE_BUILD_TYPE=Release

source install/setup.bash
```

### Add to .bashrc so every terminal is sourced automatically

```bash
echo "source ~/ros2_ws/install/setup.bash" >> ~/.bashrc
source ~/.bashrc
```

### Verify the build

```bash
ros2 pkg list | grep lite6
# Expected output:
#   lite6_cube_stacker
#   lite6_moveit_config

ros2 pkg executables lite6_cube_stacker
# Expected output:
#   lite6_cube_stacker aruco_detector
#   lite6_cube_stacker camera_robot_calibration
#   lite6_cube_stacker cube_stacker
```

---

## Step 8 — Hardware Setup

### Physical layout

```
  ┌─────────────────────────────────────────────┐
  │                    TABLE                     │
  │                                              │
  │  [ZED Camera on stand]       [Cube pile]     │
  │  (facing the robot)                          │
  │                                              │
  │           [STACK ZONE]     [Lite6 Base]      │
  └─────────────────────────────────────────────┘
```

- Robot base = **world frame origin**
- Camera stand is on the opposite side of the table from the robot
- Use a USB **3.0** (blue) port for the ZED — USB 2.0 will cause frame drops


### Connect the Lite6 arm

```bash
# Connect arm controller to PC via ethernet
# Default robot IP: 192.168.1.185
# Set your PC ethernet adapter to static IP: 192.168.1.100

# Test connection
ping 192.168.1.185
```

### Test ZED camera alone

```bash
ros2 launch zed_wrapper zed_camera.launch.py camera_model:=zed2

# In another terminal — confirm topics are live
ros2 topic list | grep zed
ros2 topic hz /zed/zed_node/rgb/color/rect/image
# Should show ~30 Hz
```

### Test Lite6 arm alone

```bash
ros2 launch xarm_api lite6_driver.launch.py robot_ip:=192.168.1.185

# In another terminal — check joint states
ros2 topic echo /xarm/joint_states

# Test gripper open/close
ros2 service call /xarm/gripper_move xarm_msgs/srv/SetInt16 "data: 850"
ros2 service call /xarm/gripper_move xarm_msgs/srv/SetInt16 "data: 200"
```

---

## Step 9 — Camera Calibration

The camera pose relative to the robot base must be measured and entered into the launch file **before running the system**. This is the most important step — wrong values will cause the arm to miss every cube.

### Measure with a tape measure

From the **robot base** (world origin), measure:

```
tx = forward distance to camera optical centre  (metres)
ty = lateral distance to camera                 (metres, left = positive)
tz = height of camera above table               (metres)
rx = camera tilt downward toward table          (radians, e.g. 30° = 0.5236)
rz = 3.1416  (camera faces toward robot = 180° yaw)
```

### Enter the values in the launch file

Open `src/lite6_cube_stacker/launch/cube_stacker.launch.py` and update:

```python
parameters=[{
    'mode': 'static',
    'tx': 0.55,     # ← From measurement
    'ty': -0.35,    # ← From measurement
    'tz': 0.62,     # ← From measurement
    'rx': 0.5236,   # ← From tilt angle
    'ry': 0.0,
    'rz': 3.1416,
}]
```

Then rebuild:

```bash
cd ~/ros2_ws
colcon build --symlink-install --packages-select lite6_cube_stacker
```

> **Tip:** With `--symlink-install`, edits to `.py` files (not CMakeLists) take effect immediately without rebuilding.

---

## Step 10 — Run the System

### Real robot

```bash
ros2 launch lite6_cube_stacker cube_stacker.launch.py \
  robot_ip:=192.168.1.185
```

### Simulation only

```bash
ros2 launch lite6_cube_stacker cube_stacker.launch.py \
  use_sim:=true
```

### Verify each subsystem in separate terminals

```bash
# 1. Check ArUco detection is working
ros2 run rqt_image_view rqt_image_view /aruco_debug

# 2. Check cube poses are being published
ros2 topic echo /detected_cubes

# 3. Check the TF tree is complete
ros2 run tf2_tools view_frames && evince frames.pdf
# Must show:
#   world → base_link → ... → link_eef
#         → zed_left_camera_optical → cube_0, cube_1, ...

# 4. Watch MoveIt2 status
ros2 topic echo /move_group/status
```

---

## Package Structure

```
ros2_ws/
├── src/
│   ├── lite6_cube_stacker/           ← this repo's package
│   │   ├── CMakeLists.txt
│   │   ├── package.xml
│   │   ├── launch/
│   │   │   └── cube_stacker.launch.py
│   │   ├── config/
│   │   └── lite6_cube_stacker/
│   │       ├── __init__.py
│   │       ├── aruco_detector.py           ← ZED → ArUco → PoseArray + TF
│   │       ├── cube_stacker.py             ← MoveIt2 pick & place logic
│   │       └── camera_robot_calibration.py ← world → camera static TF
│   │
│   ├── zed-ros2-wrapper/             ← clone separately (Step 5)
│   └── xarm_ros2/                    ← clone separately (Step 5)
│
├── build/    ← generated by colcon, not in git
├── install/  ← generated by colcon, not in git
└── log/      ← generated by colcon, not in git
```

---

## Key Parameters to Tune

| Parameter | File | Description |
|-----------|------|-------------|
| `tx`, `ty`, `tz`, `rx` | `cube_stacker.launch.py` | Camera position relative to robot base |
| `marker_size` | `cube_stacker.launch.py` | Physical ArUco marker size in metres |
| `CUBE_HEIGHT` | `cube_stacker.py` | Physical cube height in metres |
| `STACK_BASE_X/Y` | `cube_stacker.py` | Where to build the stack in world frame |
| `GRIPPER_CLOSE_POS` | `cube_stacker.py` | Gripper encoder value for closed position |
| `SAFE_Z` | `cube_stacker.py` | Travel height above table between moves |