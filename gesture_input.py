"""
Gesture → Robot Action mapping:
    one   → Order: Coffee
    peace → Order: Orange juice
    three → Order: Chocolate
    four  → Toggle: lactose-free (skips milk)
    five  → Toggle: diabetic (skips sugar)
    ok    → Confirm current selection
    fist  → Cancel / clear selection
"""

import threading
import cv2, time, torch
from PIL import Image
from transformers import AutoImageProcessor, SiglipForImageClassification
import mediapipe as mp

HF_MODEL = 'prithivMLmods/Hand-Gesture-19'


GESTURE_TO_BEVERAGE = {
    'one':   'coffee',
    'peace': 'orange juice',
    'three': 'chocolate',
}
GESTURE_TO_CONDITION = {
    'four': 'lactose intolerant',   # 4 fingers = skip milk
    'five': 'diabetic',             # 5 fingers = skip sugar
}
CONFIRM_GESTURE = 'ok'
CANCEL_GESTURE  = 'fist'

CONFIDENCE_THRESHOLD = 0.75  
DEBOUNCE_FRAMES      = 15    
                               
class GestureRecognizer:

    def __init__(self):
        print('Loading gesture classifier from HuggingFace (first run downloads ~400 MB)...')
        self.processor = AutoImageProcessor.from_pretrained(HF_MODEL)
        self.model     = SiglipForImageClassification.from_pretrained(HF_MODEL)
        self.model.eval()

        self.mp_hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.5,
        )
        print('GestureRecognizer ready.')

    def predict(self, frame):

        annotated = frame.copy()
        h, w = frame.shape[:2]

        rgb    = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self.mp_hands.process(rgb)

        if not result.multi_hand_landmarks:
            cv2.putText(annotated, 'No hand detected', (20, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)
            return None, 0.0, annotated

        lm  = result.multi_hand_landmarks[0].landmark
        xs  = [l.x for l in lm]
        ys  = [l.y for l in lm]
        pad = 0.15
        x1  = max(0, int((min(xs) - pad) * w))
        y1  = max(0, int((min(ys) - pad) * h))
        x2  = min(w, int((max(xs) + pad) * w))
        y2  = min(h, int((max(ys) + pad) * h))

        crop = frame[y1:y2, x1:x2]
        if crop.size == 0:
            return None, 0.0, annotated

        pil_img = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        inputs  = self.processor(images=pil_img, return_tensors='pt')
        with torch.no_grad():
            logits = self.model(**inputs).logits
            probs  = torch.softmax(logits, dim=1)
            conf, idx = probs.max(dim=1)

        label = self.model.config.id2label[idx.item()]
        conf  = conf.item()

        color = (0, 255, 0) if conf >= CONFIDENCE_THRESHOLD else (0, 165, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(annotated, f'{label} {conf:.0%}',
                    (x1, max(y1 - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.85, color, 2)

        if conf < CONFIDENCE_THRESHOLD:
            return None, conf, annotated

        return label, conf, annotated


class WebcamSource:
    """Minimal cv2.VideoCapture wrapper that matches the `image`/`close` API
    used by ZedCamera, so get_order_from_gesture can consume either source."""
    def __init__(self, cam_id=0):
        self.cap = cv2.VideoCapture(cam_id)
        if not self.cap.isOpened():
            raise RuntimeError(f'Could not open webcam {cam_id}.')

    @property
    def image(self):
        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError('Webcam read failed.')
        return frame

    def close(self):
        self.cap.release()


def get_order_from_gesture(cam, timeout=60.0, log=print,
                           on_frame=None, stop_event=None):
    """
    Parameters
    ----------
    cam : object with `.image` returning a BGR numpy frame (ZedCamera or WebcamSource).
    on_frame : optional callable(annotated_bgr_frame). If provided, the caller
        is responsible for displaying frames (e.g. an embedded Tk panel) and
        no OpenCV window is created.
    stop_event : optional threading.Event that, when set, breaks the loop early.
    """
    recognizer = GestureRecognizer()

    selected_beverage = None
    active_conditions = set()
    debounce_buffer   = []
    last_acted        = None
    deadline          = time.time() + timeout

    log('─── Gesture ordering active ───')
    log('one finger: Coffee')
    log('peace (2): Orange Juice')
    log('three fingers: Chocolate')
    log('four fingers: Toggle lactose-free (skip milk)')
    log('five (open palm): Toggle diabetic (skip sugar)')
    log('ok: Confirm')
    log('fist: Cancel / restart')

    use_cv_window = on_frame is None
    if use_cv_window:
        cv2.namedWindow('Gesture Order', cv2.WINDOW_NORMAL)
        cv2.resizeWindow('Gesture Order', 960, 540)

    try:
        while time.time() < deadline:
            if stop_event is not None and stop_event.is_set():
                break

            frame    = cam.image
            gesture, conf, annotated = recognizer.predict(frame)

            debounce_buffer.append(gesture)
            if len(debounce_buffer) > DEBOUNCE_FRAMES:
                debounce_buffer.pop(0)

            stable = None
            if (len(debounce_buffer) == DEBOUNCE_FRAMES
                    and len(set(debounce_buffer)) == 1
                    and debounce_buffer[0] is not None):
                stable = debounce_buffer[0]

            if stable != last_acted:
                last_acted = stable

                if stable == CANCEL_GESTURE:
                    log('Cancel — selection cleared.')
                    selected_beverage = None
                    active_conditions.clear()
                    debounce_buffer.clear()

                elif stable in GESTURE_TO_BEVERAGE:
                    selected_beverage = GESTURE_TO_BEVERAGE[stable]
                    log(f'Selected: {selected_beverage}')

                elif stable in GESTURE_TO_CONDITION:
                    cond = GESTURE_TO_CONDITION[stable]
                    if cond in active_conditions:
                        active_conditions.discard(cond)
                        log(f'Removed condition: {cond}')
                    else:
                        active_conditions.add(cond)
                        log(f'Added condition: {cond}')

                elif stable == CONFIRM_GESTURE:
                    if selected_beverage:
                        log(f'Confirmed: {selected_beverage} | '
                            f'conditions: {list(active_conditions) or "none"}')
                        return selected_beverage, list(active_conditions)
                    else:
                        log('OK detected — select a beverage first (show 1, 2 or 3 fingers).')

            _draw_hud(annotated, selected_beverage, active_conditions,
                      stable, time.time(), deadline)

            if use_cv_window:
                cv2.imshow('Gesture Order', annotated)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            else:
                on_frame(annotated)

        log('Gesture ordering ended (timeout or quit).')
        return None, None
    finally:
        if use_cv_window:
            cv2.destroyAllWindows()


def _draw_hud(frame, beverage, conditions, stable, now, deadline):
    h, w      = frame.shape[:2]
    remaining = max(0, deadline - now)

    overlay = frame.copy()
    cv2.rectangle(overlay, (0, h - 110), (w, h), (20, 20, 20), -1)
    cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)

    bev_color = (0, 255, 120) if beverage else (120, 120, 120)
    cv2.putText(frame, f'Order : {beverage or "---"}',
                (20, h - 75), cv2.FONT_HERSHEY_SIMPLEX, 0.85, bev_color, 2)

    cond_str = ', '.join(conditions) if conditions else 'none'
    cv2.putText(frame, f'Mods  : {cond_str}',
                (20, h - 42), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (180, 180, 180), 2)

    timer_color = (0, 200, 255) if remaining > 10 else (0, 80, 255)
    cv2.putText(frame, f'{remaining:.0f}s',
                (w - 80, h - 65), cv2.FONT_HERSHEY_SIMPLEX, 1.0, timer_color, 2)

    if stable:
        role = (GESTURE_TO_BEVERAGE.get(stable)
                or GESTURE_TO_CONDITION.get(stable)
                or stable)
        cv2.putText(frame, f'[ {stable} → {role} ]',
                    (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 220, 0), 2)


if __name__ == '__main__':
    print('Standalone test (webcam). Press Q to quit.\n')
    cam = WebcamSource()
    try:
        beverage, conditions = get_order_from_gesture(cam, timeout=90.0)
        if beverage:
            req = f'I want {beverage}.'
            if conditions:
                req += f' Dietary conditions: {", ".join(conditions)}.'
            print(f'\n→ Requirement string for FP1: {req!r}')
        else:
            print('\nNo order placed.')
    finally:
        cam.close()
