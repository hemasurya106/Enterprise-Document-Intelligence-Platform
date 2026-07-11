"""Multilingual OCR via Gemini Vision (multimodal)."""
from __future__ import annotations

import io

from PIL import Image
import google.generativeai as genai

from .logic_agent import configure_gemini

GEMINI_VISION_MODEL = "gemini-2.0-flash"


def extract_text_with_gemini_vision(image_bytes: bytes, tesseract_text: str = "") -> str:
    """
    Send an image to Gemini Vision for multilingual text extraction.

    Uses Tesseract's raw output (if any) as supplementary context, but
    Gemini should primarily read directly from the image since it
    handles non-Latin scripts (Tamil, Malayalam, Urdu, etc.) natively.
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
                f"{tesseract_text.strip()}"
            )

        prompt = (
            "Extract all visible text from this image exactly as written. "
            "Preserve the original language and script — do NOT translate.\n"
            "If supplementary Tesseract OCR text is provided below, treat it only as a "
            "possible hint; ignore it if it conflicts with what is visible in the image.\n"
            "Return ONLY the extracted text with no commentary, labels, or markdown."
            f"{hint_block}"
        )

        model = genai.GenerativeModel(GEMINI_VISION_MODEL)
        response = model.generate_content([prompt, img])

        if not response or not getattr(response, "text", None):
            return ""
        return response.text.strip()
    except Exception as e:
        print(f"Gemini Vision OCR failed: {e}")
        return ""
