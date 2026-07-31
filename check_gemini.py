"""Temp diagnostic: is the Gemini path actually firing? (safe to delete)"""
import os
from app.config import settings  # triggers .env -> os.environ bridge

key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")

print("[1] KEY VISIBLE TO retrieval.py :", "YES" if key else "NO -- this is the bug")
if key:
    print("    key length:", len(key), "| prefix:", key[:6] + "..." + key[-3:])
print("[2] MODEL CONFIGURED           :", settings.GEMINI_MODEL)

if not key:
    raise SystemExit("STOP: no key in os.environ, Gemini can never fire.")

print("[3] LIVE API CALL...")
try:
    from google import genai
    client = genai.Client(api_key=key)
    r = client.models.generate_content(
        model=settings.GEMINI_MODEL,
        contents="Reply with exactly one word: WORKING",
    )
    print("    RESULT: GEMINI IS FIRING ->", repr((r.text or "").strip()))
except Exception as e:
    print("    RESULT: GEMINI FAILED ->", type(e).__name__)
    print("    detail:", str(e)[:600])
