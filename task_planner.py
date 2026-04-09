"""
OpenAI Vision-based task planner for the beverage-making robot.

Sends a camera image to GPT-4o, which reads the container labels and
returns a structured JSON task plan.
"""

import cv2, json, base64
from openai import OpenAI

from config import INGREDIENT_TAG_MAP

# Build the valid ingredient list dynamically from config
_VALID_INGREDIENTS = ', '.join(f'"{name}"' for name in INGREDIENT_TAG_MAP)

TASK_PLAN_PROMPT = f"""You are a robotic task planner for a beverage-making robot.

You will be shown an image of a tabletop with several containers. Each container has a
white label indicating its contents (e.g., "coffee", "sugar", "milk"). There is also a
stirring stick and main cup containing water.

Your job is to output a task plan to make coffee. The plan should be a JSON array of
action objects. Each action has a "action" field and optionally an "ingredient" field.

Available actions:
- {{"action": "ADD_INGREDIENT", "ingredient": "<name>"}} — Pick up the named ingredient
  container, bring it to the main cup, pour it, and return it to its original position.
- {{"action": "STIR"}} — Pick up the stirring stick, stir the contents of the main cup,
  and return the stick.

Valid ingredient names: {_VALID_INGREDIENTS}

Rules:
1. Add all visible ingredients needed for coffee (coffee is required; milk and sugar
   are optional but include them if their containers are visible).
2. Always add coffee first.
3. Always STIR as the final step after all ingredients have been added.
4. Output ONLY the JSON array, no other text.

Example output:
[
  {{"action": "ADD_INGREDIENT", "ingredient": "coffee"}},
  {{"action": "ADD_INGREDIENT", "ingredient": "sugar"}},
  {{"action": "ADD_INGREDIENT", "ingredient": "milk"}},
  {{"action": "STIR"}}
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

    client = OpenAI(api_key='YOUR_KEY_HERE')  # replace with your key, remove after

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
