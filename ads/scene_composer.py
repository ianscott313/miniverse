from __future__ import annotations
import base64
import logging
import os
from pathlib import Path

from openai import OpenAI
from PIL import Image

from ads.models import AdBrief, Scene

logger = logging.getLogger(__name__)

_openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY", "dummy-key-for-tests"))

_BG_SIZE = (1920, 1080)
_PRODUCT_MAX_HEIGHT_RATIO = 0.55


def compose(scene: Scene, brief: AdBrief, product_image: Path, output_dir: Path) -> Path:
    """
    Generate a background with GPT-image-1, composite the product on top.
    Returns path to the final composited image.
    """
    logger.info("Composing scene %d", scene.index)
    bg_path = _generate_background(scene, brief, output_dir)
    product_no_bg = _remove_background(product_image, output_dir)
    output_path = output_dir / f"scene_{scene.index:02d}_composed.png"
    _composite(bg_path, product_no_bg, output_path)
    return output_path


def _generate_background(scene: Scene, brief: AdBrief, output_dir: Path) -> Path:
    """Call GPT-image-1 (gpt-image-2 in marketing terms) to generate background."""
    full_prompt = (
        f"{scene.visual_prompt}. "
        f"Visual style: {brief.visual_style}. "
        f"Color palette: {', '.join(brief.color_palette)}. "
        f"Cinematic, photorealistic, 16:9. "
        f"Do NOT include any product or text."
    )
    logger.info("Generating background for scene %d", scene.index)
    response = _openai_client.images.generate(
        model="gpt-image-1",
        prompt=full_prompt,
        size="1792x1024",
        quality="high",
        n=1,
        response_format="b64_json",
    )
    image_data = base64.b64decode(response.data[0].b64_json)
    bg_path = output_dir / f"scene_{scene.index:02d}_bg.png"
    bg_path.write_bytes(image_data)
    return bg_path


def _remove_background(product_image: Path, output_dir: Path) -> Path:
    """Remove background from product photo using rembg."""
    from rembg import remove
    with open(product_image, "rb") as f:
        output_data = remove(f.read())
    out_path = output_dir / "product_nobg.png"
    out_path.write_bytes(output_data)
    return out_path


def _composite(bg_path: Path, product_path: Path, output_path: Path) -> None:
    """Paste the product (no-bg) onto the background, centered and scaled."""
    bg = Image.open(bg_path).convert("RGBA").resize(_BG_SIZE)
    product = Image.open(product_path).convert("RGBA")

    max_height = int(_BG_SIZE[1] * _PRODUCT_MAX_HEIGHT_RATIO)
    ratio = max_height / product.height
    new_w = int(product.width * ratio)
    product = product.resize((new_w, max_height), Image.LANCZOS)

    x = (_BG_SIZE[0] - new_w) // 2
    y = _BG_SIZE[1] - max_height - int(_BG_SIZE[1] * 0.05)

    result = bg.copy()
    result.paste(product, (x, y), product)
    result.save(output_path, "PNG")
