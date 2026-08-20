"""
ui.py — a modern voice-assistant interface for JARVIS.

Drop-in for the `player.ui` object the skills already talk to. It honours the
exact contract the rest of the codebase uses, so nothing else has to change:

    player.ui.gui_queue.put({"action": "write_log",         "data": "..."})
    player.ui.gui_queue.put({"action": "write_log_instant", "data": "..."})
    player.ui.gui_queue.put({"action": "set_state",         "data": "THINKING"})
    player.ui.muted            # bool
    player.ui._toggle_mute()   # flips mute

New, optional actions the UI also understands (safe to ignore):
    {"action": "set_state",  "data": "LISTENING" | "SPEAKING" | "IDLE" | "ERROR"}
    {"action": "clear_log"}
    {"action": "user_said",  "data": "the recognised user utterance"}

Design goals
------------
* Pure standard-library Tkinter — no pip install, runs anywhere Python does.
* A single animated "core" orb that reflects state (idle breathing, listening
  pulse, thinking spin, speaking ripple) — the visual language every modern
  assistant uses.
* A clean transcript with a subtle type-out effect for JARVIS lines.
* A mute toggle and a text-entry fallback so it's usable without a mic.

The UI runs on the main thread (Tkinter requires this). Skills push messages
from worker threads via the thread-safe `gui_queue`; a periodic `after()`
pump drains the queue on the UI thread. That indirection is exactly why the
queue exists — never touch Tk widgets from a worker thread.
"""

from __future__ import annotations

import math
import queue
import time
import tkinter as tk
from typing import Callable, Optional


# ── palette (deep-space, matches the studio brand blues) ───────────────────────
BG        = "#05060f"
PANEL     = "#0b1020"
PANEL_2   = "#141a44"
INK       = "#eaf0ff"
MUTED     = "#9aa6d4"
LINE      = "#20264d"

BLUE      = "#3b6dff"
BLUE_LT   = "#5b8cff"
CYAN      = "#57e0ff"
AMBER     = "#ffb020"
RED       = "#ff4d6d"
GREEN     = "#3ddc84"

STATE_COLOR = {
    "IDLE":      BLUE_LT,
    "LISTENING": GREEN,
    "THINKING":  AMBER,
    "SPEAKING":  CYAN,
    "ERROR":     RED,
}
STATE_LABEL = {
    "IDLE":      "Standing by",
    "LISTENING": "Listening…",
    "THINKING":  "Thinking…",
    "SPEAKING":  "Speaking…",
    "ERROR":     "Error",
}


class AssistantUI:
    """The window + the animated core + the transcript."""

    def __init__(self, *, title: str = "JARVIS",
                 on_text_submit: Optional[Callable[[str], None]] = None,
                 on_mute_change: Optional[Callable[[bool], None]] = None):
        # public, read by the skills
        self.gui_queue: "queue.Queue[dict]" = queue.Queue()
        self.muted: bool = False

        self._on_text_submit = on_text_submit
        self._on_mute_change = on_mute_change

        self.state = "IDLE"
        self._t0 = time.time()
        self._typing_queue: list[str] = []
        self._typing_active = False

        self._build(title)
        self._pump_queue()
        self._animate()

    # ── window construction ────────────────────────────────────────────────────
    def _build(self, title: str) -> None:
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=BG)
        self.root.minsize(820, 560)
        try:
            self.root.geometry("980x680")
        except Exception:
            pass

        # header ---------------------------------------------------------------
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", padx=28, pady=(22, 6))

        tk.Label(header, text="JARVIS", bg=BG, fg=INK,
                 font=("Segoe UI Semibold", 20)).pack(side="left")
        tk.Label(header, text="  ·  personal assistant", bg=BG, fg=MUTED,
                 font=("Segoe UI", 11)).pack(side="left", pady=(6, 0))

        self.status_dot = tk.Canvas(header, width=12, height=12, bg=BG,
                                    highlightthickness=0)
        self.status_dot.pack(side="right", padx=(8, 0), pady=(4, 0))
        self.status_lbl = tk.Label(header, text=STATE_LABEL["IDLE"], bg=BG,
                                   fg=MUTED, font=("Segoe UI", 11))
        self.status_lbl.pack(side="right")

        # body: core orb (left) + transcript (right) ---------------------------
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=28, pady=10)

        left = tk.Frame(body, bg=BG, width=320)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        self.core = tk.Canvas(left, width=300, height=300, bg=BG,
                              highlightthickness=0)
        self.core.pack(pady=(30, 10))

        self.state_caption = tk.Label(left, text=STATE_LABEL["IDLE"], bg=BG,
                                      fg=BLUE_LT, font=("Segoe UI Semibold", 14))
        self.state_caption.pack()

        # mute toggle
        self.mute_btn = tk.Button(
            left, text="🔊  Mic on", command=self._toggle_mute,
            bg=PANEL, fg=INK, activebackground=PANEL_2, activeforeground=INK,
            relief="flat", bd=0, font=("Segoe UI", 11), padx=18, pady=9,
            cursor="hand2", highlightthickness=1, highlightbackground=LINE,
        )
        self.mute_btn.pack(pady=22)

        # transcript -----------------------------------------------------------
        right = tk.Frame(body, bg=PANEL, highlightthickness=1,
                         highlightbackground=LINE)
        right.pack(side="right", fill="both", expand=True, padx=(24, 0))

        tk.Label(right, text="TRANSCRIPT", bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", padx=18, pady=(14, 4))

        wrap = tk.Frame(right, bg=PANEL)
        wrap.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.log = tk.Text(
            wrap, bg=PANEL, fg=INK, insertbackground=INK, relief="flat", bd=0,
            wrap="word", font=("Segoe UI", 12), padx=12, pady=8,
            state="disabled", spacing1=4, spacing3=8,
        )
        scroll = tk.Scrollbar(wrap, command=self.log.yview, width=10)
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)

        self.log.tag_configure("jarvis", foreground=CYAN,
                               font=("Segoe UI Semibold", 12))
        self.log.tag_configure("user", foreground=INK,
                               font=("Segoe UI", 12))
        self.log.tag_configure("meta", foreground=MUTED,
                               font=("Segoe UI", 10, "italic"))

        # text-entry fallback --------------------------------------------------
        entry_row = tk.Frame(right, bg=PANEL)
        entry_row.pack(fill="x", padx=12, pady=(0, 14))

        self.entry = tk.Entry(entry_row, bg=PANEL_2, fg=INK, insertbackground=INK,
                              relief="flat", bd=0, font=("Segoe UI", 12))
        self.entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 8))
        self.entry.bind("<Return>", self._submit_text)

        tk.Button(entry_row, text="Send", command=self._submit_text,
                  bg=BLUE, fg="white", activebackground=BLUE_LT,
                  activeforeground="white", relief="flat", bd=0,
                  font=("Segoe UI Semibold", 11), padx=20, pady=9,
                  cursor="hand2").pack(side="right")

        self._log_line("Systems online. How can I help, sir?", tag="jarvis")

    # ── queue pump (runs on UI thread) ─────────────────────────────────────────
    def _pump_queue(self) -> None:
        try:
            while True:
                msg = self.gui_queue.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(40, self._pump_queue)

    def _handle(self, msg: dict) -> None:
        action = msg.get("action")
        data = msg.get("data")

        if action == "set_state":
            self.set_state(str(data))
        elif action == "write_log":
            self._enqueue_typing(str(data))
        elif action == "write_log_instant":
            self._log_line(str(data), tag=self._tag_for(str(data)))
        elif action == "user_said":
            self._log_line(f"You: {data}", tag="user")
        elif action == "clear_log":
            self.log.configure(state="normal")
            self.log.delete("1.0", "end")
            self.log.configure(state="disabled")

    @staticmethod
    def _tag_for(line: str) -> str:
        low = line.lower()
        if low.startswith("jarvis"):
            return "jarvis"
        if low.startswith("you"):
            return "user"
        return "meta"

    # ── transcript writing ──────────────────────────────────────────────────────
    def _log_line(self, text: str, tag: str = "meta") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _enqueue_typing(self, line: str) -> None:
        """Type JARVIS lines out char-by-char for a live feel."""
        self._typing_queue.append(line)
        if not self._typing_active:
            self._type_next()

    def _type_next(self) -> None:
        if not self._typing_queue:
            self._typing_active = False
            return
        self._typing_active = True
        line = self._typing_queue.pop(0)
        tag = self._tag_for(line)
        self.log.configure(state="normal")
        self.log.insert("end", "\n", tag)
        self.log.configure(state="disabled")
        self._type_char(line, 0, tag)

    def _type_char(self, line: str, i: int, tag: str) -> None:
        if i < len(line):
            self.log.configure(state="normal")
            self.log.insert("end", line[i], tag)
            self.log.see("end")
            self.log.configure(state="disabled")
            self.root.after(12, self._type_char, line, i + 1, tag)
        else:
            self.log.configure(state="normal")
            self.log.insert("end", "\n")
            self.log.configure(state="disabled")
            self.root.after(120, self._type_next)

    # ── state + mute ────────────────────────────────────────────────────────────
    def set_state(self, state: str) -> None:
        state = state.upper()
        if state not in STATE_COLOR:
            state = "IDLE"
        self.state = state
        self.status_lbl.configure(text=STATE_LABEL[state])
        self.state_caption.configure(text=STATE_LABEL[state],
                                     fg=STATE_COLOR[state])

    def _toggle_mute(self) -> None:
        self.muted = not self.muted
        self.mute_btn.configure(
            text=("🔇  Mic off" if self.muted else "🔊  Mic on"),
            fg=(RED if self.muted else INK),
        )
        if self._on_mute_change:
            try:
                self._on_mute_change(self.muted)
            except Exception:
                pass

    def _submit_text(self, _evt=None) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self._log_line(f"You: {text}", tag="user")
        if self._on_text_submit:
            try:
                self._on_text_submit(text)
            except Exception:
                pass

    # ── the animated core ───────────────────────────────────────────────────────
    def _animate(self) -> None:
        t = time.time() - self._t0
        c = self.core
        c.delete("all")
        cx, cy, base = 150, 150, 60
        col = STATE_COLOR[self.state]

        # concentric glow rings — count/behaviour vary by state
        if self.state == "THINKING":
            # rotating dashed ring
            for k in range(3):
                r = base + 22 + k * 20
                start = (t * 120 + k * 40) % 360
                c.create_arc(cx - r, cy - r, cx + r, cy + r,
                             start=start, extent=90, style="arc",
                             outline=col, width=2)
        elif self.state == "LISTENING":
            # expanding pulse rings
            for k in range(3):
                phase = (t * 1.2 + k / 3) % 1
                r = base + phase * 70
                alpha = 1 - phase
                w = max(1, int(3 * alpha))
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=col, width=w)
        elif self.state == "SPEAKING":
            # audio-style ripples
            for k in range(4):
                r = base + 14 + k * 16 + math.sin(t * 6 + k) * 5
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=col, width=2)
        else:  # IDLE / ERROR — gentle breathing halo
            for k in range(2):
                r = base + 18 + k * 18 + math.sin(t * 1.6 + k) * 4
                c.create_oval(cx - r, cy - r, cx + r, cy + r,
                              outline=col, width=1)

        # the core orb, softly pulsing
        pulse = 1 + 0.05 * math.sin(t * (5 if self.state == "SPEAKING" else 2))
        r = base * pulse
        # layered fills for a glow effect
        for rr, shade in ((r + 14, PANEL_2), (r + 6, PANEL), (r, col)):
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr,
                          fill=shade, outline="")
        # inner highlight
        c.create_oval(cx - r * 0.5, cy - r * 0.62, cx + r * 0.2, cy - r * 0.1,
                      fill=BLUE_LT, outline="")
        # tiny rocket glyph in the centre (brand nod)
        c.create_text(cx, cy, text="🚀", font=("Segoe UI Emoji", 26))

        # status dot in the header
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, 11, 11, fill=col, outline="")

        self.root.after(33, self._animate)  # ~30 fps

    # ── lifecycle ───────────────────────────────────────────────────────────────
    def run(self) -> None:
        self.root.mainloop()


# ── standalone demo — python ui.py ─────────────────────────────────────────────
if __name__ == "__main__":
    ui = AssistantUI(
        on_text_submit=lambda text: ui.gui_queue.put(
            {"action": "write_log", "data": f"JARVIS: You said “{text}”. (demo)"}),
    )

    # cycle through the states so you can see the core react
    import itertools, threading

    def _demo():
        for st in itertools.cycle(["THINKING", "SPEAKING", "LISTENING", "IDLE"]):
            time.sleep(2.6)
            ui.gui_queue.put({"action": "set_state", "data": st})
            if st == "SPEAKING":
                ui.gui_queue.put({"action": "write_log",
                                  "data": "JARVIS: All systems nominal, sir."})

    threading.Thread(target=_demo, daemon=True).start()
    ui.run()
