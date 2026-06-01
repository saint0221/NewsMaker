"""뉴스 URL QR 코드를 ffmpeg 필터로 비디오에 합성한다."""
import subprocess
import tempfile
from pathlib import Path

import qrcode
from PIL import Image


def _make_qr_png(url: str, size: int, output_path: str):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=2,
    )
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="white", back_color="black").convert("RGB")
    img = img.resize((size, size), Image.LANCZOS)
    img.save(output_path)


def create_black_video_with_qr(
    output_path: str,
    duration: float,
    url: str,
    width: int = 1080,
    height: int = 1920,
    qr_size: int = 160,       # 코너 소형 QR
    corner_padding: int = 40,
):
    """검은 배경 + 우하단 소형 QR 코드 MP4를 생성한다."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        qr_path = f.name

    _make_qr_png(url, qr_size, qr_path)

    x = width - qr_size - corner_padding
    y = height - qr_size - corner_padding

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=30",
        "-loop", "1", "-i", qr_path,
        "-filter_complex",
        f"[1:v]format=rgba,colorchannelmixer=aa=0.75[qr];[0:v][qr]overlay={x}:{y}",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", output_path,
    ], check=True, capture_output=True)

    Path(qr_path).unlink(missing_ok=True)


def create_qr_scene_video(
    output_path: str,
    duration: float,
    url: str,
    width: int = 1080,
    height: int = 1920,
    qr_size: int = 500,       # CTA 씬 대형 QR
):
    """마지막 씬용 — 검은 배경 + 중앙 대형 QR 코드."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        qr_path = f.name

    _make_qr_png(url, qr_size, qr_path)

    x = (width - qr_size) // 2
    y = (height - qr_size) // 2 + 80   # 살짝 아래

    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"color=c=black:s={width}x{height}:r=30",
        "-loop", "1", "-i", qr_path,
        "-filter_complex",
        f"[0:v][1:v]overlay={x}:{y}",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-an", output_path,
    ], check=True, capture_output=True)

    Path(qr_path).unlink(missing_ok=True)
