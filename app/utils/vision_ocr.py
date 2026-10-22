from __future__ import annotations

import io
import os
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

        # 1. Primary: Try OpenAI gpt-4o-mini vision if OPENAI_API_KEY is available
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                import base64
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)
                b64_img = base64.b64encode(image_bytes).decode("utf-8")
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": prompt},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"},
                                },
                            ],
                        }
                    ],
                    max_tokens=1000,
                    temperature=0,
                )
                extracted = response.choices[0].message.content.strip()
                if extracted:
                    return extracted
            except Exception as oai_err:
                logger.warning("OpenAI vision OCR fallback (%s) — trying Gemini if configured", oai_err)

        # 2. Fallback: Gemini Vision if configured
        if os.getenv("GEMINI_AI_API_KEY") and genai is not None:
            configure_gemini()
            model    = genai.GenerativeModel(GEMINI_VISION_MODEL)
            response = gemini_breaker.call(model.generate_content, [prompt, img])

            if response is None:
                logger.warning(
                    "Gemini Vision unavailable (circuit breaker/timeout) — returning empty",
                    extra={"circuit_state": gemini_breaker.state},
                )
                return ""

            if getattr(response, "text", None):
                return response.text.strip()

        return ""

    except Exception as exc:
        logger.error(
            "Gemini Vision OCR failed unexpectedly",
            extra={"error": str(exc)},
            exc_info=True,
        )
        return ""