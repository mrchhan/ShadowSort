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
