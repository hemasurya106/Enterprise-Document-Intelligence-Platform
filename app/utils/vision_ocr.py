from __future__ import annotations

import io
import logging

from PIL import Image
import google.generativeai as genai

from .logic_agent import configure_gemini
from .gemini_circuit_breaker import gemini_breaker

logger = logging.getLogger("app.vision_ocr")

GEMINI_VISION_MODEL = "gemini-2.0-flash"


def extract_text_with_gemini_vision(image_bytes: bytes, tesseract_text: str = "") -> str:
    """
    Extract text from an image via Gemini Vision.

    Falls back to empty string if:
      - image_bytes is empty
      - Gemini API raises an exception
      - the call exceeds the circuit-breaker timeout (15 s)
      - the circuit breaker is OPEN (too many recent failures)
    """
    if not image_bytes:
        return ""

    try:
        configure_gemini()
        img = Image.open(io.BytesIO(image_bytes))

        hint_block = ""
        if tesseract_text and tesseract_text.strip():
            hint_block = (
                "\n\nOptional hint from Tesseract OCR (may be incomplete or wrong; "
                "trust the image over this hint):\n"
                + tesseract_text.strip()
            )

        prompt = (
            "Extract all visible text from this image exactly as written. "
            "Preserve the original language and script — do NOT translate.\n"
            "If supplementary Tesseract OCR text is provided below, treat it only "
            "as a possible hint; ignore it if it conflicts with what is visible in "
            "the image.\n"
            "Return ONLY the extracted text with no commentary, labels, or markdown."
            + hint_block
        )

        model    = genai.GenerativeModel(GEMINI_VISION_MODEL)
        response = gemini_breaker.call(model.generate_content, [prompt, img])

        if response is None:
            # Circuit breaker tripped or timeout — log already emitted by breaker
            logger.warning(
                "Gemini Vision unavailable (circuit breaker/timeout) — returning empty",
                extra={"circuit_state": gemini_breaker.state},
            )
            return ""

        if not getattr(response, "text", None):
            logger.warning("Gemini Vision returned empty response")
            return ""

        return response.text.strip()

    except Exception as exc:
        logger.error(
            "Gemini Vision OCR failed unexpectedly",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return ""