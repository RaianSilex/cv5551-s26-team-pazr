"""
Tkinter GUI for the beverage-making robot.

The user picks one of three input modes:
  - Buttons: choose a beverage and optional dietary conditions via checkboxes.
  - Text prompt: type a free-form request.
  - Gesture: use hand gestures via the ZED camera.

Either way, a user-requirement string is built and sent through the full
capture -> plan -> execute pipeline in FP1.run_beverage_task.
"""

import threading
import tkinter as tk
from tkinter import ttk, scrolledtext

import cv2
from PIL import Image, ImageTk

from config import BEVERAGE_RECIPES, DIETARY_CONDITIONS
from FP1 import run_beverage_task
from gesture_input import WebcamSource, get_order_from_gesture

# Max width (px) of the embedded webcam preview in the gesture panel.
GESTURE_PREVIEW_WIDTH = 480


# Which conditions apply to which beverages. A condition is only offered for
# a beverage if at least one of the ingredients it restricts appears in that
# beverage's recipe (required + optional).
def _relevant_conditions(beverage):
    recipe = BEVERAGE_RECIPES[beverage]
    recipe_ingredients = set(recipe['required']) | set(recipe['optional'])
    return [
        cond for cond, skipped in DIETARY_CONDITIONS.items()
        if any(ing in recipe_ingredients for ing in skipped)
    ]


class BeverageGUI:
    def __init__(self, root):
        self.root = root
        root.title('Beverage Robot')
        root.geometry('640x900')

        # ── Mode selector ─────────────────────────────
        mode_frame = ttk.LabelFrame(root, text='Input mode', padding=10)
        mode_frame.pack(fill='x', padx=10, pady=(10, 5))

        self.mode = tk.StringVar(value='buttons')
        ttk.Radiobutton(
            mode_frame, text='Buttons', value='buttons',
            variable=self.mode, command=self._on_mode_change,
        ).pack(side='left', padx=10)
        ttk.Radiobutton(
            mode_frame, text='Text prompt', value='text',
            variable=self.mode, command=self._on_mode_change,
        ).pack(side='left', padx=10)
        ttk.Radiobutton(
            mode_frame, text='Gesture', value='gesture',
            variable=self.mode, command=self._on_mode_change,
        ).pack(side='left', padx=10)

        # ── Buttons panel ─────────────────────────────
        self.buttons_frame = ttk.LabelFrame(root, text='Choose a beverage', padding=10)
        self.buttons_frame.pack(fill='x', padx=10, pady=5)

        self.selected_beverage = tk.StringVar(value='')
        # Condition checkboxes: keyed by (beverage, condition) -> BooleanVar
        self.condition_vars = {}

        for beverage in BEVERAGE_RECIPES:
            sub = ttk.Frame(self.buttons_frame)
            sub.pack(fill='x', pady=4)

            ttk.Radiobutton(
                sub, text=beverage.upper(), value=beverage,
                variable=self.selected_beverage,
            ).pack(side='left')

            conds_frame = ttk.Frame(sub)
            conds_frame.pack(side='left', padx=20)
            for cond in _relevant_conditions(beverage):
                var = tk.BooleanVar(value=False)
                self.condition_vars[(beverage, cond)] = var
                ttk.Checkbutton(conds_frame, text=cond, variable=var).pack(side='left', padx=5)

        # ── Text prompt panel ─────────────────────────
        self.text_frame = ttk.LabelFrame(root, text='Text prompt', padding=10)
        self.text_entry = tk.Text(self.text_frame, height=4, wrap='word')
        self.text_entry.pack(fill='both', expand=True)
        self.text_entry.insert(
            '1.0',
            'e.g. I want coffee, but I am lactose intolerant.',
        )

        # ── Gesture hint panel ────────────────────────
        self.gesture_frame = ttk.LabelFrame(root, text='Gesture guide', padding=10)
        hints = [
            ('1 finger',           'Order coffee'),
            ('2 fingers (peace)',  'Order orange juice'),
            ('3 fingers',          'Order chocolate'),
            ('4 fingers',          'Toggle lactose-free (skip milk)'),
            ('5 fingers (open palm)', 'Toggle diabetic (skip sugar)'),
            ('OK sign',            'Confirm the current order'),
            ('Fist',               'Cancel / clear selection'),
        ]
        for gesture_name, meaning in hints:
            row = ttk.Frame(self.gesture_frame)
            row.pack(fill='x', anchor='w', pady=1)
            ttk.Label(row, text=f'{gesture_name}:', width=22,
                      font=('TkDefaultFont', 10, 'bold')).pack(side='left')
            ttk.Label(row, text=meaning,
                      font=('TkDefaultFont', 10)).pack(side='left')

        ttk.Label(
            self.gesture_frame,
            text='Toggles and the beverage choice both feed into the same request.',
            font=('TkDefaultFont', 9, 'italic'),
            foreground='#555555',
        ).pack(anchor='w', pady=(6, 4))

        # Embedded webcam preview (populated during gesture ordering).
        self.camera_label = ttk.Label(self.gesture_frame, anchor='center',
                                      text='(Camera preview appears here when you press "Make Beverage")',
                                      background='#000000', foreground='#bbbbbb')
        self.camera_label.pack(pady=(4, 0))
        self._camera_photo = None  # keep a reference so Tk does not GC the image
        self._gesture_stop_event = None

        # ── Execute button ────────────────────────────
        self.execute_btn = ttk.Button(
            root, text='Make Beverage', command=self._on_execute,
        )
        self.execute_btn.pack(fill='x', padx=10, pady=10)

        # ── Output / status ───────────────────────────
        out_frame = ttk.LabelFrame(root, text='Status', padding=10)
        out_frame.pack(fill='both', expand=True, padx=10, pady=(5, 10))
        self.output = scrolledtext.ScrolledText(out_frame, wrap='word', state='disabled')
        self.output.pack(fill='both', expand=True)

        self._on_mode_change()

    # ──────────────────────────────────────────────
    # UI helpers
    # ──────────────────────────────────────────────
    def _on_mode_change(self):
        mode = self.mode.get()
        # Hide all panels first
        self.buttons_frame.pack_forget()
        self.text_frame.pack_forget()
        self.gesture_frame.pack_forget()

        if mode == 'buttons':
            self.buttons_frame.pack(fill='x', padx=10, pady=5,
                                    before=self.execute_btn)
        elif mode == 'text':
            self.text_frame.pack(fill='x', padx=10, pady=5,
                                 before=self.execute_btn)
        else:  # gesture
            self.gesture_frame.pack(fill='x', padx=10, pady=5,
                                    before=self.execute_btn)

    def _log(self, message):
        # Thread-safe append to the status area.
        def append():
            self.output.configure(state='normal')
            self.output.insert('end', f'{message}\n')
            self.output.see('end')
            self.output.configure(state='disabled')
        self.root.after(0, append)

    def _clear_log(self):
        self.output.configure(state='normal')
        self.output.delete('1.0', 'end')
        self.output.configure(state='disabled')

    def _build_requirement_from_buttons(self):
        beverage = self.selected_beverage.get()
        if not beverage:
            return None, 'Please select a beverage.'
        active_conds = [
            cond for (bev, cond), var in self.condition_vars.items()
            if bev == beverage and var.get()
        ]
        parts = [f'I want {beverage}.']
        if active_conds:
            parts.append('Dietary conditions: ' + ', '.join(active_conds) + '.')
        return ' '.join(parts), None

    def _build_requirement_from_text(self):
        text = self.text_entry.get('1.0', 'end').strip()
        if not text:
            return None, 'Please type a request.'
        return text, None

    # ──────────────────────────────────────────────
    # Execution
    # ──────────────────────────────────────────────
    def _on_execute(self):
        # ── Gesture mode ──
        if self.mode.get() == 'gesture':
            self._clear_log()
            self._log('Starting gesture ordering — show your hand to the laptop webcam.')
            self._log('1=Coffee  2=OJ  3=Chocolate  4=Lactose-free  5=Diabetic')
            self._log('OK=Confirm  Fist=Cancel')
            self.execute_btn.configure(state='disabled')
            self._gesture_stop_event = threading.Event()
            thread = threading.Thread(target=self._run_gesture_task, daemon=True)
            thread.start()
            return

        # ── Buttons / text modes ──
        if self.mode.get() == 'buttons':
            requirement, err = self._build_requirement_from_buttons()
        else:
            requirement, err = self._build_requirement_from_text()

        if err:
            self._clear_log()
            self._log(f'[ERROR] {err}')
            return

        self._clear_log()
        self._log(f'Request: {requirement}')
        self.execute_btn.configure(state='disabled')

        thread = threading.Thread(
            target=self._run_task, args=(requirement,), daemon=True,
        )
        thread.start()

    def _run_task(self, requirement):
        try:
            result = run_beverage_task(
                user_requirement=requirement,
                confirm=True,
                log=self._log,
            )
            self._log('')
            self._log(f'=== {result["status"].upper()}: {result["message"]} ===')
        except Exception as e:
            self._log(f'[EXCEPTION] {type(e).__name__}: {e}')
        finally:
            self.root.after(0, lambda: self.execute_btn.configure(state='normal'))

    def _update_preview(self, bgr_frame):
        """Render an annotated BGR frame into the embedded gesture preview.
        Called from the gesture thread; schedules the actual Tk update on the
        main thread."""
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        if w > GESTURE_PREVIEW_WIDTH:
            scale = GESTURE_PREVIEW_WIDTH / float(w)
            new_size = (GESTURE_PREVIEW_WIDTH, int(h * scale))
            pil_img = Image.fromarray(rgb).resize(new_size, Image.BILINEAR)
        else:
            pil_img = Image.fromarray(rgb)

        def apply():
            photo = ImageTk.PhotoImage(image=pil_img)
            self._camera_photo = photo  # retain reference
            self.camera_label.configure(image=photo, text='')
        self.root.after(0, apply)

    def _clear_preview(self):
        def apply():
            self._camera_photo = None
            self.camera_label.configure(
                image='',
                text='(Camera preview appears here when you press "Make Beverage")',
            )
        self.root.after(0, apply)

    def _run_gesture_task(self):
        cam = None
        try:
            cam = WebcamSource()
        except Exception as e:
            self._log(f'[ERROR] Could not open laptop webcam: {e}')
            self.root.after(0, lambda: self.execute_btn.configure(state='normal'))
            return

        try:
            beverage, conditions = get_order_from_gesture(
                cam,
                timeout=90.0,
                log=self._log,
                on_frame=self._update_preview,
                stop_event=self._gesture_stop_event,
            )
            if beverage is None:
                self._log('[INFO] No order placed via gesture.')
                return

            # Build the same requirement string that button/text modes produce
            # so the downstream prompt in FP1 is consistent across input modes.
            req = f'I want {beverage}.'
            if conditions:
                req += f' Dietary conditions: {", ".join(conditions)}.'
            self._log(f'Requirement: {req}')

            result = run_beverage_task(
                user_requirement=req,
                confirm=False,   # gesture already confirmed — skip OpenCV window
                log=self._log,
            )
            self._log('')
            self._log(f'=== {result["status"].upper()}: {result["message"]} ===')

        except Exception as e:
            self._log(f'[EXCEPTION] {type(e).__name__}: {e}')
        finally:
            if cam is not None:
                cam.close()
            self._clear_preview()
            self.root.after(0, lambda: self.execute_btn.configure(state='normal'))


def main():
    root = tk.Tk()
    BeverageGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
