"""Core behaviour: duplicates, best pick, junk, apply, undo, people folders. Runs without AI or face models."""
import os

import numpy as np
import pytest
from PIL import Image, ImageFilter

from shadowsort.engine import DELETE_FOLDER, PEOPLE_FOLDER, Options, apply_plan, build_plan, latest_undo_log, undo


def photo(seed, w=800, h=600):
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), np.float32)
    img[:] = rng.integers(30, 200, 3)
    yy, xx = np.mgrid[0:h, 0:w]
    for _ in range(25):
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(15, 120)
        img[(xx - cx) ** 2 + (yy - cy) ** 2 < r * r] = rng.integers(0, 255, 3)
    img += rng.normal(0, 6, img.shape)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


@pytest.fixture
def library(tmp_path):
    src = tmp_path / "photos"
    (src / "sub").mkdir(parents=True)
    for i in range(5):
        photo(i).save(src / f"IMG_{i}.jpg", quality=92)
    photo(0).save(src / "IMG_0 copy.jpg", quality=92)                      # exact-ish copy
    photo(1).resize((400, 300)).save(src / "sub" / "IMG-WA0001.jpg", quality=60)  # WhatsApp-style smaller copy
    photo(9).filter(ImageFilter.GaussianBlur(12)).save(src / "blurry.jpg")
    Image.new("RGB", (800, 600), (250, 250, 250)).save(src / "blank.jpg")
    (src / "broken.jpg").write_bytes(b"not an image")
    (src / "notes.txt").write_text("leave me alone")
    return src


def opts(src, **kw):
    return Options(source=str(src), output=str(src / "Organized"), use_ai=False, faces=False, **kw)


def test_plan_finds_duplicates_and_junk(library):
    plan = build_plan(opts(library), log=lambda m: None)
    by_name = {os.path.basename(a.src): a for a in plan.actions}
    assert by_name["blurry.jpg"].reason == "Blurry"
    assert by_name["blank.jpg"].kind == "delete"
    assert by_name["broken.jpg"].reason == "Unreadable or corrupt"
    # the bigger original wins over the WhatsApp copy
    assert by_name["IMG_1.jpg"].kind == "keep"
    assert by_name["IMG-WA0001.jpg"].kind == "delete"
    assert by_name["IMG-WA0001.jpg"].reason.startswith("Duplicate")
    # exactly one of IMG_0 / its copy is kept, and it's the one without "copy" in the name
    assert by_name["IMG_0.jpg"].kind == "keep" and by_name["IMG_0 copy.jpg"].kind == "delete"
    assert plan.stats["keep"] == 5
    assert "notes.txt" not in by_name


def test_apply_and_undo_restore_everything(library):
    before = sorted(p.relative_to(library) for p in library.rglob("*") if p.is_file())
    plan = build_plan(opts(library), log=lambda m: None)
    log = apply_plan(plan)
    out = library / "Organized"
    assert (out / DELETE_FOLDER / "Duplicates").is_dir()
    assert len(list((out / DELETE_FOLDER).rglob("*.jpg"))) == 5
    assert (library / "notes.txt").exists()          # non-photos are never touched
    undo(log)
    after = sorted(p.relative_to(library) for p in library.rglob("*") if p.is_file()
                   if "Organized" not in p.parts)
    assert after == before


def test_copy_mode_leaves_originals(library):
    plan = build_plan(opts(library, copy_instead_of_move=True), log=lambda m: None)
    apply_plan(plan)
    assert (library / "IMG_0.jpg").exists() and (library / "IMG_3.jpg").exists()
    undo(latest_undo_log(str(library / "Organized")))
    assert not list((library / "Organized").rglob("*.jpg"))


def test_people_folders_use_links_not_copies(library):
    from shadowsort.faces import Person

    plan = build_plan(opts(library), log=lambda m: None)
    group = str(library / "IMG_2.jpg")
    plan.people = [Person(0, "Ali", "Person 1", photos={group, str(library / "IMG_3.jpg")}),
                   Person(1, "Sara", "Person 2", photos={group})]
    log = apply_plan(plan)
    ali = library / "Organized" / PEOPLE_FOLDER / "Ali" / "IMG_2.jpg"
    sara = library / "Organized" / PEOPLE_FOLDER / "Sara" / "IMG_2.jpg"
    assert ali.exists() and sara.exists()
    assert os.path.samefile(ali, sara)                # one file on disk, two folders
    undo(log)
    assert (library / "IMG_2.jpg").exists() and not ali.exists()


def test_people_split_into_solo_and_group_folders(library):
    from shadowsort import faces as F

    plan = build_plan(opts(library), log=lambda m: None)
    p = lambda n: str(library / n)  # noqa: E731
    e = np.ones(128, np.float32) / np.sqrt(128)
    plan.faces = [F.Face(p("IMG_2.jpg"), (0.1, 0.1, 0.1, 0.1), 0.9, 120, e),                       # 0 Ali solo
                  *[F.Face(p("IMG_3.jpg"), (0.1 * k, 0.1, 0.1, 0.1), 0.9, 100, e) for k in range(5)]]  # 1-5 group of 5
    plan.people = [F.Person(0, "Ali", "Person 1", [0, 1], {p("IMG_2.jpg"), p("IMG_3.jpg")}),
                   F.Person(1, "Sara", "Person 2", [2], {p("IMG_3.jpg")})]
    plan.together = [["Ali", "Sara"]]
    apply_plan(plan)
    out = library / "Organized"
    assert (out / PEOPLE_FOLDER / "Ali" / "Solo" / "IMG_2.jpg").exists()
    assert (out / PEOPLE_FOLDER / "Ali" / "Group" / "IMG_3.jpg").exists()
    assert not (out / PEOPLE_FOLDER / "Sara" / "Solo").exists()
    assert (out / "Group Photos" / "IMG_3.jpg").exists()
    assert (out / PEOPLE_FOLDER / "Together" / "Ali & Sara" / "IMG_3.jpg").exists()
    assert os.path.samefile(out / "Group Photos" / "IMG_3.jpg", out / PEOPLE_FOLDER / "Ali" / "Group" / "IMG_3.jpg")


def test_export_zip_only_chosen_kinds(library, tmp_path):
    import zipfile
    from shadowsort import faces as F

    p = lambda n: str(library / n)  # noqa: E731
    e = np.ones(128, np.float32) / np.sqrt(128)
    faces = [F.Face(p("IMG_2.jpg"), (0.1, 0.1, 0.1, 0.1), 0.9, 120, e),
             F.Face(p("IMG_3.jpg"), (0.1, 0.1, 0.1, 0.1), 0.9, 100, e),
             F.Face(p("IMG_3.jpg"), (0.5, 0.1, 0.1, 0.1), 0.9, 100, e)]
    ali = F.Person(0, "Ali", "Person 1", [0, 1], {p("IMG_2.jpg"), p("IMG_3.jpg")})
    [solo] = F.export_zips([ali], lambda s: s, str(tmp_path / "a"), faces=faces, kinds=(F.SOLO,))
    assert zipfile.ZipFile(solo).namelist() == ["Solo/IMG_2.jpg"]
    [both] = F.export_zips([ali], lambda s: s, str(tmp_path / "b"), faces=faces)
    assert sorted(zipfile.ZipFile(both).namelist()) == ["Small Group/IMG_3.jpg", "Solo/IMG_2.jpg"]
