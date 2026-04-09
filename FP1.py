"""
FP1 – Beverage-Making Robot (Coffee)

Main orchestrator: captures the scene, detects containers, gets a task plan
from OpenAI, and executes it on the Lite6 arm.
"""

import cv2, json, time
from xarm.wrapper import XArmAPI

from utils.zed_camera import ZedCamera
from checkpoint1 import GRIPPER_LENGTH
from config import ROBOT_IP, INGREDIENT_TAG_MAP
from primitives import ContainerDetector, execute_add_ingredient, execute_stir
from task_planner import get_task_plan


def execute_plan(arm, plan, poses):
    """
    Execute a task plan (list of action dicts) using the robot.
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
