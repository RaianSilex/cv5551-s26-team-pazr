"""
Test script for beverage robot primitives — no LLM required.

Runs a hardcoded coffee-making sequence so you can verify
pick, pour, place, and stir motions on the physical setup.

Usage:
    python test_primitives.py              # run full sequence (coffee, sugar, milk, stir)
    python test_primitives.py coffee       # test only coffee
    python test_primitives.py stir         # test only stirring
    python test_primitives.py coffee sugar # test coffee then sugar
"""

import cv2, sys, time, json
from xarm.wrapper import XArmAPI

from utils.zed_camera import ZedCamera
from checkpoint1 import GRIPPER_LENGTH
from config import ROBOT_IP, INGREDIENT_TAG_MAP, STIRRER_TAG_ID, MAIN_CUP_POSITION
from primitives import ContainerDetector, execute_add_ingredient, execute_stir


def main():
    # Parse which steps to test from command line
    args = sys.argv[1:]
    if not args:
        # Default: full coffee sequence
        steps = list(INGREDIENT_TAG_MAP.keys()) + ['stir']
    else:
        steps = [a.lower() for a in args]

    print(f'Test sequence: {steps}')

    # Initialize ZED Camera
    zed = ZedCamera()
    camera_intrinsic = zed.camera_intrinsic

    # Detect containers
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
        # Capture and detect
        print('Capturing scene...')
        cv_image = zed.image

        print('Detecting AprilTags...')
        poses = detector.detect_all(cv_image)
        if poses is None or len(poses) == 0:
            print('No tags detected. Aborting.')
            return

        print(f'Detected tag IDs: {list(poses.keys())}')

        # Show what was detected and wait for confirmation
        print('\nExpected tags:')
        for name, tag_id in INGREDIENT_TAG_MAP.items():
            status = 'FOUND' if tag_id in poses else 'MISSING'
            print(f'  {name:>10} (tag {tag_id}): {status}')
        print(f'  {"stirrer":>10} (tag {STIRRER_TAG_ID}): {"FOUND" if STIRRER_TAG_ID in poses else "MISSING"}')
        print(f'  {"main cup":>10}: fixed position (x={MAIN_CUP_POSITION["x"]}, y={MAIN_CUP_POSITION["y"]}, z={MAIN_CUP_POSITION["z"]})')

        print('\nPress "k" on the image window to execute, any other key to abort.')
        cv2.namedWindow('Test Primitives', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('Test Primitives', 1280, 720)
        cv2.imshow('Test Primitives', cv_image)
        key = cv2.waitKey(0)
        cv2.destroyAllWindows()

        if key != ord('k'):
            print('Aborted by user.')
            return

        # Execute each step
        for step in steps:
            print(f'\n=== Testing: {step} ===')

            if step == 'stir':
                success = execute_stir(arm, poses)
            elif step in INGREDIENT_TAG_MAP:
                success = execute_add_ingredient(arm, step, poses)
            else:
                print(f'Unknown step: {step}. Skipping.')
                continue

            if not success:
                print(f'Step "{step}" failed. Stopping.')
                return

            arm.move_gohome(wait=True)
            time.sleep(0.5)

        print('\nAll tests completed successfully!')

    finally:
        arm.move_gohome(wait=True)
        time.sleep(0.5)
        arm.disconnect()
        zed.close()


if __name__ == '__main__':
    main()
