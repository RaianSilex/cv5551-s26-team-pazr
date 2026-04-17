"""
OpenAI Vision-based task planner for the beverage-making robot.

Sends a camera image plus a user requirement string to GPT-4o, which reads
the container labels and returns a structured task plan (or an error if
the ingredients needed aren't visible).
"""

import cv2, json, base64
from openai import OpenAI

from config import INGREDIENT_TAG_MAP, BEVERAGE_RECIPES, DIETARY_CONDITIONS

# Build lists for the prompt dynamically from config
_VALID_INGREDIENTS = ', '.join(f'"{name}"' for name in INGREDIENT_TAG_MAP)
_RECIPES_TEXT = '\n'.join(
    f'  - {bev}: required={r["required"]}, optional={r["optional"]}'
    for bev, r in BEVERAGE_RECIPES.items()
)
_CONDITIONS_TEXT = '\n'.join(
    f'  - "{cond}" → skip: {skipped}'
    for cond, skipped in DIETARY_CONDITIONS.items()
)

BASE_PROMPT = f"""You are a robotic task planner for a beverage-making robot.

You will be shown an image of a tabletop with several containers. Each container has a
white label indicating its contents (e.g., "coffee", "sugar", "milk", "orange",
"chocolate"). There is also a stirring stick and a main cup containing water.

Valid ingredient names: {_VALID_INGREDIENTS}

Beverage recipes:
{_RECIPES_TEXT}

Dietary conditions and their effect:
{_CONDITIONS_TEXT}

Your job:
1. Identify which ingredient containers are visible on the table from their labels.
2. Read the user's request (provided below) and figure out which beverage they want,
   along with any dietary conditions.
3. Check whether all REQUIRED ingredients for the chosen beverage are visible on the
   table. If any required ingredient is missing, return an error.
4. Otherwise, build a task plan using the OPTIONAL ingredients that are visible,
   SKIPPING any ingredient the user's dietary conditions forbid.
5. Always add the primary ingredient (the required one) first.
6. Always STIR as the final step after all ingredients have been added.

Output format (JSON ONLY, no other text, no markdown fences):

Success case:
{{
  "status": "ok",
  "beverage": "<beverage name>",
  "plan": [
    {{"action": "ADD_INGREDIENT", "ingredient": "<name>"}},
    ...
    {{"action": "STIR"}}
  ]
}}

Error case (required ingredient missing, or user wants something we can't make):
{{
  "status": "error",
  "message": "Sorry we don't have the ingredients for that"
}}

Available actions inside the plan:
- {{"action": "ADD_INGREDIENT", "ingredient": "<name>"}} — pick up, pour, return
- {{"action": "STIR"}} — pick stirrer, stir, return stirrer

Output ONLY the JSON object, nothing else."""


def build_prompt(user_requirement):
    """
    Append the user's request to the base prompt.

    Parameters
    ----------
    user_requirement : str
        Free-form text describing what the user wants (e.g.,
        "I want coffee. I am lactose intolerant.")
    """
    req = (user_requirement or '').strip()
    if not req:
        req = 'Make coffee with whatever ingredients are available.'
    return f"{BASE_PROMPT}\n\nUser request: {req}"


def get_task_plan(image, user_requirement=''):
    """
    Send the camera image plus the user's request to the OpenAI Vision API.

    Parameters
    ----------
    image : numpy.ndarray
        BGR/BGRA image from the camera.
    user_requirement : str
        Free-form text describing what the user wants.

    Returns
    -------
    dict
        Parsed response. Either
            {"status": "ok", "beverage": str, "plan": [...]}
        or
            {"status": "error", "message": str}
    """
    # Encode image to base64 JPEG
    if len(image.shape) > 2 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    _, buffer = cv2.imencode('.jpg', image)
    b64_image = base64.b64encode(buffer).decode('utf-8')

    client = OpenAI(api_key='')  # replace with the key, remove after

    prompt = build_prompt(user_requirement)

    response = client.chat.completions.create(
        model='gpt-4o',
        messages=[
            {
                'role': 'user',
                'content': [
                    {'type': 'text', 'text': prompt},
                    {
                        'type': 'image_url',
                        'image_url': {
                            'url': f'data:image/jpeg;base64,{b64_image}',
                        },
                    },
                ],
            }
        ],
        max_tokens=600,
    )

    raw = response.choices[0].message.content.strip()
    # Strip markdown code fences if present
    if raw.startswith('```'):
        raw = raw.split('\n', 1)[1]
        raw = raw.rsplit('```', 1)[0]

    return json.loads(raw)
