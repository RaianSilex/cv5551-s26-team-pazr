"""
FP1 – Beverage-Making Robot (Coffee)

Uses OpenAI Vision API to read container labels, generate a structured task
plan, then executes the plan on a Lite6 arm using AprilTag-based grasping.

April Tag Assignments (tag36h11 family):
    Tags 0-3  : Table calibration tags (used by checkpoint0)
    Tag  5    : Coffee powder container
    Tag  6    : Milk powder container
    Tag  7    : Sugar container
    Tag  8    : Stirring stick
    Tag  9    : Main cup (water)
"""

import cv2, numpy, time, json, base64
from openai import OpenAI
from pupil_apriltags import Detector
from xarm.wrapper import XArmAPI

from utils.zed_camera import ZedCamera
from checkpoint0 import get_transform_camera_robot
from checkpoint1 import grasp_cube, GRIPPER_LENGTH, CUBE_TAG_FAMILY, CUBE_TAG_SIZE

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────
ROBOT_IP = '192.168.1.182'

# Map ingredient names → april tag IDs
INGREDIENT_TAG_MAP = {
    'coffee':  5,
    'milk':    6,
    'sugar':   7,
}
STIRRER_TAG_ID = 8
MAIN_CUP_TAG_ID = 9

# Motion parameters (mm)
PRE_GRASP_HEIGHT = 120   # safe height above object
POUR_HEIGHT = 80         # height above main cup when pouring
STIR_DEPTH = 30          # how far stirrer descends into cup
STIR_CYCLES = 3          # number of up-down stir motions
POUR_TILT_ANGLE = 60     # degrees to tilt when pouring


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
        Detect all AprilTags (ID >= 5) and return a dict mapping tag_id → 4x4 pose
        in the robot base frame (meters).
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
# Robot Primitive Actions
# ──────────────────────────────────────────────
def pick_container(arm, container_pose):
    """Pick up a container at the given 4x4 pose (meters, robot frame). Same as grasp_cube."""
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


def move_above_cup(arm, cup_pose):
    """Move the held container above the main cup at pouring height."""
    x = cup_pose[0, 3] * 1000
    y = cup_pose[1, 3] * 1000
    z = cup_pose[2, 3] * 1000

    arm.set_position(x, y, z + PRE_GRASP_HEIGHT + POUR_HEIGHT, 180, 0, 0, wait=True)


def pour(arm, cup_pose):
    """Tilt the held container to pour its contents into the main cup, then return upright."""
    x = cup_pose[0, 3] * 1000
    y = cup_pose[1, 3] * 1000
    z = cup_pose[2, 3] * 1000
    pour_z = z + POUR_HEIGHT

    # Tilt to pour
    arm.set_position(x, y, pour_z, 180, POUR_TILT_ANGLE, 0, wait=True)
    time.sleep(2.0)  # let contents pour out

    # Return to upright
    arm.set_position(x, y, pour_z, 180, 0, 0, wait=True)
    time.sleep(0.5)

    # Lift back up
    arm.set_position(x, y, pour_z + PRE_GRASP_HEIGHT, 180, 0, 0, wait=True)


def stir(arm, cup_pose):
    """With stirrer held, perform an up-down stirring motion inside the main cup."""
    x = cup_pose[0, 3] * 1000
    y = cup_pose[1, 3] * 1000
    z = cup_pose[2, 3] * 1000

    top_z = z + POUR_HEIGHT
    bottom_z = z + STIR_DEPTH

    # Move above cup
    arm.set_position(x, y, top_z, 180, 0, 0, wait=True)

    # Descend into cup
    arm.set_position(x, y, bottom_z, 180, 0, 0, wait=True)

    # Stir: small circular / up-down motions
    for _ in range(STIR_CYCLES):
        arm.set_position(x + 10, y, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x, y + 10, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x - 10, y, bottom_z, 180, 0, 0, wait=True)
        arm.set_position(x, y - 10, bottom_z, 180, 0, 0, wait=True)

    # Return to center and lift out
    arm.set_position(x, y, bottom_z, 180, 0, 0, wait=True)
    arm.set_position(x, y, top_z + PRE_GRASP_HEIGHT, 180, 0, 0, wait=True)


# ──────────────────────────────────────────────
# High-Level Task Functions
# ──────────────────────────────────────────────
def execute_add_ingredient(arm, ingredient_name, poses):
    """
    Full sequence: pick ingredient container → move to main cup → pour → return container.
    """
    tag_id = INGREDIENT_TAG_MAP[ingredient_name]
    if tag_id not in poses:
        print(f'[ERROR] AprilTag {tag_id} for "{ingredient_name}" not detected.')
        return False
    if MAIN_CUP_TAG_ID not in poses:
        print(f'[ERROR] Main cup (tag {MAIN_CUP_TAG_ID}) not detected.')
        return False

    container_pose = poses[tag_id]
    cup_pose = poses[MAIN_CUP_TAG_ID]

    print(f'  Picking up {ingredient_name} container (tag {tag_id})...')
    pick_container(arm, container_pose)

    print(f'  Moving above main cup...')
    move_above_cup(arm, cup_pose)

    print(f'  Pouring {ingredient_name}...')
    pour(arm, cup_pose)

    print(f'  Returning {ingredient_name} container...')
    place_container(arm, container_pose)

    return True


def execute_stir(arm, poses):
    """
    Full sequence: pick stirrer → stir in main cup → return stirrer.
    """
    if STIRRER_TAG_ID not in poses:
        print(f'[ERROR] Stirrer (tag {STIRRER_TAG_ID}) not detected.')
        return False
    if MAIN_CUP_TAG_ID not in poses:
        print(f'[ERROR] Main cup (tag {MAIN_CUP_TAG_ID}) not detected.')
        return False

    stirrer_pose = poses[STIRRER_TAG_ID]
    cup_pose = poses[MAIN_CUP_TAG_ID]

    print(f'  Picking up stirrer (tag {STIRRER_TAG_ID})...')
    pick_container(arm, stirrer_pose)

    print(f'  Stirring...')
    stir(arm, cup_pose)

    print(f'  Returning stirrer...')
    place_container(arm, stirrer_pose)

    return True


# ──────────────────────────────────────────────
# OpenAI Vision Task Planner
# ──────────────────────────────────────────────
TASK_PLAN_PROMPT = """You are a robotic task planner for a beverage-making robot.

You will be shown an image of a tabletop with several containers. Each container has a
white label indicating its contents (e.g., "coffee", "sugar", "milk"). There is also a
main cup containing water and a stirring stick.

Your job is to output a task plan to make coffee. The plan should be a JSON array of
action objects. Each action has a "action" field and optionally an "ingredient" field.

Available actions:
- {"action": "ADD_INGREDIENT", "ingredient": "<name>"} — Pick up the named ingredient
  container, bring it to the main cup, pour it, and return it to its original position.
- {"action": "STIR"} — Pick up the stirring stick, stir the contents of the main cup,
  and return the stick.

Valid ingredient names: "coffee", "milk", "sugar"

Rules:
1. Add all visible ingredients needed for coffee (coffee is required; milk and sugar
   are optional but include them if their containers are visible).
2. Always add coffee first.
3. Always STIR as the final step after all ingredients have been added.
4. Output ONLY the JSON array, no other text.

Example output:
[
  {"action": "ADD_INGREDIENT", "ingredient": "coffee"},
  {"action": "ADD_INGREDIENT", "ingredient": "sugar"},
  {"action": "ADD_INGREDIENT", "ingredient": "milk"},
  {"action": "STIR"}
]"""


def get_task_plan(image):
    """
    Send the camera image to OpenAI Vision API and get back a structured task plan.

    Parameters
    ----------
    image : numpy.ndarray
        BGR/BGRA image from the camera.

    Returns
    -------
    list[dict]
        Parsed list of task actions.
    """
    # Encode image to base64 JPEG
    if len(image.shape) > 2 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    _, buffer = cv2.imencode('.jpg', image)
    b64_image = base64.b64encode(buffer).decode('utf-8')

    client = OpenAI()  # uses OPENAI_API_KEY env var

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': TASK_PLAN_PROMPT},
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/jpeg;base64,{b64_image}',
                        },
                    },
                ],
            }
        ],
        max_tokens=500,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1]
        raw = raw.rsplit('```', 1)[0]

    plan = json.loads(raw)
    return plan


# ──────────────────────────────────────────────
# Task Executor
# ──────────────────────────────────────────────
def execute_plan(arm, plan, poses):
    """
    Execute a task plan (list of action dicts) using the robot.

    Parameters
    ----------
    arm : XArmAPI
    plan : list[dict]
        Task plan from OpenAI.
    poses : dict
        Mapping of tag_id → 4x4 pose matrix from ContainerDetector.
    """
    for i, step in enumerate(plan):
        action = step['action']
        print(f'\n[Step {i+1}/{len(plan)}] {action}', end='')
        if 'ingredient' in step:
            print(f' — {step["ingredient"]}')
        else:
            print()

        if action == 'ADD_INGREDIENT':
            ingredient = step['ingredient'].lower()
            if ingredient not in INGREDIENT_TAG_MAP:
                print(f'  [SKIP] Unknown ingredient: {ingredient}')
                continue
            success = execute_add_ingredient(arm, ingredient, poses)
            if not success:
                print(f'  [ABORT] Failed to add {ingredient}.')
                return False

        elif action == 'STIR':
            success = execute_stir(arm, poses)
            if not success:
                print(f'  [ABORT] Failed to stir.')
                return False

        else:
            print(f'  [SKIP] Unknown action: {action}')

        # Return home between steps for safety
        arm.move_gohome(wait=True)
        time.sleep(0.5)

    print('\nBeverage preparation complete!')
    return True


# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
def main():
    # Initialize ZED Camera
    zed = ZedCamera()
    camera_intrinsic = zed.camera_intrinsic

    # Initialize container detector
    detector = ContainerDetector(camera_intrinsic)

    # Initialize Lite6 Robot
    arm = XArmAPI(ROBOT_IP)
    arm.connect()
    arm.motion_enable(enable=True)
    arm.set_tcp_offset([0, 0, GRIPPER_LENGTH, 0, 0, 0])
    arm.set_mode(0)
    arm.set_state(0)
    arm.move_gohome(wait=True)
    time.sleep(0.5)

    try:
        # Step 1: Capture scene
        print('Capturing scene...')
        cv_image = zed.image

        # Step 2: Detect all container poses via AprilTags
        print('Detecting containers...')
        poses = detector.detect_all(cv_image)
        if poses is None or len(poses) == 0:
            print('No containers detected. Aborting.')
            return

        detected_tags = list(poses.keys())
        print(f'Detected tags: {detected_tags}')

        # Verify main cup is visible
        if MAIN_CUP_TAG_ID not in poses:
            print(f'Main cup (tag {MAIN_CUP_TAG_ID}) not detected. Aborting.')
            return

        # Step 3: Send image to OpenAI for task planning
        print('\nSending image to OpenAI for task planning...')
        plan = get_task_plan(cv_image)
        print('Received task plan:')
        print(json.dumps(plan, indent=2))

        # Step 4: Confirm with user before executing
        print('\nPress "k" on the image window to execute, or any other key to abort.')
        cv2.namedWindow('Beverage Setup', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('Beverage Setup', 1280, 720)
        cv2.imshow('Beverage Setup', cv_image)
        key = cv2.waitKey(0)
        cv2.destroyAllWindows()

        if key != ord('k'):
            print('Aborted by user.')
            return

        # Step 5: Execute the plan
        print('\nExecuting task plan...')
        execute_plan(arm, plan, poses)

    finally:
        arm.move_gohome(wait=True)
        time.sleep(0.5)
        arm.disconnect()
        zed.close()


if __name__ == '__main__':
    main()
