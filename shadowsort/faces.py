"""Face recognition: find every face, group the same person across photos, remember names.

Runs fully offline with OpenCV's YuNet (face detector) and SFace (face recogniser).
The two model files (~38 MB) download once on first use, or ship in ./models/faces.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Set

import numpy as np
from PIL import Image, ImageOps

_ZOO = "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models"
MODELS = {
    "detector": ("face_detection_yunet_2023mar.onnx", f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
                 "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    "recognizer": ("face_recognition_sface_2021dec.onnx",
                   f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
                   "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79"),
}

MATCH = 0.53         # cosine similarity to join a person (tuned on real event photos: same person >= 0.6,
                     # different people up to ~0.46, even look-alike relatives)
MERGE = 0.57         # merge two groups whose average faces are this similar...
MERGE_PAIRS = 0.65   # ...or whose closest faces are this similar (and average >= MERGE_FLOOR)
MERGE_FLOOR = 0.47
SUGGEST = 0.56       # below the merge bar but close: ask the user "same person?"
SUGGEST_PAIRS = 0.62
KNOWN = 0.58         # recognise someone you named in an earlier run
MIN_FACE_PX = 34     # ignore tiny background faces
MIN_SCORE = 0.82     # detector confidence
MIN_SHARP = 18.0     # skip out-of-focus background faces (Laplacian variance of the face at 96 px)
CROP = 112           # face thumbnail size for the UI
PRESENT_SCORE = 0.5  # faces this confident count as "someone else is in the photo", even if too small to recognise
MAIN_FACE = 0.35     # a face counts as a "main" person in a photo if it is at least this big vs the largest face

SOLO, SMALL, GROUP = "Solo", "Small Group", "Group"
KINDS = (SOLO, SMALL, GROUP)
GROUP_SIZE = 5       # this many main people or more = a big group photo


def available() -> bool:
    try:
        import cv2
        return hasattr(cv2, "FaceDetectorYN") and hasattr(cv2, "FaceRecognizerSF")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------
def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir() -> str:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    d = os.path.join(base, "Shadow Creative Studio", "ShadowSort")
    old = os.path.join(base, "AIShadow", "ShadowSort")
    if not os.path.isdir(d) and os.path.isdir(old):  # keep names/models from earlier versions
        try:
            import shutil
            shutil.copytree(old, d)
        except OSError:
            pass
    os.makedirs(d, exist_ok=True)
    return d


def models_dir() -> str:
    bundled = os.path.join(_app_dir(), "models", "faces")
    if all(os.path.exists(os.path.join(bundled, m[0])) for m in MODELS.values()):
        return bundled
    d = os.path.join(data_dir(), "models", "faces")
    os.makedirs(d, exist_ok=True)
    return d


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure_models(target: Optional[str] = None, log: Callable[[str], None] = print) -> Dict[str, str]:
    d = target or models_dir()
    os.makedirs(d, exist_ok=True)
    paths = {}
    for key, (name, url, sha) in MODELS.items():
        path = os.path.join(d, name)
        if not (os.path.exists(path) and _sha256(path) == sha):
            log(f"Downloading face model {name} (one time)…")
            tmp = path + ".part"
            urllib.request.urlretrieve(url, tmp)
            if _sha256(tmp) != sha:
                os.remove(tmp)
                raise RuntimeError(f"Downloaded {name} is corrupt — please try again.")
            os.replace(tmp, path)
        paths[key] = path
    return paths


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
@dataclass
class Face:
    path: str
    box: tuple            # x, y, w, h as fractions of the image
    score: float
    size: float           # face width in pixels (analysis scale)
    emb: np.ndarray
    person: int = -1
    scene: tuple = ()     # sizes of every face found in this photo (incl. veiled / distant / soft ones)

    @property
    def quality(self):
        return self.size * self.score


@dataclass
class Person:
    pid: int
    name: str
    default_name: str
    faces: List[int] = field(default_factory=list)
    photos: Set[str] = field(default_factory=set)
    centroid: Optional[np.ndarray] = None
    known: bool = False
    hidden: bool = False
    crops: List[bytes] = field(default_factory=list)   # RGB888 CROP x CROP

    @property
    def renamed(self):
        return self.name.strip() and self.name.strip() != self.default_name


# ---------------------------------------------------------------------------
# detection + embeddings
# ---------------------------------------------------------------------------
def _load_bgr(path: str, max_side: int = 1280):
    with Image.open(path) as im:
        try:
            im.draft("RGB", (max_side, max_side))
        except Exception:
            pass
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((max_side, max_side))
        arr = np.asarray(im)[:, :, ::-1].copy()
    return arr


class FaceEngine:
    def __init__(self, log: Callable[[str], None] = print):
        self.paths = ensure_models(log=log)
        self._tls = threading.local()

    def _models(self):
        import cv2
        if not hasattr(self._tls, "det"):
            self._tls.det = cv2.FaceDetectorYN.create(self.paths["detector"], "", (320, 320), MIN_SCORE, 0.3, 5000)
            self._tls.rec = cv2.FaceRecognizerSF.create(self.paths["recognizer"], "")
        return self._tls.det, self._tls.rec

    def faces_in(self, path: str) -> List[Face]:
        import cv2
        try:
            img = _load_bgr(path)
        except Exception:
            return []
        h, w = img.shape[:2]
        det, rec = self._models()
        det.setInputSize((w, h))
        det.setScoreThreshold(PRESENT_SCORE)
        _, found = det.detect(img)
        out = []
        if found is None:
            return out
        scene = tuple(float(f[2]) for f in found if float(f[14]) >= PRESENT_SCORE)
        for f in found:
            x, y, fw, fh, score = float(f[0]), float(f[1]), float(f[2]), float(f[3]), float(f[14])
            if score < MIN_SCORE or fw < MIN_FACE_PX:
                continue
            x0, y0 = max(0, int(x)), max(0, int(y))
            patch = img[y0:int(y + fh), x0:int(x + fw)]
            if patch.size == 0:
                continue
            g = cv2.resize(cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY), (96, 96))
            if cv2.Laplacian(g, cv2.CV_64F).var() < MIN_SHARP:
                continue
            aligned = rec.alignCrop(img, f)
            e = rec.feature(aligned).flatten().astype(np.float32)
            e /= np.linalg.norm(e) + 1e-9
            out.append(Face(path, (x / w, y / h, fw / w, fh / h), score, fw, e, scene=scene))
        return out


# ---------------------------------------------------------------------------
# grouping
# ---------------------------------------------------------------------------
def _norm(v):
    return v / (np.linalg.norm(v) + 1e-9)


def cluster(faces: List[Face]) -> List[List[int]]:
    """Greedy centroid clustering, best-quality faces first. Two faces in the same photo are
    never the same person."""
    order = sorted(range(len(faces)), key=lambda i: -faces[i].quality)
    sums: List[np.ndarray] = []
    members: List[List[int]] = []
    photos: List[Set[str]] = []
    for i in order:
        f = faces[i]
        placed = False
        if sums:
            C = np.stack([_norm(s) for s in sums])
            sims = C @ f.emb
            for k in np.argsort(-sims):
                if sims[k] < MATCH:
                    break
                if f.path in photos[k]:
                    continue
                sums[k] = sums[k] + f.emb
                members[k].append(i)
                photos[k].add(f.path)
                placed = True
                break
        if not placed:
            sums.append(f.emb.copy())
            members.append([i])
            photos.append({f.path})
    return merge_split(faces, members)


def _top_faces(faces, idx, k=40):
    return sorted(idx, key=lambda i: -faces[i].quality)[:k]


def link_scores(faces: List[Face], A: List[int], B: List[int]):
    """(centroid similarity, mean of the 3 closest face pairs)."""
    ea = np.stack([faces[i].emb for i in _top_faces(faces, A)])
    eb = np.stack([faces[i].emb for i in _top_faces(faces, B)])
    cs = float(_norm(ea.sum(0)) @ _norm(eb.sum(0)))
    S = (ea @ eb.T).ravel()
    k = min(3, S.size)
    ks = float(np.sort(S)[-k:].mean())
    return cs, ks


def _same_enough(cs, ks):
    return cs >= MERGE or (ks >= MERGE_PAIRS and cs >= MERGE_FLOOR)


def merge_split(faces: List[Face], members: List[List[int]]) -> List[List[int]]:
    """Join groups that are really one person (makeup, lighting, glasses, age...).
    Repeats until nothing more can be joined."""
    members = [list(m) for m in members]
    photos = [{faces[i].path for i in m} for m in members]
    while len(members) > 1:
        best, best_v = None, 0.0
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                shared = len(photos[a] & photos[b])
                small = min(len(photos[a]), len(photos[b]))
                if shared and (shared > max(1, 0.1 * small) or shared >= small):
                    continue  # truly seen together in several photos -> two different people
                cs, ks = link_scores(faces, members[a], members[b])
                if _same_enough(cs, ks):
                    v = cs + ks
                    if v > best_v:
                        best, best_v = (a, b), v
        if not best:
            break
        a, b = best
        members[a] += members[b]
        del members[b], photos[b]
        # one person can't be twice in the same photo: keep the closer face, set the other aside
        c = _norm(np.sum([faces[i].emb for i in members[a]], axis=0))
        by_photo: Dict[str, List[int]] = {}
        for i in members[a]:
            by_photo.setdefault(faces[i].path, []).append(i)
        kept, aside = [], []
        for idx in by_photo.values():
            idx.sort(key=lambda i: -float(faces[i].emb @ c))
            kept.append(idx[0])
            aside += idx[1:]
        members[a] = kept
        photos[a] = {faces[i].path for i in kept}
        for i in aside:
            members.append([i])
            photos.append({faces[i].path})
    return members


def suggest_pairs(people: List["Person"], faces: List[Face], limit: int = 12, dismissed=()):
    """People that might be the same person - shown to the user to confirm with one click."""
    out = []
    for i in range(len(people)):
        for j in range(i + 1, len(people)):
            a, b = people[i], people[j]
            if (a.pid, b.pid) in dismissed or (b.pid, a.pid) in dismissed:
                continue
            if a.known and b.known and a.name != b.name:
                continue
            if len(a.photos & b.photos) > 1:
                continue
            cs, ks = link_scores(faces, a.faces, b.faces)
            if cs >= SUGGEST or ks >= SUGGEST_PAIRS:
                out.append((cs + ks, a, b))
    out.sort(key=lambda t: -t[0])
    return [(a, b) for _, a, b in out[:limit]]


# ---------------------------------------------------------------------------
# people you've named before
# ---------------------------------------------------------------------------
def _db_path():
    return os.path.join(data_dir(), "people.json")


def load_known() -> List[dict]:
    try:
        with open(_db_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        for p in data.get("people", []):
            p["samples"] = np.array(p["samples"], dtype=np.float32)
        return data.get("people", [])
    except Exception:
        return []


def save_known(people: List[Person], faces: List[Face]) -> int:
    """Remember the people the user named, so next time they're recognised automatically."""
    db = {p["name"]: p for p in load_known()}
    saved = 0
    for person in people:
        if person.hidden or not person.renamed:
            continue
        best = sorted(person.faces, key=lambda i: -faces[i].quality)[:12]
        new = np.stack([faces[i].emb for i in best])
        name = person.name.strip()
        if name in db:
            new = np.concatenate([db[name]["samples"], new])[-30:]
        db[name] = {"name": name, "samples": new}
        saved += 1
    out = {"version": 1, "people": [{"name": p["name"], "samples": np.asarray(p["samples"], dtype=float).round(5).tolist()}
                                    for p in db.values()]}
    tmp = _db_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(out, fh)
    os.replace(tmp, _db_path())
    return saved


def forget_all() -> bool:
    try:
        os.remove(_db_path())
        return True
    except OSError:
        return False


def forget_known(name: str) -> None:
    db = [p for p in load_known() if p["name"] != name]
    with open(_db_path(), "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "people": [{"name": p["name"], "samples": p["samples"].tolist()} for p in db]}, fh)


# ---------------------------------------------------------------------------
# full pipeline
# ---------------------------------------------------------------------------
def find_people(paths: List[str], min_photos: int = 2, workers: int = 4,
                progress: Optional[Callable[[int, int], None]] = None,
                cancelled: Callable[[], bool] = lambda: False,
                log: Callable[[str], None] = print):
    engine = FaceEngine(log=log)
    faces: List[Face] = []
    total = len(paths)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = [pool.submit(engine.faces_in, p) for p in paths]
        for i, f in enumerate(as_completed(futs), 1):
            if cancelled():
                pool.shutdown(cancel_futures=True)
                return [], [], 0
            faces.extend(f.result())
            if progress:
                progress(i, total)
    faces.sort(key=lambda f: (f.path, f.box))
    groups = cluster(faces)

    people: List[Person] = []
    unknown = 0
    for g in groups:
        photos = {faces[i].path for i in g}
        if len(photos) < min_photos:
            unknown += len(g)
            continue
        centroid = _norm(np.sum([faces[i].emb for i in g], axis=0))
        people.append(Person(0, "", "", list(g), photos, centroid))

    # recognise people named in earlier runs
    known = load_known()
    claimed: Dict[str, Person] = {}
    for person in people:
        best, best_sim = None, KNOWN
        for k in known:
            sim = float(np.max(k["samples"] @ person.centroid))
            if sim >= best_sim:
                best, best_sim = k["name"], sim
        if best:
            if best in claimed and not (claimed[best].photos & person.photos):  # same known person split -> merge
                other = claimed[best]
                other.faces += person.faces
                other.photos |= person.photos
                other.centroid = _norm(np.sum([faces[i].emb for i in other.faces], axis=0))
                person.faces = []
                continue
            if best in claimed:  # both in the same photo: can't be the same person, keep the closer one named
                continue
            person.name, person.known = best, True
            claimed[best] = person
    people = [p for p in people if p.faces]
    people.sort(key=lambda p: (not p.known, -len(p.photos)))
    n = 0
    for pid, person in enumerate(people):
        person.pid = pid
        if not person.known:
            n += 1
            person.default_name = person.name = f"Person {n}"
        else:
            person.default_name = person.name
        for i in person.faces:
            faces[i].person = pid
    for person in people:
        make_crops(person, faces)
    return people, faces, unknown


def make_crops(person: Person, faces: List[Face], count: int = 5) -> None:
    best = sorted(person.faces, key=lambda i: -faces[i].quality)[:count]
    person.crops = []
    for i in best:
        f = faces[i]
        try:
            with Image.open(f.path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                W, H = im.size
                x, y, w, h = f.box
                cx, cy, s = (x + w / 2) * W, (y + h / 2) * H, max(w * W, h * H) * 1.5
                box = (int(cx - s / 2), int(cy - s / 2), int(cx + s / 2), int(cy + s / 2))
                crop = im.crop(box).resize((CROP, CROP), Image.Resampling.LANCZOS)
                person.crops.append(crop.tobytes())
        except Exception:
            continue


def merge_people(people: List[Person], faces: List[Face], src: Person, dst: Person) -> None:
    dst.faces += src.faces
    dst.photos |= src.photos
    dst.centroid = _norm(np.sum([faces[i].emb for i in dst.faces], axis=0))
    for i in src.faces:
        faces[i].person = dst.pid
    people.remove(src)
    make_crops(dst, faces)


def split_faces(people: List[Person], faces: List[Face], person: Person, idx: List[int],
                new_person: bool = False) -> Optional[Person]:
    """Take faces out of a person: either drop them, or make them a new person."""
    idx = [i for i in idx if i in person.faces]
    if not idx:
        return None
    person.faces = [i for i in person.faces if i not in set(idx)]
    person.photos = {faces[i].path for i in person.faces}
    for i in idx:
        faces[i].person = -1
    if person.faces:
        person.centroid = _norm(np.sum([faces[i].emb for i in person.faces], axis=0))
        make_crops(person, faces)
    else:
        people.remove(person)
    if not new_person:
        return None
    pid = max([p.pid for p in people] + [-1]) + 1
    n = 1 + sum(1 for p in people if p.default_name.startswith("Person "))
    names = {p.name for p in people}
    while f"Person {n}" in names:
        n += 1
    newp = Person(pid, f"Person {n}", f"Person {n}", list(idx), {faces[i].path for i in idx},
                  _norm(np.sum([faces[i].emb for i in idx], axis=0)))
    for i in idx:
        faces[i].person = pid
    make_crops(newp, faces)
    people.insert(people.index(person) + 1 if person in people else len(people), newp)
    return newp


# ---------------------------------------------------------------------------
# sharing
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# solo / small group / group
# ---------------------------------------------------------------------------
def main_faces(faces: List[Face]) -> Dict[str, tuple]:
    """Per photo: (how many main people, size of the biggest face). Small faces far in the
    background don't count; veiled, side-on or distant faces that were too small to recognise do."""
    sizes: Dict[str, List[float]] = {}
    for f in faces:
        if f.scene:
            sizes[f.path] = list(f.scene)
        else:
            sizes.setdefault(f.path, [])
    for f in faces:
        if not f.scene:
            sizes[f.path].append(f.size)
    out = {}
    for path, sz in sizes.items():
        biggest = max(sz)
        out[path] = (sum(1 for x in sz if x >= MAIN_FACE * biggest), biggest)
    return out


def kind_for(count: int, group_size: int = GROUP_SIZE) -> str:
    if count <= 1:
        return SOLO
    return SMALL if count < group_size else GROUP


def person_photo_kinds(person: Person, faces: List[Face], mains: Dict[str, tuple],
                       group_size: int = GROUP_SIZE) -> Dict[str, str]:
    """photo path -> Solo / Small Group / Group, from this person's point of view."""
    out = {}
    for i in person.faces:
        f = faces[i]
        count, biggest = mains.get(f.path, (1, f.size))
        if f.size < MAIN_FACE * biggest:   # this person is only in the background: never "solo"
            count += 1
        out[f.path] = kind_for(max(count, 1), group_size)
    return out


def kind_counts(kinds: Dict[str, str]) -> Dict[str, int]:
    c = {k: 0 for k in KINDS}
    for v in kinds.values():
        c[v] += 1
    return c


def group_photos(faces: List[Face], mains: Dict[str, tuple], group_size: int = GROUP_SIZE) -> List[str]:
    return sorted(p for p, (count, _) in mains.items() if count >= group_size)


def together_photos(people: List[Person]) -> Set[str]:
    """Photos that contain every one of these people."""
    if not people:
        return set()
    out = set(people[0].photos)
    for p in people[1:]:
        out &= p.photos
    return out


# ---------------------------------------------------------------------------
# sharing
# ---------------------------------------------------------------------------
def _safe_name(name: str, fallback: str = "Photos") -> str:
    return "".join("_" if c in '<>:"/\\|?*' else c for c in name.strip()).strip(" .") or fallback


def _write_zip(path: str, items, locate, tick) -> None:
    """items: (original path, folder inside the zip or '')."""
    used = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        for src, sub in items:
            real = locate(src)
            tick()
            if not real or not os.path.exists(real):
                continue
            arc = os.path.basename(real)
            base, ext = os.path.splitext(arc)
            k = 2
            while (sub + "/" + arc).lower() in used:
                arc = f"{base} ({k}){ext}"
                k += 1
            used.add((sub + "/" + arc).lower())
            z.write(real, f"{sub}/{arc}" if sub else arc)


def _unique(path):
    base, ext = os.path.splitext(path)
    n = 2
    while os.path.exists(path):
        path = f"{base} ({n}){ext}"
        n += 1
    return path


def export_zips(people: List[Person], locate: Callable[[str], Optional[str]], target: str,
                progress: Optional[Callable[[int, int], None]] = None,
                faces: Optional[List[Face]] = None, kinds=KINDS, group_size: int = GROUP_SIZE,
                split: bool = True) -> List[str]:
    """One ZIP per person with only the chosen kinds (Solo / Small Group / Group), each in its own folder."""
    os.makedirs(target, exist_ok=True)
    mains = main_faces(faces) if faces is not None else None
    jobs = []
    for p in people:
        if p.hidden:
            continue
        if mains is not None:
            pk = person_photo_kinds(p, faces, mains, group_size)
            items = [(src, k if split else "") for src, k in sorted(pk.items()) if k in kinds]
        else:
            items = [(src, "") for src in sorted(p.photos)]
        if items:
            jobs.append((p, items))
    total = sum(len(it) for _, it in jobs)
    state = {"done": 0}

    def tick():
        state["done"] += 1
        if progress:
            progress(state["done"], total)

    made = []
    for person, items in jobs:
        path = _unique(os.path.join(target, f"{_safe_name(person.name, person.default_name)}.zip"))
        _write_zip(path, items, locate, tick)
        made.append(path)
    return made


def export_together_zip(people: List[Person], locate: Callable[[str], Optional[str]], target: str,
                        progress: Optional[Callable[[int, int], None]] = None) -> Optional[str]:
    photos = sorted(together_photos(people))
    if not photos:
        return None
    os.makedirs(target, exist_ok=True)
    name = " & ".join(_safe_name(p.name, p.default_name) for p in people)
    path = _unique(os.path.join(target, f"{name}.zip"))
    state = {"done": 0}

    def tick():
        state["done"] += 1
        if progress:
            progress(state["done"], len(photos))

    _write_zip(path, [(p, "") for p in photos], locate, tick)
    return path
