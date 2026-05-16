"""
ads/main.py — Cinematic Ads pipeline entry point.

Usage:
    python -m ads --image product.jpg [--output output/] [--scenes 7]

Environment variables:
    OPENAI_API_KEY       — GPT-4o Vision + GPT-image-1 (gpt-image-2)
    ELEVENLABS_API_KEY   — voice synthesis
    HIGGSFIELD_API_KEY   — Seedance 2.0 animation
    PIXABAY_API_KEY      — royalty-free music (optional)
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ads.main")


def run(image_path: Path, output_dir: Path, num_scenes: int) -> Path:
    from ads.verifier import pre_flight, post_validate
    from ads.creative_director import analyze, run_wizard, generate_brief, present_and_confirm_brief
    from ads.storyboard import generate as generate_storyboard
    from ads.scene_composer import compose
    from ads.auditor import audit_image, audit_video
    from ads.animator import animate
    from ads.voice import synthesize_scene, synthesize_tagline
    from ads.music import fetch as fetch_music
    from ads.assembler import assemble
    from ads.models import SceneAsset

    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = output_dir / "assets"
    images_dir = assets_dir / "images"
    audio_dir = assets_dir / "audio"
    for d in [assets_dir, images_dir, audio_dir]:
        d.mkdir(parents=True, exist_ok=True)

    # 1. Pre-flight
    logger.info("Running pre-flight checks...")
    pre_flight(image_path)

    # 2. Analyze product
    analysis = analyze(image_path)

    # 3. Wizard
    answers = run_wizard(analysis)

    # 4. Generate + confirm brief
    brief = generate_brief(analysis, answers)
    brief = present_and_confirm_brief(brief)

    # 5. Storyboard
    logger.info("Generating storyboard...")
    scenes = generate_storyboard(brief, num_scenes)
    print(f"\n✓ Storyboard: {len(scenes)} scenes planned\n")

    # 6. Scene loop
    scene_assets: list[SceneAsset] = []
    for scene in scenes:
        print(f"\n── Scene {scene.index}/{len(scenes)}: {scene.narration_line}")

        # 6a. Compose image with audit loop (max 3 attempts)
        image_path_out = None
        for attempt in range(1, 4):
            image_path_out = compose(scene, brief, image_path, images_dir)
            audit = audit_image(image_path_out, scene, brief)
            if audit.passed:
                break
            logger.warning("Image audit failed (attempt %d): %s", attempt, audit.rejection_reason)
            if attempt == 3:
                print(f"  ⚠ Image could not pass audit after 3 attempts.")
                print(f"  Reason: {audit.rejection_reason}")

        print(f"  Image ready: {image_path_out}")
        input("  Press Enter to approve this image (or Ctrl+C to abort): ")

        # 6b. Animate with audit loop (max 2 attempts)
        video_path_out = None
        for attempt in range(1, 3):
            video_path_out = animate(image_path_out, scene, output_dir / "scenes")
            audit = audit_video(video_path_out, scene, brief)
            if audit.passed:
                break
            logger.warning("Video audit failed (attempt %d): %s", attempt, audit.rejection_reason)
            if attempt == 2:
                print(f"  ⚠ Video audit failed: {audit.rejection_reason}")

        # 6c. Synthesize scene voice
        audio_path_out = synthesize_scene(scene, brief, audio_dir)

        scene_assets.append(SceneAsset(
            scene=scene,
            image_path=image_path_out,
            video_path=video_path_out,
            audio_path=audio_path_out,
        ))
        print(f"  ✓ Scene {scene.index} complete")

    # 7. Tagline voice
    synthesize_tagline(brief, audio_dir)

    # 8. Music
    logger.info("Fetching music for mood: %s", brief.mood_music)
    music_path = fetch_music(brief.mood_music, assets_dir)

    # 9. Assemble
    logger.info("Assembling final ad...")
    ad_output = assemble(scene_assets, music_path, brief, output_dir)

    # 10. Post-validate
    post_validate(output_dir)

    print(f"\n{'='*60}")
    print(f"✓ Cinematic ad ready: {ad_output.final_video_path}")
    print(f"  Duration: {ad_output.duration_sec:.1f}s")
    print(f"  Tagline: {brief.tagline}")
    print(f"{'='*60}\n")

    return ad_output.final_video_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a cinematic product ad")
    parser.add_argument("--image", required=True, help="Path to product photo")
    parser.add_argument("--output", default="output", help="Output directory (default: output/)")
    parser.add_argument("--scenes", type=int, default=7, help="Number of scenes (default: 7)")
    args = parser.parse_args()

    try:
        run(
            image_path=Path(args.image),
            output_dir=Path(args.output),
            num_scenes=args.scenes,
        )
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(0)
    except Exception as exc:
        logger.exception("Pipeline failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
