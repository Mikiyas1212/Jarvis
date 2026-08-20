"""
screen_processor.py — capture the screen or camera, ask a Groq vision model
what it sees, and speak the answer.

Changes vs. the original:
  * The Groq API key is no longer hard-coded. It is read from the GROQ_API_KEY
    environment variable, and we fail loudly with a clear message if it's unset.
    (The previous file shipped a real-looking key in source — anyone with the
    file could spend against that account. Rotate that key.)
  * Speaking + UI state go through assistant_io, so no per-call event loops and
    no duplicated TTS-cleaning code.
"""

import io
import os
import base64
import time
import threading

from assistant_io import say, set_state, State

VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


def _client():
    """Build a Groq client, requiring the key to come from the environment."""
    from groq import Groq
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError(
            "GROQ_API_KEY is not set. Add it to your environment "
            "(e.g. a .env file or system variables) before using vision."
        )
    return Groq(api_key=key)


# ── screen capture ─────────────────────────────────────────────────────────────
def _capture_screen() -> tuple[bytes, str]:
    """Return (png_bytes, mime). Tries mss first, then PIL."""
    try:
        import mss
        import mss.tools
        with mss.mss() as sct:
            shot = sct.grab(sct.monitors[1])
            return mss.tools.to_png(shot.rgb, shot.size), "image/png"
    except Exception:
        pass
    try:
        from PIL import ImageGrab
        buf = io.BytesIO()
        ImageGrab.grab().save(buf, format="PNG")
        return buf.getvalue(), "image/png"
    except Exception as e:
        raise RuntimeError(f"Screen capture failed: {e}")


# ── camera capture ─────────────────────────────────────────────────────────────
def _capture_camera() -> tuple[bytes, str]:
    """
    Return (jpeg_bytes, mime). Tries indices 0-4 with CAP_DSHOW then CAP_ANY,
    warms up 50 frames, retries up to 10 times on a black frame. Raises rather
    than silently falling back to a screenshot.
    """
    try:
        import cv2
    except ImportError:
        raise RuntimeError("opencv-python not installed. Run: pip install opencv-python")

    for backend_name, backend in [("CAP_DSHOW", cv2.CAP_DSHOW), ("CAP_ANY", cv2.CAP_ANY)]:
        for idx in range(5):
            cap = cv2.VideoCapture(idx, backend)
            if not cap.isOpened():
                cap.release()
                continue

            print(f"[camera] opened idx={idx} backend={backend_name}")
            for _ in range(50):            # warm up auto-exposure
                cap.read()

            frame = None
            for _ in range(10):
                ret, f = cap.read()
                if ret and f is not None and f.mean() > 8:
                    frame = f
                    break
                time.sleep(0.05)

            cap.release()
            if frame is None:
                print(f"[camera] idx={idx} {backend_name}: black/empty, skipping")
                continue

            h, w = frame.shape[:2]
            if w > 1280:
                frame = cv2.resize(frame, (1280, int(h * 1280 / w)))
            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            print(f"[camera] captured {len(buf.tobytes()):,} bytes from idx={idx}")
            return buf.tobytes(), "image/jpeg"

    raise RuntimeError(
        "No working camera found on indices 0-4. "
        "Check the webcam is connected and not in use by another app."
    )


# ── vision query ──────────────────────────────────────────────────────────────
def _query_vision(image_bytes: bytes, question: str, mime: str,
                  elaborate: bool = False) -> str:
    client = _client()
    b64 = base64.standard_b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    if elaborate:
        instruction = (
            "You are looking at a screen. Focus ONLY on the main content — "
            "if this is a presentation or slide, read and summarize the slide "
            "content, bullet points, headings, and key information. Ignore "
            "taskbars, browser chrome, window borders, notifications, and system "
            "UI. Give a clear, concise summary in up to 10 sentences. Address the "
            "user as 'sir' once at the very end only."
        )
    else:
        instruction = (
            f"{question}\n\nAnswer concisely in 2-3 sentences. "
            "Address the user as 'sir' once at the very end only."
        )

    response = client.chat.completions.create(
        model=VISION_MODEL,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text", "text": instruction},
            ],
        }],
        max_tokens=1024 if elaborate else 512,
    )
    return response.choices[0].message.content.strip()


# ── main entry point ──────────────────────────────────────────────────────────
def screen_process(params: dict, player=None) -> None:
    angle = params.get("angle", "screen").lower()
    question = params.get("text", "What do you see?")
    elaborate = params.get("elaborate", False)

    def _run():
        try:
            set_state(player, State.THINKING)
            if angle == "camera":
                image_bytes, mime = _capture_camera()
            else:
                image_bytes, mime = _capture_screen()
            answer = _query_vision(image_bytes, question, mime, elaborate=elaborate)
            say(player, answer)
        except Exception as e:
            set_state(player, State.ERROR)
            say(player, f"I was unable to process the visual input, sir. {e}")

    threading.Thread(target=_run, daemon=True).start()
