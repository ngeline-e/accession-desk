"""
The Accession Desk - turns any ordinary object into a work of contemporary art.

Flow (two requests so the label can appear while the image is still developing):

  POST /api/label    {"object": "..."}         -> {"label": {...}}
  POST /api/install  {"label": {...}}          -> {"image_prompt": "...", "image": "data:image/png;base64,..."}

The image prompt is written from the label only (see prompts.py).
"""

import base64
import json
import os
import re

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import prompts

load_dotenv()  # reads .env locally; on Render the variables come from the dashboard

app = Flask(__name__)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if OPENAI_API_KEY in ("", "your-api-key-here"):  # placeholder from .env-example
    OPENAI_API_KEY = None
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-4.1")
IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-1")
IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "medium")  # low | medium | high
# Mock mode lets you test the whole interface without spending credits.
MOCK_MODE = os.getenv("MOCK_MODE", "0") == "1" or not OPENAI_API_KEY

MAX_OBJECT_CHARS = 300
MIN_WORDS, MAX_WORDS = 80, 120

client = None
if not MOCK_MODE:
    from openai import OpenAI

    client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def word_count(text: str) -> int:
    return len(re.findall(r"\b[\w'’-]+\b", text))


def clean_object(raw) -> str:
    text = (raw or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:MAX_OBJECT_CHARS]


def generate_label(object_description: str) -> dict:
    """Curator call: description -> structured wall label (with one length retry)."""
    messages = [
        {"role": "developer", "content": prompts.LABEL_SYSTEM_PROMPT},
        {"role": "user", "content": f"Object submitted by a visitor: {object_description}"},
    ]
    label = None
    for _attempt in range(2):
        response = client.responses.create(
            model=TEXT_MODEL,
            input=messages,
            temperature=1.0,
            text={
                "format": {
                    "type": "json_schema",
                    "name": "wall_label",
                    "schema": prompts.LABEL_SCHEMA,
                    "strict": True,
                }
            },
        )
        label = json.loads(response.output_text)
        n = word_count(label["extended_label"])
        if MIN_WORDS <= n <= MAX_WORDS:
            break
        # Ask the curator to fix the length, keeping everything else.
        messages += [
            {"role": "assistant", "content": response.output_text},
            {
                "role": "user",
                "content": (
                    f"The extended label has {n} words. Rewrite it to between "
                    f"{MIN_WORDS} and {MAX_WORDS} words. Keep every other field and all rules."
                ),
            },
        ]
    return label


def generate_image_prompt(label: dict) -> str:
    """Installer call: label -> image prompt. Falls back to a template on failure."""
    try:
        response = client.responses.create(
            model=TEXT_MODEL,
            input=[
                {"role": "developer", "content": prompts.IMAGE_DIRECTOR_PROMPT},
                {"role": "user", "content": prompts.label_to_brief(label)},
            ],
            temperature=0.8,
        )
        text = response.output_text.strip()
        if text:
            return text
    except Exception as exc:  # noqa: BLE001
        app.logger.warning("Image director failed, using fallback: %s", exc)
    return prompts.fallback_image_prompt(label)


def generate_image(image_prompt: str) -> str:
    """Images API call. Returns a data URL the <img> tag can display directly."""
    params = {"model": IMAGE_MODEL, "prompt": image_prompt, "size": "1024x1024", "n": 1}
    if IMAGE_MODEL.startswith("dall-e"):
        # DALL-E models use different quality values and return URLs unless asked.
        params["response_format"] = "b64_json"
    else:
        params["quality"] = IMAGE_QUALITY
    result = client.images.generate(**params)
    image = result.data[0]
    if getattr(image, "b64_json", None):
        return f"data:image/png;base64,{image.b64_json}"
    return image.url  # some models return a URL instead of base64


# ---------------------------------------------------------------------------
# Mock responses (MOCK_MODE=1 or no API key)
# ---------------------------------------------------------------------------

def mock_label(object_description: str) -> dict:
    name = object_description[:40] or "an object"
    return {
        "artist_name": "Ondine Malkowicz-Ferreira",
        "artist_bio": "b. 1991, lives and works between Verdun and the cloud",
        "title": f"Holding Pattern ({name})",
        "year": "2026",
        "medium": "Found object, lint, residual intention",
        "dimensions": "Dimensions variable",
        "provenance": "Found at the bottom of a tote bag, 2026; private collection of a visitor; acquired by the museum after a brief hesitation",
        "credit_line": "Gift of the visitor's pocket",
        "theorist": "Halvard Quenneville",
        "theorist_book": "The Pocket as Archive",
        "extended_label": (
            "Through a quasi-forensic attention to the overlooked, this work "
            "simultaneously and insistently interrogates the infrastructure of "
            "carrying, foregrounding the potentiality of the residual against the "
            f"hyper-visibility of exhibition. It is {name}. As invented theorist "
            "Halvard Quenneville argues in The Pocket as Archive, the post-functional "
            "object destabilizes the distinction between possession and accompaniment. "
            "Here, the everyday becomes a para-institutional space in which use "
            "problematizes value; the work renders visible neither utility nor its "
            "absence, but an ongoing, radically and deliberately unresolved becoming."
        ),
    }


def mock_image() -> str:
    svg = (
        "<svg xmlns='http://www.w3.org/2000/svg' width='1024' height='1024'>"
        "<rect width='1024' height='1024' fill='#ecebe7'/>"
        "<rect y='700' width='1024' height='324' fill='#b9b6af'/>"
        "<rect x='432' y='520' width='160' height='240' fill='#fafaf8'/>"
        "<circle cx='512' cy='490' r='34' fill='#3a3a3a'/>"
        "<text x='512' y='940' font-family='Arial' font-size='28' text-anchor='middle' fill='#555'>"
        "MOCK MODE - no image generated</text></svg>"
    )
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", mock_mode=MOCK_MODE)


@app.post("/api/label")
def api_label():
    data = request.get_json(silent=True) or {}
    obj = clean_object(data.get("object"))
    if not obj:
        return jsonify(error="Describe an object first."), 400
    try:
        label = mock_label(obj) if MOCK_MODE else generate_label(obj)
        label["word_count"] = word_count(label["extended_label"])
        return jsonify(label=label)
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Label generation failed")
        return jsonify(error=f"The curator is unavailable: {exc}"), 502


@app.post("/api/install")
def api_install():
    data = request.get_json(silent=True) or {}
    label = data.get("label")
    required = prompts.LABEL_SCHEMA["required"]
    if not isinstance(label, dict) or not all(isinstance(label.get(k), str) for k in required):
        return jsonify(error="A complete wall label is required."), 400
    # Only keep known fields and cap their length before they reach the model.
    label = {k: label[k][:1500] for k in required}
    try:
        if MOCK_MODE:
            image_prompt = prompts.fallback_image_prompt(label)
            image = mock_image()
        else:
            image_prompt = generate_image_prompt(label)
            image = generate_image(image_prompt)
        return jsonify(image_prompt=image_prompt, image=image)
    except Exception as exc:  # noqa: BLE001
        app.logger.exception("Image generation failed")
        return jsonify(error=f"The installation crew is on strike: {exc}"), 502


@app.get("/healthz")
def healthz():
    return jsonify(ok=True, mock_mode=MOCK_MODE)


if __name__ == "__main__":
    app.run(debug=True)
