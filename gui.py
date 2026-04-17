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

from config import BEVERAGE_RECIPES, DIETARY_CONDITIONS
from FP1 import run_beverage_task
from gesture_input import get_order_from_gesture


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
        root.geometry('640x720')

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
            '1 finger: Coffee',
            '2 fingers (Peace): Orange Juice',
            '3 fingers: Chocolate',
            '4 fingers: Toggle lactose-free',
            'OK: Confirm order',
            'Fist;  Cancel / restart',
        ]
        for hint in hints:
            ttk.Label(self.gesture_frame, text=hint, font=('TkDefaultFont', 11)).pack(anchor='w', pady=1)

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
            self._log('Starting gesture ordering — show your hand to the camera.')
            self._log('1 finger=Coffee  Peace=OJ  3 fingers=No milk')
            self._log('OK=Confirm  Fist=Cancel')
            self.execute_btn.configure(state='disabled')
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

    def _run_gesture_task(self):
        from utils.zed_camera import ZedCamera
        zed = ZedCamera()
        try:
            beverage, conditions = get_order_from_gesture(
                zed, timeout=90.0, log=self._log,
            )
            if beverage is None:
                self._log('[INFO] No order placed via gesture.')
                return

            # Build requirement string exactly as FP1 expects
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
            zed.close()
            self.root.after(0, lambda: self.execute_btn.configure(state='normal'))


def main():
    root = tk.Tk()
    BeverageGUI(root)
    root.mainloop()


if __name__ == '__main__':
    main()
