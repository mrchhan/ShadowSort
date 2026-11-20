"""Download ShadowSort's offline models so the app works without internet (and can ship them in the installer).

    python download_model.py          -> face models (38 MB) + AI content model (~600 MB, needs requirements-ai.txt)
    python download_model.py faces    -> face models only
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from shadowsort import faces  # noqa: E402

target = os.path.join(HERE, "models", "faces")
faces.ensure_models(target)
print(f"Face models ready in {target}")

if "faces" not in sys.argv[1:]:
    from transformers import CLIPModel, CLIPProcessor

    MODEL_ID = "openai/clip-vit-base-patch32"
    clip = os.path.join(HERE, "models", "clip")
    os.makedirs(clip, exist_ok=True)
    print(f"Downloading {MODEL_ID} -> {clip}")
    CLIPModel.from_pretrained(MODEL_ID).save_pretrained(clip)
    CLIPProcessor.from_pretrained(MODEL_ID).save_pretrained(clip)
    print("Done.")
