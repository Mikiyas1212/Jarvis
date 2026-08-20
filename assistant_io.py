"""
assistant_io.py — one shared place for talking to the UI and the voice.

Why this exists
---------------
Before this module, almost every skill (reminder, screen_processor,
send_message, flight_finder ...) hand-rolled the same three things:

  * a `_speak()` that pushed a line to `player.ui.gui_queue` AND spun up a
    brand-new asyncio event loop every single call, and
  * a `_clean_for_tts()` markdown stripper, and
  * ad-hoc `set_state` / `write_log` dictionaries typed out inline.

Creating a fresh event loop per utterance is wasteful and, on Windows, can
raise "Event loop is closed" when two skills speak at once. Centralising it
here means every skill gets the same safe behaviour and the UI protocol lives
in exactly one file.

The public surface is tiny and null-safe — every function accepts `player`
and does the right thing when `player` is None (head-less / test mode), so
skills no longer need `if player:` ladders.
"""

from __future__ import annotations

import re
import asyncio
import threading
from typing import Optional, Any


# ── UI states the front-end knows how to render ────────────────────────────────
class State:
    IDLE      = "IDLE"
    LISTENING = "LISTENING"
    THINKING  = "THINKING"
    SPEAKING  = "SPEAKING"
    ERROR     = "ERROR"


# ── a single background event loop, shared by every skill ──────────────────────
# One long-lived loop on one daemon thread. Coroutines are handed to it with
# run_coroutine_threadsafe, so we never create/close loops mid-flight again.
_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, daemon=True,
                             name="assistant-io-loop").start()
    return _loop


def run_coro(coro) -> Any:
    """
    Run an awaitable to completion on the shared loop and return its result.
    Safe to call from any thread. Falls back to a private loop only if the
    shared one somehow can't be used.
    """
    loop = _get_loop()
    try:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()
    except RuntimeError:
        tmp = asyncio.new_event_loop()
        try:
            return tmp.run_until_complete(coro)
        finally:
            tmp.close()


# ── UI queue helpers ───────────────────────────────────────────────────────────
def _queue(player):
    """Return the UI's gui_queue if it exists, else None (head-less mode)."""
    ui = getattr(player, "ui", None)
    return getattr(ui, "gui_queue", None) if ui else None


def emit(player, action: str, data: Any = None) -> None:
    """Push a raw {action, data} message to the UI. No-op without a UI."""
    q = _queue(player)
    if q is not None:
        q.put({"action": action, "data": data})


def set_state(player, state: str) -> None:
    """Tell the UI which visual state to show (see the State class)."""
    emit(player, "set_state", state)


def log(player, text: str, instant: bool = False) -> None:
    """Write a line to the transcript. `instant` skips the type-out animation."""
    emit(player, "write_log_instant" if instant else "write_log", text)


# ── text-to-speech ─────────────────────────────────────────────────────────────
_MD_PATTERNS = [
    (re.compile(r"\*{1,3}"), ""),          # **bold** / *italic*
    (re.compile(r"#{1,6}\s*"), ""),        # # headings
    (re.compile(r"[`_~]"), ""),            # code / underscore / strike
    (re.compile(r"\[([^\]]+)\]\([^)]+\)"), r"\1"),  # [text](url) -> text
    (re.compile(r"\s{2,}"), " "),          # collapse whitespace
]


def clean_for_tts(text: str) -> str:
    """Strip markdown so the voice doesn't read symbols aloud."""
    for pattern, repl in _MD_PATTERNS:
        text = pattern.sub(repl, text)
    return text.strip()


def say(player, text: str, *, prefix: str = "JARVIS", instant: bool = False,
        speaking_state: bool = True) -> None:
    """
    The one function every skill should use to talk.

    * writes the line to the UI transcript (as "PREFIX: text"),
    * flips the UI into SPEAKING while the voice plays, then back to IDLE,
    * runs `player.speak(...)` on the shared loop (no per-call loops),
    * prints to stdout when there is no player (tests / CLI).
    """
    clean = clean_for_tts(text)

    if player is None:
        print(f"[{prefix.lower()}] {clean}")
        return

    log(player, f"{prefix}: {clean}", instant=instant)

    speak = getattr(player, "speak", None)
    if speak is None:
        return

    if speaking_state:
        set_state(player, State.SPEAKING)
    try:
        run_coro(speak(clean))
    finally:
        if speaking_state:
            set_state(player, State.IDLE)
