"""씬별 AI 이미지를 fal.ai Flux로 생성한다."""
import os
import re
import subprocess
import requests
from pathlib import Path


_PROMPT_TEMPLATE = """\
Convert this news narration into a vivid photojournalistic image description.

Scene title: {title}
Narration: {narration}

Write 50-80 words describing what a news photographer would capture.
Requirements:
- Realistic, photojournalistic style
- No text, no graphics, no logos
- Suitable for 9:16 vertical smartphone format
- High quality, professional photography aesthetic

Return ONLY the visual description."""


def _make_image_prompt(scene_title: str, narration: str) -> str:
    prompt = _PROMPT_TEMPLATE.format(title=scene_title, narration=narration[:300])
    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions",
             "--model", "claude-haiku-4-5-20251001"],
            input=prompt, capture_output=True, text=True, timeout=30,
        )
        text = result.stdout.strip()
        return text if text else narration[:100]
    except Exception:
        return narration[:100]


def generate_scene_image(
    scene_title: str,
    narration: str,
    output_path: str,
) -> bool:
    """
    fal.ai Flux Dev로 씬 이미지를 생성하고 저장한다.
    성공 시 True, 실패 시 False 반환.
    """
    api_key = os.environ.get("FAL_API_KEY", "")
    if not api_key:
        return False

    visual_desc = _make_image_prompt(scene_title, narration)
    full_prompt = (
        f"{visual_desc}. "
        "Photojournalistic, high quality, professional news photography, "
        "sharp focus, natural lighting, realistic."
    )

    try:
        resp = requests.post(
            "https://fal.run/fal-ai/flux-2",   # Flux 2
            headers={
                "Authorization": f"Key {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": full_prompt,
                "image_size": {"width": 1000, "height": 560},  # 썸네일 공간에 맞춤
                "num_inference_steps": 25,
                "guidance_scale": 3.5,
                "num_images": 1,
                "enable_safety_checker": True,
            },
            timeout=120,
        )
        resp.raise_for_status()
        img_url = resp.json()["images"][0]["url"]

        img_data = requests.get(img_url, timeout=30).content
        Path(output_path).write_bytes(img_data)
        return True

    except Exception as e:
        return False
