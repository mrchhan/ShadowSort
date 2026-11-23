"""Scan -> analyse -> find duplicates/junk -> pick best -> categorise -> plan -> apply / undo."""

from __future__ import annotations

import csv
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, List, Optional

import numpy as np

from .analyzer import IMAGE_EXTENSIONS, PhotoInfo, analyze
from .classifier import make_classifier

DELETE_FOLDER = "_To Delete"
PEOPLE_FOLDER = "By Person"
GROUP_FOLDER = "Group Photos"
TOGETHER_FOLDER = "Together"
STATE_FOLDER = ".shadowsort"
MONTHS = ["01 - January", "02 - February", "03 - March", "04 - April", "05 - May", "06 - June",
          "07 - July", "08 - August", "09 - September", "10 - October", "11 - November", "12 - December"]

# Duplicate matching levels: (max pHash distance, max dHash distance)
MATCH_LEVELS = {
    "exact": None,            # byte-identical only
    "near": (6, 8),           # same photo resized / re-saved / WhatsApp-compressed
    "similar": (12, 16),      # burst shots / near-identical retakes
}


@dataclass
class Options:
    source: str
    output: str
    organize_by: str = "both"          # "category" | "date" | "both"
    match_level: str = "near"          # key of MATCH_LEVELS
    include_subfolders: bool = True
    use_ai: bool = True
    extra_categories: List[str] = field(default_factory=list)
    junk_blurry: bool = True
    junk_dark_blank: bool = True
    junk_tiny: bool = False
    blur_threshold: float = 20.0       # Laplacian variance on 512px image; lower = blurrier
    tiny_px: int = 300
    copy_instead_of_move: bool = False
    faces: bool = True                 # find people and make a folder per person
    min_person_photos: int = 2
    split_people: bool = True          # By Person/<name>/Solo | Small Group | Group
    group_size: int = 5                # main people in a photo for it to count as a big group
    group_folder: bool = True          # also a "Group Photos" folder with every big-group photo once
    workers: int = max(2, min(8, (os.cpu_count() or 4)))


@dataclass
class Action:
    src: str
    dst: str
    kind: str          # "keep" | "delete"
    reason: str        # e.g. "Best of duplicate group 3", "Duplicate of IMG_001.jpg", "Blurry"
    category: str = ""
    group: int = 0


@dataclass
class Plan:
    options: Options
    photos: List[PhotoInfo]
    actions: List[Action]
    groups: List[List[PhotoInfo]]       # duplicate groups (best first)
    skipped: List[str]                  # files that are not images
    people: list = field(default_factory=list)   # faces.Person
    faces: list = field(default_factory=list)    # faces.Face
    together: list = field(default_factory=list)  # lists of person names for Together/ folders
    unknown_faces: int = 0

    @property
    def stats(self) -> Dict[str, int]:
        keep = sum(a.kind == "keep" for a in self.actions)
        dup = sum(a.kind == "delete" and a.reason.startswith("Duplicate") for a in self.actions)
        junk = sum(a.kind == "delete" for a in self.actions) - dup
        cats = len({a.category for a in self.actions if a.kind == "keep"})
        return {"total": len(self.photos), "keep": keep, "duplicates": dup, "junk": junk,
                "categories": cats, "groups": len(self.groups)}


Progress = Callable[[str, int, int], None]


class Cancelled(Exception):
    pass


# ---------------------------------------------------------------------------
# scanning
# ---------------------------------------------------------------------------
def find_images(opts: Options):
    images, skipped = [], []
    out_abs = os.path.abspath(opts.output)
    for root, dirs, files in os.walk(opts.source):
        root_abs = os.path.abspath(root)
        # never re-scan our own output / delete / state folders
        dirs[:] = [d for d in dirs
                   if not (os.path.abspath(os.path.join(root, d)) + os.sep).startswith(out_abs + os.sep)
                   and d not in (DELETE_FOLDER, STATE_FOLDER)]
        if (root_abs + os.sep).startswith(out_abs + os.sep):
            continue
        for f in sorted(files):
            p = os.path.join(root, f)
            if os.path.splitext(f)[1].lower() in IMAGE_EXTENSIONS:
                images.append(p)
            elif not f.startswith("."):
                skipped.append(p)
        if not opts.include_subfolders:
            break
    return images, skipped


# ---------------------------------------------------------------------------
# quality score (used to pick the best photo in a duplicate group)
# ---------------------------------------------------------------------------
def _exposure_quality(p: PhotoInfo) -> float:
    # 1.0 at a mid brightness, falling off toward black/white; reward contrast
    b = 1.0 - min(1.0, abs(p.brightness - 125) / 125)
    c = min(1.0, p.contrast / 60)
    return 0.6 * b + 0.4 * c


def score_group(group: List[PhotoInfo]) -> None:
    max_px = max(p.width * p.height for p in group) or 1
    max_sharp = max(p.sharpness for p in group) or 1
    max_size = max(p.size_bytes for p in group) or 1
    for p in group:
        s = (0.40 * (p.sharpness / max_sharp)
             + 0.30 * ((p.width * p.height) / max_px)
             + 0.12 * _exposure_quality(p)
             + 0.08 * (p.size_bytes / max_size)
             + 0.06 * (1.0 if p.date_source == "exif" else 0.0)
             + 0.04 * (1.0 if p.camera else 0.0))
        if p.looks_like_copy:
            s -= 0.05
        p.score = round(s * 100, 1)


# ---------------------------------------------------------------------------
# duplicate grouping
# ---------------------------------------------------------------------------
class _DSU:
    def __init__(self, n):
        self.p = list(range(n))

    def find(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def _popcount64(arr: np.ndarray) -> np.ndarray:
    if hasattr(np, "bitwise_count"):
        return np.bitwise_count(arr)
    # fallback for numpy < 2.0
    arr = arr.copy()
    c = np.zeros(arr.shape, dtype=np.uint8)
    for _ in range(64):
        c += (arr & np.uint64(1)).astype(np.uint8)
        arr >>= np.uint64(1)
    return c


def find_duplicate_groups(photos: List[PhotoInfo], level: str) -> List[List[PhotoInfo]]:
    n = len(photos)
    dsu = _DSU(n)

    by_hash: Dict[str, int] = {}
    for i, p in enumerate(photos):
        if p.sha256 in by_hash:
            dsu.union(by_hash[p.sha256], i)
        else:
            by_hash[p.sha256] = i

    limits = MATCH_LEVELS.get(level)
    if limits and n > 1:
        max_p, max_d = limits
        ph = np.array([p.phash for p in photos], dtype=np.uint64)
        dh = np.array([p.dhash for p in photos], dtype=np.uint64)
        aspect = np.array([p.width / p.height if p.height else 1 for p in photos])
        # ignore near-blank images: their hashes are meaningless and would all match each other
        flat = np.array([p.contrast < 6 for p in photos])
        for i in range(n - 1):
            if flat[i]:
                continue
            dp = _popcount64(ph[i + 1:] ^ ph[i])
            dd = _popcount64(dh[i + 1:] ^ dh[i])
            ar = np.abs(aspect[i + 1:] - aspect[i]) / max(aspect[i], 1e-6)
            hits = np.nonzero((dp <= max_p) & (dd <= max_d) & (ar < 0.08) & ~flat[i + 1:])[0]
            for h in hits:
                dsu.union(i, i + 1 + int(h))

    buckets: Dict[int, List[PhotoInfo]] = {}
    for i, p in enumerate(photos):
        buckets.setdefault(dsu.find(i), []).append(p)

    groups = []
    for g in buckets.values():
        if len(g) > 1:
            score_group(g)
            g.sort(key=lambda x: (-x.score, x.looks_like_copy, len(x.name), x.name))
            groups.append(g)
    groups.sort(key=lambda g: g[0].path)
    return groups


# ---------------------------------------------------------------------------
# junk detection
# ---------------------------------------------------------------------------
def junk_reason(p: PhotoInfo, opts: Options) -> Optional[str]:
    if not p.ok:
        return "Unreadable or corrupt"
    if opts.junk_dark_blank:
        if p.contrast < 6:
            return "Blank (single colour)"
        if p.brightness < 18 and p.contrast < 20:
            return "Too dark"
        if p.brightness > 245 and p.contrast < 12:
            return "Overexposed / white"
    if opts.junk_tiny and max(p.width, p.height) < opts.tiny_px:
        return "Tiny image"
    if opts.junk_blurry and p.sharpness < opts.blur_threshold and not p.looks_like_screenshot:
        return "Blurry"
    return None


JUNK_SUBFOLDER = {
    "Unreadable or corrupt": "Unreadable",
    "Blank (single colour)": "Blank or Dark",
    "Too dark": "Blank or Dark",
    "Overexposed / white": "Blank or Dark",
    "Tiny image": "Tiny",
    "Blurry": "Blurry",
}


# ---------------------------------------------------------------------------
# plan
# ---------------------------------------------------------------------------
def _dest_dir(opts: Options, p: PhotoInfo) -> str:
    parts = [opts.output]
    if opts.organize_by in ("category", "both"):
        parts.append(_safe(p.category or "Other"))
    if opts.organize_by in ("date", "both"):
        dt = p.taken or datetime.now()
        parts += [str(dt.year), MONTHS[dt.month - 1]]
    return os.path.join(*parts)


def _safe(name: str) -> str:
    bad = '<>:"/\\|?*'
    name = "".join("_" if c in bad else c for c in name).strip(" .")
    return name or "Other"


def build_plan(opts: Options, progress: Optional[Progress] = None,
               cancelled: Callable[[], bool] = lambda: False,
               log: Callable[[str], None] = print,
               on_photo: Optional[Callable[[PhotoInfo], None]] = None) -> Plan:
    prog = progress or (lambda *a: None)
    opts.source = os.path.abspath(opts.source)
    opts.output = os.path.abspath(opts.output)

    prog("Finding photos", 0, 0)
    paths, skipped = find_images(opts)
    log(f"Found {len(paths)} images ({len(skipped)} other files left alone).")

    photos: List[PhotoInfo] = []
    with ThreadPoolExecutor(max_workers=opts.workers) as pool:
        futures = [pool.submit(analyze, p) for p in paths]
        for i, f in enumerate(as_completed(futures), 1):
            if cancelled():
                pool.shutdown(cancel_futures=True)
                raise Cancelled()
            info = f.result()
            photos.append(info)
            if on_photo:
                on_photo(info)
            prog("Analysing photos", i, len(paths))
    photos.sort(key=lambda p: p.path.lower())

    actions: List[Action] = []
    delete_root = os.path.join(opts.output, DELETE_FOLDER)

    # 1) junk
    junk = {}
    for p in photos:
        r = junk_reason(p, opts)
        if r:
            junk[p.path] = r

    # 2) duplicates among the remaining good photos
    prog("Finding duplicates", 0, 0)
    good = [p for p in photos if p.path not in junk]
    groups = find_duplicate_groups(good, opts.match_level)
    log(f"Duplicate groups: {len(groups)}")

    losers: Dict[str, str] = {}
    best_of: Dict[str, int] = {}
    for gi, g in enumerate(groups, 1):
        best_of[g[0].path] = gi
        for p in g[1:]:
            exact = p.sha256 == g[0].sha256
            losers[p.path] = (f"Duplicate of {g[0].name}" + ("" if exact else " (similar)"), gi)

    # 3) categorise the photos we keep
    keepers = [p for p in good if p.path not in losers]
    if opts.organize_by in ("category", "both"):
        clf = make_classifier(opts.use_ai, opts.extra_categories, log=log)
        log(f"Categories: {clf.name}")
        try:
            clf.classify(keepers, progress=lambda d, t: prog("Recognising content", d, t), cancelled=cancelled)
        except Exception as exc:  # e.g. no internet for the first model download
            log(f"AI model could not be loaded ({type(exc).__name__}). Using basic folders instead. "
                f"Connect to the internet once, or run download_model.py.")
            from .classifier import BasicClassifier
            BasicClassifier().classify(keepers)
        if cancelled():
            raise Cancelled()

    # 4) actions
    for p in photos:
        if p.path in junk:
            r = junk[p.path]
            actions.append(Action(p.path, os.path.join(delete_root, JUNK_SUBFOLDER[r], p.name), "delete", r))
        elif p.path in losers:
            reason, gi = losers[p.path]
            name = f"G{gi:03d}_{p.name}"
            actions.append(Action(p.path, os.path.join(delete_root, "Duplicates", name), "delete", reason, group=gi))
        else:
            gi = best_of.get(p.path, 0)
            reason = f"Best of duplicate group {gi}" if gi else "Unique"
            actions.append(Action(p.path, os.path.join(_dest_dir(opts, p), p.name), "keep", reason,
                                  category=p.category, group=gi))

    _resolve_name_clashes(actions)
    plan = Plan(opts, photos, actions, groups, skipped)

    # 5) people (face recognition) - photos stay in one place, each person gets links
    if opts.faces:
        from . import faces as F
        if not F.available():
            log("Face recognition needs OpenCV (pip install opencv-python-headless) - skipped.")
        else:
            try:
                prog("Finding faces", 0, len(keepers))
                plan.people, plan.faces, plan.unknown_faces = F.find_people(
                    [p.path for p in keepers], min_photos=opts.min_person_photos, workers=opts.workers,
                    progress=lambda d, t: prog("Finding faces", d, t), cancelled=cancelled, log=log, step=prog)
                if cancelled():
                    raise Cancelled()
                known = sum(p.known for p in plan.people)
                log(f"People found: {len(plan.people)} ({known} recognised from earlier runs), "
                    f"{plan.unknown_faces} faces seen only once.")
            except Cancelled:
                raise
            except Exception as exc:
                log(f"Face recognition skipped ({type(exc).__name__}: {exc}).")
    return plan


def person_link_actions(plan: Plan) -> List[Action]:
    """Links (not copies) pointing at each photo's organized location:
    By Person/<name>/[Solo|Small Group|Group]/, Group Photos/, Together/<A & B>/."""
    from . import faces as F
    opts = plan.options
    where = {a.src: a.dst for a in plan.actions if a.kind == "keep"}
    mains = F.main_faces(plan.faces) if plan.faces else {}
    out: List[Action] = []

    def add(folder, sources, reason, used=None):
        used = set() if used is None else used
        for src in sorted(sources):
            real = where.get(src)
            if not real:
                continue
            dst = os.path.join(folder, os.path.basename(real))
            base, ext = os.path.splitext(dst)
            n = 2
            while dst.lower() in used:
                dst = f"{base} ({n}){ext}"
                n += 1
            used.add(dst.lower())
            out.append(Action(real, dst, "link", reason))

    for person in plan.people:
        if person.hidden or not person.photos:
            continue
        name = _safe(person.name.strip() or person.default_name)
        folder = os.path.join(opts.output, PEOPLE_FOLDER, name)
        if opts.split_people and mains:
            kinds = F.person_photo_kinds(person, plan.faces, mains, opts.group_size)
            for kind in F.KINDS:
                add(os.path.join(folder, kind), [p for p, k in kinds.items() if k == kind],
                    f"{kind} photo of {person.name}")
        else:
            add(folder, person.photos, f"Photo of {person.name}")
    if opts.group_folder and mains:
        add(os.path.join(opts.output, GROUP_FOLDER), F.group_photos(plan.faces, mains, opts.group_size),
            "Group photo")
    for names in getattr(plan, "together", []):
        people = [p for p in plan.people if p.name in names]
        if len(people) >= 2:
            add(os.path.join(opts.output, PEOPLE_FOLDER, TOGETHER_FOLDER,
                             " & ".join(_safe(p.name) for p in people)),
                F.together_photos(people), "Together")
    return out


def make_links(plan: Plan, actions: List[Action], log_path: Optional[str] = None) -> int:
    """Create extra link folders after Organize (e.g. a new Together folder); recorded for Undo."""
    made = []
    for a in actions:
        if not os.path.exists(a.src):
            continue
        os.makedirs(os.path.dirname(a.dst), exist_ok=True)
        dst = a.dst
        base, ext = os.path.splitext(dst)
        n = 2
        while os.path.exists(dst):
            if os.path.exists(dst) and os.path.samefile(dst, a.src):
                break
            dst = f"{base} ({n}){ext}"
            n += 1
        if os.path.exists(dst):
            continue
        try:
            os.link(a.src, dst)
            kind = "link"
        except OSError:
            shutil.copy2(a.src, dst)
            kind = "copy"
        made.append({"link": dst, "kind": kind})
    log_path = log_path or latest_undo_log(plan.options.output)
    if log_path and made:
        with open(log_path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["moves"].extend(made)
        with open(log_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1)
    return len(made)


def _resolve_name_clashes(actions: List[Action]) -> None:
    used = set()
    for a in actions:
        dst = a.dst
        base, ext = os.path.splitext(dst)
        n = 2
        while dst.lower() in used or (os.path.exists(dst) and os.path.abspath(dst) != os.path.abspath(a.src)):
            dst = f"{base} ({n}){ext}"
            n += 1
        used.add(dst.lower())
        a.dst = dst


# ---------------------------------------------------------------------------
# apply / undo
# ---------------------------------------------------------------------------
def apply_plan(plan: Plan, progress: Optional[Progress] = None,
               cancelled: Callable[[], bool] = lambda: False) -> str:
    """Moves (or copies) files. Nothing is ever permanently deleted. Returns the undo-log path."""
    prog = progress or (lambda *a: None)
    opts = plan.options
    state = os.path.join(opts.output, STATE_FOLDER)
    os.makedirs(state, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = os.path.join(state, f"undo-{stamp}.json")
    done = []
    mode = "copy" if opts.copy_instead_of_move else "move"

    def save_log():
        with open(log_path, "w", encoding="utf-8") as fh:
            json.dump({"mode": mode, "created": stamp, "source": opts.source, "moves": done}, fh, indent=1)

    total = len(plan.actions)
    try:
        for i, a in enumerate(plan.actions, 1):
            if cancelled():
                break
            if os.path.abspath(a.src) == os.path.abspath(a.dst):
                continue
            os.makedirs(os.path.dirname(a.dst), exist_ok=True)
            dst = a.dst
            base, ext = os.path.splitext(dst)
            n = 2
            while os.path.exists(dst):  # never overwrite anything
                dst = f"{base} ({n}){ext}"
                n += 1
            if mode == "copy":
                shutil.copy2(a.src, dst)
            else:
                shutil.move(a.src, dst)
            a.dst = dst
            done.append({"src": a.src, "dst": dst})
            if i % 25 == 0:
                save_log()
            prog("Organising", i, total)
        # people folders: hard links (same file, no extra space); copies if links aren't possible
        links = [] if cancelled() else person_link_actions(plan)
        for i, a in enumerate(links, 1):
            if not os.path.exists(a.src):
                continue
            os.makedirs(os.path.dirname(a.dst), exist_ok=True)
            dst = a.dst
            base, ext = os.path.splitext(dst)
            n = 2
            while os.path.exists(dst):
                dst = f"{base} ({n}){ext}"
                n += 1
            try:
                os.link(a.src, dst)
                kind = "link"
            except OSError:
                shutil.copy2(a.src, dst)
                kind = "copy"
            done.append({"link": dst, "kind": kind})
            prog("Making people folders", i, len(links))
    finally:
        save_log()
        if mode == "move":
            _remove_empty_dirs(opts.source, keep_root=True, skip=opts.output)
        write_report(plan, os.path.join(opts.output, f"ShadowSort report {stamp}.csv"))
    return log_path


def _remove_empty_dirs(root: str, keep_root: bool = True, skip: str = "") -> None:
    skip = os.path.abspath(skip) if skip else ""
    for d, _, _ in os.walk(root, topdown=False):
        ad = os.path.abspath(d)
        if (keep_root and ad == os.path.abspath(root)) or (skip and (ad + os.sep).startswith(skip + os.sep)):
            continue
        try:
            if not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass


def write_report(plan: Plan, path: str) -> None:
    info = {p.path: p for p in plan.photos}
    with open(path, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["Action", "Reason", "Category", "Original file", "New location", "Date taken",
                    "Date source", "Width", "Height", "Sharpness", "Quality score", "Duplicate group"])
        for a in plan.actions:
            p = info.get(a.src)
            w.writerow(["Keep" if a.kind == "keep" else "To delete", a.reason, a.category, a.src, a.dst,
                        p.taken.strftime("%Y-%m-%d %H:%M") if p and p.taken else "",
                        p.date_source if p else "", p.width if p else "", p.height if p else "",
                        round(p.sharpness, 1) if p else "", p.score if p and a.group else "", a.group or ""])


def latest_undo_log(output: str) -> Optional[str]:
    state = os.path.join(output, STATE_FOLDER)
    if not os.path.isdir(state):
        return None
    logs = sorted(f for f in os.listdir(state) if f.startswith("undo-") and f.endswith(".json"))
    return os.path.join(state, logs[-1]) if logs else None


def undo(log_path: str, progress: Optional[Progress] = None) -> int:
    prog = progress or (lambda *a: None)
    with open(log_path, encoding="utf-8") as fh:
        data = json.load(fh)
    moves = data.get("moves", [])
    restored = 0
    for i, m in enumerate(reversed(moves), 1):
        if "link" in m:  # people-folder entry: just remove it
            try:
                os.remove(m["link"])
            except OSError:
                pass
            continue
        src, dst = m["src"], m["dst"]
        if not os.path.exists(dst):
            continue
        if data.get("mode") == "copy":
            os.remove(dst)
        else:
            os.makedirs(os.path.dirname(src), exist_ok=True)
            target = src
            base, ext = os.path.splitext(src)
            n = 2
            while os.path.exists(target):
                target = f"{base} (restored {n}){ext}"
                n += 1
            shutil.move(dst, target)
        restored += 1
        prog("Undoing", i, len(moves))
    # tidy up empty folders we created
    out = os.path.dirname(os.path.dirname(log_path))
    for root, dirs, files in os.walk(out, topdown=False):
        if STATE_FOLDER in root:
            continue
        try:
            if not os.listdir(root) and os.path.abspath(root) != os.path.abspath(out):
                os.rmdir(root)
        except OSError:
            pass
    os.rename(log_path, log_path.replace(".json", ".undone.json"))
    return restored


def empty_delete_folder(output: str) -> int:
    """Permanently delete everything in the _To Delete folder (only on explicit user request)."""
    folder = os.path.join(output, DELETE_FOLDER)
    if not os.path.isdir(folder):
        return 0
    count = sum(len(f) for _, _, f in os.walk(folder))
    try:
        from send2trash import send2trash  # Recycle Bin when available
        send2trash(folder)
    except Exception:
        shutil.rmtree(folder)
    return count
