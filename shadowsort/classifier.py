"""Content categories.

* AIClassifier  - offline CLIP model (needs `torch` + `transformers`, see requirements-ai.txt).
                  The model (~600 MB) downloads once on first use, or can be placed in
                  ./models/clip next to the app for fully offline installs.
* BasicClassifier - no AI: Screenshots / Camera Photos / Images, using metadata only.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Dict, List, Optional

from PIL import Image, ImageOps

from .analyzer import PhotoInfo

MODEL_ID = "openai/clip-vit-base-patch32"

# Folder name -> prompts describing it. Users can add their own names in the app.
DEFAULT_CATEGORIES: Dict[str, List[str]] = {
    "People": ["a photo of a person", "a photo of a group of people", "a portrait photo of a man or woman"],
    "Selfies": ["a selfie taken with a phone front camera", "a close-up selfie of a face"],
    "Kids & Family": ["a photo of children playing", "a family photo with kids"],
    "Pets & Animals": ["a photo of a cat", "a photo of a dog", "a photo of an animal", "a photo of a bird"],
    "Food & Drinks": ["a photo of food on a plate", "a photo of a meal", "a photo of a drink or dessert"],
    "Nature & Landscapes": ["a landscape photo of nature", "a photo of mountains, trees, sky or the sea", "a photo of flowers or plants"],
    "Cars & Vehicles": ["a photo of a car", "a photo of a motorbike", "a photo of a vehicle on a road"],
    "Buildings & Places": ["a photo of a building", "a photo of a city street", "a photo of a room interior"],
    "Documents & Receipts": ["a scanned document with text", "a photo of a receipt or invoice", "a photo of a page of paper with writing"],
    "Screenshots": ["a screenshot of a phone screen", "a screenshot of a computer screen", "a screenshot of a chat conversation"],
    "Events & Celebrations": ["a photo of a wedding", "a photo of a birthday party", "a photo of a celebration or festival"],
    "Products & Shopping": ["a product photo for an online shop", "a photo of clothes or shoes", "a photo of an electronic gadget"],
    "Memes & Graphics": ["a meme with text", "a digital illustration or graphic design", "a poster or flyer"],
}

OTHER = "Other"


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ai_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:
        return False


def _as_tensor(out):
    """transformers versions differ: features may come back as a tensor or a model output."""
    if hasattr(out, "norm"):
        return out
    for attr in ("image_embeds", "text_embeds", "pooler_output"):
        val = getattr(out, attr, None)
        if val is not None:
            return val
    return out[0]


class BasicClassifier:
    name = "Basic (no AI)"

    def classify(self, photos: List[PhotoInfo], progress: Optional[Callable[[int, int], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False) -> None:
        total = len(photos)
        for i, p in enumerate(photos, 1):
            if p.looks_like_screenshot:
                p.category = "Screenshots"
            elif p.camera:
                p.category = "Camera Photos"
            elif "whatsapp" in p.path.lower() or "-wa" in p.name.lower():
                p.category = "WhatsApp"
            else:
                p.category = "Images"
            if progress:
                progress(i, total)


class AIClassifier:
    name = "AI (CLIP, offline)"

    def __init__(self, categories: Optional[Dict[str, List[str]]] = None, min_confidence: float = 0.22,
                 log: Callable[[str], None] = print):
        self.categories = categories or DEFAULT_CATEGORIES
        self.min_confidence = min_confidence
        self.log = log
        self._model = None

    def _load(self):
        import torch
        from transformers import CLIPModel, CLIPProcessor

        local = os.path.join(_app_dir(), "models", "clip")
        source = local if os.path.isdir(local) else MODEL_ID
        self.log(f"Loading AI model ({'local' if source == local else 'download on first run'})…")
        self._model = CLIPModel.from_pretrained(source)
        self._proc = CLIPProcessor.from_pretrained(source)
        self._model.eval()
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._model.to(self._device)

        # one averaged text embedding per category
        names, embeds = [], []
        with torch.no_grad():
            for name, prompts in self.categories.items():
                prompts = prompts or [f"a photo of {name.lower()}"]
                t = self._proc(text=prompts, return_tensors="pt", padding=True).to(self._device)
                e = _as_tensor(self._model.get_text_features(**t))
                e = e / e.norm(dim=-1, keepdim=True)
                e = e.mean(dim=0)
                embeds.append(e / e.norm())
                names.append(name)
        self._names = names
        self._text = torch.stack(embeds)

    def classify(self, photos: List[PhotoInfo], progress: Optional[Callable[[int, int], None]] = None,
                 cancelled: Callable[[], bool] = lambda: False, batch_size: int = 16) -> None:
        import torch

        if self._model is None:
            self._load()
        total = len(photos)
        done = 0
        for start in range(0, total, batch_size):
            if cancelled():
                return
            batch = photos[start:start + batch_size]
            images, idx = [], []
            for i, p in enumerate(batch):
                if p.looks_like_screenshot and "Screenshots" in self.categories:
                    p.category = "Screenshots"
                    continue
                try:
                    with Image.open(p.path) as im:
                        try:
                            im.draft("RGB", (448, 448))
                        except Exception:
                            pass
                        im = ImageOps.exif_transpose(im).convert("RGB")
                        im.thumbnail((448, 448))
                        images.append(im.copy())
                        idx.append(i)
                except Exception:
                    batch[i].category = OTHER
            if images:
                with torch.no_grad():
                    inp = self._proc(images=images, return_tensors="pt").to(self._device)
                    feats = _as_tensor(self._model.get_image_features(**inp))
                    feats = feats / feats.norm(dim=-1, keepdim=True)
                    probs = (100.0 * feats @ self._text.T).softmax(dim=-1).cpu()
                for row, i in enumerate(idx):
                    conf, k = probs[row].max(dim=0)
                    p = batch[i]
                    p.category = self._names[int(k)] if float(conf) >= self.min_confidence else OTHER
                    p.extra["confidence"] = round(float(conf), 3)
            done += len(batch)
            if progress:
                progress(done, total)


def make_classifier(use_ai: bool, extra_categories: Optional[List[str]] = None,
                    log: Callable[[str], None] = print):
    if use_ai and ai_available():
        cats = dict(DEFAULT_CATEGORIES)
        for name in extra_categories or []:
            name = name.strip()
            if name and name not in cats:
                cats[name] = [f"a photo of {name.lower()}"]
        return AIClassifier(cats, log=log)
    if use_ai:
        log("AI pack not installed - using basic categories (Screenshots / Camera Photos / Images).")
    return BasicClassifier()
