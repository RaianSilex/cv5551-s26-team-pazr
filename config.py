"""
Shared configuration for the beverage-making robot.

April Tag Assignments (tag36h11 family):
    Tags 0-3  : Table calibration tags (used by checkpoint0)
    Tag  5    : Coffee powder container
    Tag  6    : Milk powder container
    Tag  7    : Sugar container
    Tag  8    : Stirring stick
"""

ROBOT_IP = '192.168.1.182'

# Map ingredient names to april tag IDs
INGREDIENT_TAG_MAP = {
    'coffee':  5,
    'milk':    6,
    'sugar':   7,
}

STIRRER_TAG_ID = 8

# Fixed position of the main cup in robot base frame (mm).
# Get these from the xArm web interface by moving the arm to the cup.
MAIN_CUP_POSITION = {
    'x': 250.0,   # mm
    'y': 0.0,     # mm
    'z': 20.0,    # mm
}

# Motion parameters (mm)
PRE_GRASP_HEIGHT = 120   # safe height above object
POUR_HEIGHT = 80         # height above main cup when pouring
STIR_DEPTH = 30          # how far stirrer descends into cup
STIR_CYCLES = 3          # number of circular stir motions
POUR_TILT_ANGLE = 60     # degrees to tilt when pouring
