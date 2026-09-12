from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://api.hedra.com/web-app/public"
DEFAULT_MODEL_ID = "26f0fc66-152b-40ab-abed-76c43df99bc8"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a tiny Hedra avatar MP4 from ARGO's portrait.")
    parser.add_argument("--image", default="frontend-v2/assets/cortana_portrait_smirky.png")
    parser.add_argument("--audio", default="test_synthetic.wav")
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--duration-ms", type=int, default=2000)
    parser.add_argument("--resolution", default="540p")
    parser.add_argument("--aspect-ratio", default="1:1")
    parser.add_argument("--output-dir", default="runtime/hedra")
    parser.add_argument("--timeout-sec", type=int, default=420)
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = (os.getenv("HEDRA_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("HEDRA_API_KEY is missing")

    image_path = _resolve_path(args.image)
    audio_path = _resolve_path(args.audio)
    if not image_path.exists():
        raise SystemExit(f"Image not found: {image_path}")
    if not audio_path.exists():
        raise SystemExit(f"Audio not found: {audio_path}")

    output_dir = _resolve_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    session.headers.update({"X-API-Key": api_key})

    image_id = create_and_upload_asset(session, image_path, "image")
    audio_id = create_and_upload_asset(session, audio_path, "audio")
    generation_id = create_generation(
        session,
        image_id=image_id,
        audio_id=audio_id,
        model_id=args.model_id,
        duration_ms=args.duration_ms,
        resolution=args.resolution,
        aspect_ratio=args.aspect_ratio,
    )
    print(f"generation_id={generation_id}")

    status = poll_generation(session, generation_id, timeout_sec=args.timeout_sec)
    asset_id = status.get("asset_id")
    asset_url = _extract_asset_url(status)
    if not asset_url and asset_id:
        asset_url = fetch_asset_url(session, asset_id)
    if not asset_url:
        raise SystemExit(f"Generation completed but no asset URL was found: {status}")

    output_path = output_dir / f"hedra_avatar_{generation_id}.mp4"
    download_file(session, asset_url, output_path)
    print(f"video={output_path}")
    return 0


def _resolve_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path


def create_and_upload_asset(session: requests.Session, path: Path, asset_type: str) -> str:
    created = _request_json(
        session,
        "POST",
        f"{BASE_URL}/assets",
        json={"name": path.name, "type": asset_type},
    )
    asset_id = created["id"]
    with path.open("rb") as handle:
        _request_json(
            session,
            "POST",
            f"{BASE_URL}/assets/{asset_id}/upload",
            files={"file": (path.name, handle)},
        )
    print(f"{asset_type}_asset_id={asset_id}")
    return asset_id


def create_generation(
    session: requests.Session,
    *,
    image_id: str,
    audio_id: str,
    model_id: str,
    duration_ms: int,
    resolution: str,
    aspect_ratio: str,
) -> str:
    payload = {
        "type": "video",
        "ai_model_id": model_id,
        "start_keyframe_id": image_id,
        "audio_id": audio_id,
        "generated_video_inputs": {
            "text_prompt": "A friendly AI assistant speaking directly to camera.",
            "resolution": resolution,
            "aspect_ratio": aspect_ratio,
            "duration_ms": duration_ms,
        },
    }
    data = _request_json(session, "POST", f"{BASE_URL}/generations", json=payload)
    return data.get("id") or data.get("generation_id") or data["batch_results"][0]["id"]


def poll_generation(session: requests.Session, generation_id: str, *, timeout_sec: int) -> dict[str, Any]:
    deadline = time.time() + timeout_sec
    last_status = ""
    while time.time() < deadline:
        data = _request_json(session, "GET", f"{BASE_URL}/generations/{generation_id}/status")
        status = data.get("status", "")
        progress = data.get("progress", 0)
        if status != last_status:
            print(f"status={status} progress={progress}")
            last_status = status
        if status == "complete":
            return data
        if status == "error":
            raise SystemExit(f"Hedra generation failed: {data}")
        time.sleep(8)
    raise SystemExit(f"Hedra generation timed out after {timeout_sec}s")


def fetch_asset_url(session: requests.Session, asset_id: str) -> str:
    data = _request_json(session, "GET", f"{BASE_URL}/assets", params={"type": "video"})
    for item in data if isinstance(data, list) else []:
        if item.get("id") == asset_id:
            return _extract_asset_url(item)
    return ""


def _extract_asset_url(data: dict[str, Any]) -> str:
    asset = data.get("asset")
    if isinstance(asset, dict):
        url = asset.get("url")
        if isinstance(url, str):
            return url
    for key in ("url", "asset_url", "download_url"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


def download_file(session: requests.Session, url: str, output_path: Path) -> None:
    with session.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with output_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)


def _request_json(session: requests.Session, method: str, url: str, **kwargs: Any) -> Any:
    response = session.request(method, url, timeout=60, **kwargs)
    try:
        data = response.json()
    except Exception:
        data = response.text
    if not response.ok:
        raise SystemExit(f"{method} {url} failed ({response.status_code}): {data}")
    return data


if __name__ == "__main__":
    raise SystemExit(main())
