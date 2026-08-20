# JARVIS — UI + code improvements

This drop brings the assistant closer to how modern voice assistants are built:
a single animated "core" that reacts to state, one shared I/O layer, and a set
of skills cleaned up around it. Everything honours the queue protocol your code
already used, so it slots in without a rewrite.

## What's here

| File | What it is | Status |
|------|-----------|--------|
| `ui.py` | Modern Tkinter assistant window (animated core, transcript, mute, text fallback) | **new** |
| `assistant_io.py` | One shared place for speaking + UI messages | **new** |
| `reminder.py` | Reminder skill | refactored |
| `screen_processor.py` | Screen/camera vision | refactored + **security fix** |
| `flight_finder.py` | Google Flights opener | refactored |
| `requirements.txt` | Dependencies | new |

The other skills (`telegram.py`, `whatsapp.py`, `send_message.py`,
`automation.py`, `intent_handler.py`) are unchanged here — see "Applying the
same pattern" below for the one-line-per-call change that brings them onto the
shared layer too.

## The headline: a real UI

Your whole codebase talked to `player.ui` — a `gui_queue`, `set_state`,
`muted`, `_toggle_mute` — but there was no UI file in the upload. `ui.py` is
that object, built to the exact contract the skills expect:

```python
player.ui.gui_queue.put({"action": "write_log",         "data": "JARVIS: ..."})
player.ui.gui_queue.put({"action": "write_log_instant", "data": "JARVIS: ..."})
player.ui.gui_queue.put({"action": "set_state",         "data": "THINKING"})
player.ui.muted             # read by intent_handler
player.ui._toggle_mute()    # called by intent_handler
```

It adds a central **core orb** that animates per state the way Siri / Alexa /
ChatGPT voice mode all do — idle breathing, a listening pulse, a thinking spin,
speaking ripples — plus a live transcript with a type-out effect, a mic mute
toggle, and a text box so it's usable without a microphone. It's pure standard
library (Tkinter), so there's nothing extra to install.

Try it on its own:

```bash
python ui.py     # runs a demo that cycles through the states
```

Wire it into your `Player`:

```python
from ui import AssistantUI

class Player:
    def __init__(self):
        self.ui = AssistantUI(
            title="JARVIS",
            on_text_submit=self.handle_text,   # optional: typed commands
            on_mute_change=self.handle_mute,   # optional
        )
    # ... your speak(), run_async(), etc.

player = Player()
# start your voice loop on a background thread, then:
player.ui.run()   # Tkinter must own the main thread
```

New optional actions the UI also understands (all safe to ignore):
`{"action": "user_said", "data": "..."}`, `{"action": "clear_log"}`, and the
extra states `LISTENING`, `SPEAKING`, `IDLE`, `ERROR`.

## The shared I/O layer

Before, nearly every skill re-implemented the same block: push a line to the
queue, then **create and destroy a brand-new asyncio event loop** to run
`player.speak(...)`. That's wasteful and, on Windows, throws "Event loop is
closed" when two skills speak at once.

`assistant_io.py` centralises it behind one call:

```python
from assistant_io import say, set_state, State

say(player, "Sir, this is your reminder: stand up.")   # logs + speaks + states
set_state(player, State.THINKING)
```

* One long-lived event loop on one daemon thread — no per-call loops.
* Null-safe: pass `player=None` and it just prints, so skills drop their
  `if player:` ladders and tests run head-less.
* Markdown stripping for TTS lives here once, not copied into every file.

## Security fix (please act on this)

`screen_processor.py` shipped a **real-looking Groq API key hard-coded in the
source**. Anyone with the file could spend against that account. The refactor
reads `GROQ_API_KEY` from the environment and refuses to run without it.

**Rotate that key now** — treat it as compromised since it was in a shared
file — then set the new one in your environment:

```bash
# Windows (PowerShell)
setx GROQ_API_KEY "your-new-key"
# macOS / Linux
export GROQ_API_KEY="your-new-key"
```

## Applying the same pattern to the rest

`send_message.py`, `telegram.py`, `whatsapp.py` still have their own `_speak`
and inline `gui_queue.put(...)`. To bring them onto the shared layer, replace
their local speak helper with the import and swap the calls:

```python
# delete the local _speak(...) definition, then:
from assistant_io import say, set_state, State

say(player, "Message sent, sir.")          # was _speak(player, "...")
set_state(player, State.THINKING)          # was gui_queue.put({...})
```

Nothing else in those files needs to change.

## Smaller fixes included

* `flight_finder.py` had a **duplicate `"dubai"` key** in the city→IATA map and
  two different, partly broken event-loop paths (one called
  `get_event_loop().run_until_complete` from a thread that had no loop). Both
  gone.
* `reminder.py` weekday/relative-date parsing preserved exactly, just tidied.

## Notes / next steps

* The desktop-automation skills drive apps by pressing keys and clicking fixed
  screen ratios (e.g. "Tab 11 times to reach the call button"). That's inherently
  brittle — it breaks when an app updates its layout or the window isn't focused.
  If you want, the next improvement is a small `ui_locator` that finds buttons by
  image or accessibility role instead of blind Tab counts.
* Consider a `config.py` (or `.env` + `python-dotenv`) so the timezone, model
  name, and any keys live in one place rather than scattered across files.
