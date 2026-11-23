"""Face grouping logic with synthetic face embeddings (no models needed)."""
import numpy as np

from shadowsort import faces as F


def make_faces(people=5, per=12, noise=0.55, seed=0):
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(people, 128))
    out, truth = [], []
    for p in range(people):
        for k in range(per):
            e = centres[p] / np.linalg.norm(centres[p]) + rng.normal(scale=noise / np.sqrt(128), size=128)
            e = (e / np.linalg.norm(e)).astype(np.float32)
            out.append(F.Face(f"/photos/{p}_{k}.jpg", (0.1, 0.1, 0.2, 0.2), 0.95, 80.0, e))
            truth.append(p)
    return out, truth


def test_each_person_in_one_group_and_never_mixed():
    faces, truth = make_faces()
    groups = F.cluster(faces)
    for g in groups:
        assert len({truth[i] for i in g}) == 1            # no mixing
    assert len(groups) == 5                               # no splitting


def test_two_faces_in_one_photo_are_two_people():
    faces, _ = make_faces(people=1, per=6)
    twin = F.Face(faces[0].path, (0.6, 0.1, 0.2, 0.2), 0.95, 80.0, faces[1].emb.copy())
    groups = F.cluster(faces + [twin])
    for g in groups:
        paths = [(faces + [twin])[i].path for i in g]
        assert len(paths) == len(set(paths))


def test_split_and_merge_people(monkeypatch):
    faces, _ = make_faces(people=2, per=4)
    groups = F.cluster(faces)
    people = [F.Person(k, f"Person {k + 1}", f"Person {k + 1}", list(g), {faces[i].path for i in g})
              for k, g in enumerate(groups)]
    monkeypatch.setattr(F, "make_crops", lambda *a, **k: None)  # no real images here
    a, b = people
    moved = a.faces[:2]
    new = F.split_faces(people, faces, a, moved, new_person=True)
    assert new is not None and len(people) == 3 and set(new.faces) == set(moved)
    F.merge_people(people, faces, new, a)
    assert len(people) == 2 and len(a.faces) == 4


def _face(path, size, x=0.1, emb=None):
    e = emb if emb is not None else np.ones(128, np.float32) / np.sqrt(128)
    return F.Face(path, (x, 0.1, 0.1, 0.1), 0.95, float(size), e)


def test_solo_small_group_and_background_faces():
    faces = [
        _face("solo.jpg", 200), _face("solo.jpg", 40, x=0.8),            # tiny guest far behind: still solo
        _face("pair.jpg", 150), _face("pair.jpg", 140, x=0.5),
        _face("big.jpg", 90), *[_face("big.jpg", 85, x=0.1 * k) for k in range(2, 7)],
        _face("behind.jpg", 300, x=0.5), _face("behind.jpg", 50),        # our person small in the background
    ]
    me = F.Person(0, "Ali", "Person 1", [0, 2, 4, 11], {"solo.jpg", "pair.jpg", "big.jpg", "behind.jpg"})
    mains = F.main_faces(faces)
    kinds = F.person_photo_kinds(me, faces, mains, group_size=5)
    assert kinds == {"solo.jpg": F.SOLO, "pair.jpg": F.SMALL, "big.jpg": F.GROUP, "behind.jpg": F.SMALL}
    assert F.group_photos(faces, mains, 5) == ["big.jpg"]


def test_together_needs_everyone():
    a = F.Person(0, "A", "A", [], {"1.jpg", "2.jpg", "3.jpg"})
    b = F.Person(1, "B", "B", [], {"2.jpg", "3.jpg", "4.jpg"})
    c = F.Person(2, "C", "C", [], {"3.jpg"})
    assert F.together_photos([a, b]) == {"2.jpg", "3.jpg"}
    assert F.together_photos([a, b, c]) == {"3.jpg"}


def test_scales_to_big_events():
    """16,000-photo events produce tens of thousands of faces; grouping must stay fast and correct."""
    import time
    rng = np.random.default_rng(3)
    centres = rng.normal(size=(1500, 128))
    centres /= np.linalg.norm(centres, axis=1, keepdims=True)
    faces, truth = [], []
    for p in range(6000):
        for j, i in enumerate(rng.choice(1500, size=rng.integers(1, 5), replace=False)):
            e = centres[i] + rng.normal(scale=0.75 / np.sqrt(128), size=128)
            faces.append(F.Face(f"/p/{p}.jpg", (0.1 * j, 0.1, 0.1, 0.1), 0.95, 80.0, (e / np.linalg.norm(e)).astype(np.float32)))
            truth.append(i)
    t = time.time()
    groups = F.cluster(faces)
    assert time.time() - t < 30
    assert all(len({truth[i] for i in g}) == 1 for g in groups)
