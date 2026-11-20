"""Animation styles for the stage.

Every style decides where each photo sits while ShadowSort reads and recognises the photos
(the 'home' position), and draws its own scanner effect. The ending (photos flying into the
folder cards) is shared, so every style finishes on the same result screen.

A style returns numpy arrays for the first n photos:  X, Y (top-left), S (size), A (alpha), Z (depth).
"""

from __future__ import annotations

import math
import os

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QLinearGradient, QPainter, QPen, QPolygonF,
                           QRadialGradient, QTransform)

from .analyzer import THUMB

CYAN = QColor("#03bbfe")
BLUE = QColor("#1e9bff")
RED = QColor("#ff3b2f")
ORANGE = QColor("#ff8800")
SRC = QRectF(0, 0, THUMB, THUMB)


def brand_gradient(x1, y1, x2, y2, alpha=255):
    g = QLinearGradient(x1, y1, x2, y2)
    for pos, c in ((0.0, CYAN), (0.35, BLUE), (0.7, RED), (1.0, ORANGE)):
        c = QColor(c)
        c.setAlpha(alpha)
        g.setColorAt(pos, c)
    return g


def ease(p):
    p = max(0.0, min(1.0, p))
    return 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def glow_line(p, a, b, grad, widths=((10, 0.16), (5, 0.32), (2, 1.0)), cosmetic=False):
    for w, al in widths:
        pen = QPen(grad, w)
        pen.setCosmetic(cosmetic)
        p.setOpacity(al)
        p.setPen(pen)
        p.drawLine(a, b)
    p.setOpacity(1)


class Style:
    key = ""
    name = ""
    blurb = ""
    cap = 1500          # how many photos are shown in the animation (the rest still get filed)

    def __init__(self, stage):
        self.st = stage
        self.rng = np.random.default_rng(11)

    # sizes -------------------------------------------------------------
    def n(self):
        return min(len(self.st.tiles), self.cap)

    def capacity(self):
        return max(1, min(self.st.total or len(self.st.tiles) or 1, self.cap))

    def layout(self):
        pass

    def on_plan(self):
        pass

    def origin(self):
        return self.st.area.center()

    # per frame -----------------------------------------------------------
    def frame(self, now):
        raise NotImplementedError

    def draw_back(self, p: QPainter, now, phase, progress):
        pass

    def draw_tiles(self, p: QPainter, now, X, Y, S, A, Z, show, phase):
        tiles = self.st.tiles
        idx = np.nonzero(show & (A > 0.02))[0]
        idx = idx[np.argsort(Z[idx], kind="stable")]
        last = -1.0
        for i in idx:
            a = round(float(A[i]), 2)
            if a != last:
                p.setOpacity(a)
                last = a
            p.drawPixmap(QRectF(float(X[i]), float(Y[i]), float(S[i]), float(S[i])), tiles[i].pm, SRC)
        p.setOpacity(1)

    def draw_front(self, p: QPainter, now, phase, progress):
        pass

    def scan_mask(self, now, progress):
        return np.zeros(self.n(), bool)


# =============================================================================
class MosaicStyle(Style):
    key, name = "mosaic", "Mosaic"
    blurb = "A wall of every photo with a scan line sweeping across it"
    cap = 100_000

    def layout(self):
        st = self.st
        a = st.area
        n = max(1, st.total or len(st.tiles) or 1)
        gap = 1.0 if n > 400 else 2.0
        s = max(3.0, min(64.0, math.sqrt(a.width() * a.height() / n)))
        while True:
            cols = max(1, int((a.width() + gap) // (s + gap)))
            rows = math.ceil(n / cols)
            if rows * (s + gap) - gap <= a.height() or s <= 3:
                break
            s -= 0.25
        self.s, self.gap, self.cols, self.rows = s, gap, cols, rows
        gw, gh = cols * (s + gap) - gap, rows * (s + gap) - gap
        self.grid = QRectF(a.x() + (a.width() - gw) / 2, a.y() + (a.height() - gh) / 2, gw, gh)
        i = np.arange(n)
        self.gx = self.grid.x() + (i % cols) * (s + gap)
        self.gy = self.grid.y() + (i // cols) * (s + gap)
        self._cache = None
        self._baked = 0

    def frame(self, now):
        m = self.n()
        return (self.gx[:m], self.gy[:m], np.full(m, self.s), np.ones(m), np.zeros(m))

    def draw_tiles(self, p, now, X, Y, S, A, Z, show, phase):
        if phase == "file":
            return super().draw_tiles(p, now, X, Y, S, A * 0.9, Z, show, phase)
        st = self.st
        if self._cache is None or self._cache.size() != st.size():
            self._cache = st.blank_pixmap()
            self._baked = 0
        m = len(X)
        # bake fully faded-in tiles into a cached image (fast with thousands of photos)
        cp = None
        while self._baked < m and A[self._baked] >= 1.0:
            cp = cp or QPainter(self._cache)
            i = self._baked
            cp.drawPixmap(QRectF(float(X[i]), float(Y[i]), self.s, self.s), st.tiles[i].pm, SRC)
            self._baked += 1
        if cp:
            cp.end()
        p.drawPixmap(0, 0, self._cache)
        for i in range(self._baked, m):
            a = float(A[i])
            if a <= 0:
                continue
            k = self.s * (1.6 - 0.6 * (1 - (1 - a) ** 3))
            p.setOpacity(a)
            p.drawPixmap(QRectF(X[i] + (self.s - k) / 2, Y[i] + (self.s - k) / 2, k, k), st.tiles[i].pm, SRC)
        p.setOpacity(1)
        p.fillRect(self.grid, QColor(6, 10, 20, 60))

    def _scan_y(self, now, phase, progress):
        g = self.grid
        if phase == "scan":
            filled = math.ceil(len(self.st.tiles) / self.cols)
            return g.y() + ((now * 0.55) % 1.0) * max(self.s, filled * (self.s + self.gap))
        return g.y() + ease(progress) * (g.height() + 20) - 10

    def draw_front(self, p, now, phase, progress):
        if phase not in ("scan", "label"):
            return
        g = self.grid
        y = self._scan_y(now, phase, progress)
        band = 90
        grad = QLinearGradient(0, y - band, 0, y)
        grad.setColorAt(0, QColor(3, 187, 254, 0))
        grad.setColorAt(1, QColor(3, 187, 254, 70))
        p.fillRect(QRectF(g.x(), max(g.y(), y - band), g.width(), max(0, min(band, y - g.y()))), grad)
        glow_line(p, QPointF(g.x() - 6, y), QPointF(g.right() + 6, y), brand_gradient(g.x(), 0, g.right(), 0))

    def scan_mask(self, now, progress):
        y = self._scan_y(now, "label", progress)
        m = self.n()
        return np.abs(self.gy[:m] + self.s / 2 - y) < (self.s + self.gap) * 0.75


# =============================================================================
class GlobeStyle(Style):
    key, name = "globe", "Globe"
    blurb = "Your photos wrap a spinning 3D globe while a scanner ring reads them"
    cap = 1400
    TILT = 0.38

    def layout(self):
        a = self.st.area
        m = self.capacity()
        i = np.arange(m) + 0.5
        self.py = 1 - 2 * i / m
        r = np.sqrt(1 - self.py ** 2)
        th = math.pi * (3 - math.sqrt(5)) * np.arange(m)
        self.px, self.pz = r * np.cos(th), r * np.sin(th)
        self.R = min(a.width(), a.height()) * 0.43
        self.cx, self.cy = a.center().x(), a.center().y() + 6
        self.s0 = max(4.0, min(56.0, self.R * math.sqrt(4 * math.pi / m) * 0.95))

    def origin(self):
        return QPointF(self.cx, self.cy)

    def _rot(self, now):
        th = now * 0.30
        ct, sn = math.cos(th), math.sin(th)
        m = self.n()
        x = self.px[:m] * ct + self.pz[:m] * sn
        z = -self.px[:m] * sn + self.pz[:m] * ct
        cp, sp = math.cos(self.TILT), math.sin(self.TILT)
        y = self.py[:m] * cp - z * sp
        z2 = self.py[:m] * sp + z * cp
        return x, y, z2

    def frame(self, now):
        x, y, z = self._rot(now)
        f = 1 / (1 - 0.28 * z)
        S = self.s0 * f
        X = self.cx + x * self.R * f - S / 2
        Y = self.cy - y * self.R * f - S / 2
        A = np.clip(0.16 + 0.84 * (z + 0.35) / 1.35, 0.12, 1.0)
        return X, Y, S, A, z

    def draw_back(self, p, now, phase, progress):
        R, cx, cy = self.R, self.cx, self.cy
        g = QRadialGradient(cx, cy, R * 1.5)
        g.setColorAt(0.0, QColor(30, 155, 255, 70))
        g.setColorAt(0.55, QColor(30, 110, 255, 28))
        g.setColorAt(0.75, QColor(255, 59, 47, 18))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(cx, cy), R * 1.5, R * 1.5)
        # faint latitude rings for the globe feel
        cp, sp = math.cos(self.TILT), math.sin(self.TILT)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for h in (-0.66, -0.33, 0.0, 0.33, 0.66):
            r = math.sqrt(1 - h * h)
            p.setPen(QPen(QColor(120, 170, 255, 22), 1))
            p.drawEllipse(QPointF(cx, cy - h * cp * R), r * R, r * sp * R)

    def _scan_h(self, now, phase, progress):
        return math.sin(now * 1.1) * 0.92 if phase == "scan" else 0.98 - 1.96 * ease(progress)

    def draw_front(self, p, now, phase, progress):
        R, cx, cy = self.R, self.cx, self.cy
        # atmosphere rim
        rim = QConicalGradient(cx, cy, (now * 25) % 360)
        for pos, c in ((0, CYAN), (0.3, BLUE), (0.55, RED), (0.8, ORANGE), (1, CYAN)):
            rim.setColorAt(pos, c)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for w, al in ((8, 0.10), (3, 0.30), (1.2, 0.8)):
            p.setOpacity(al)
            p.setPen(QPen(rim, w))
            p.drawEllipse(QPointF(cx, cy), R * 1.1, R * 1.1)
        p.setOpacity(1)
        if phase not in ("scan", "label"):
            return
        h = self._scan_h(now, phase, progress)
        r = math.sqrt(max(0.0, 1 - h * h))
        cp, sp = math.cos(self.TILT), math.sin(self.TILT)
        c = QPointF(cx, cy - h * cp * R)
        grad = brand_gradient(cx - r * R, 0, cx + r * R, 0)
        for w, al in ((10, 0.15), (5, 0.35), (2, 1.0)):
            p.setOpacity(al)
            p.setPen(QPen(grad, w))
            p.drawEllipse(c, r * R * 1.04, r * sp * R * 1.04 + 1)
        p.setOpacity(1)

    def scan_mask(self, now, progress):
        h = self._scan_h(now, "label", progress)
        _, _, z = self._rot(now)
        return (np.abs(self.py[: self.n()] - h) < 0.07) & (z > 0)


# =============================================================================
class GalaxyStyle(Style):
    key, name = "galaxy", "Galaxy"
    blurb = "Photos orbit a glowing core in spiral arms while a radar beam sweeps"
    cap = 1600
    SQUASH = 0.48

    def layout(self):
        a = self.st.area
        m = self.capacity()
        rng = np.random.default_rng(5)
        self.Rm = min(a.width() * 0.47, a.height() * 0.47 / self.SQUASH)
        u = rng.random(m)
        self.rr = self.Rm * (0.07 + 0.93 * u ** 0.75)
        arm = np.arange(m) % 3
        k = self.rr / self.Rm
        self.base = arm * 2 * math.pi / 3 + k * 3.4 + rng.normal(0, 0.30, m) * (1 - k * 0.4)
        self.w = 0.22 + 0.55 * (1 - k)
        self.cx, self.cy = a.center().x(), a.center().y()
        self.s0 = max(5.0, min(40.0, math.sqrt(a.width() * a.height() * 0.42 / m)))

    def origin(self):
        return QPointF(self.cx, self.cy)

    def frame(self, now):
        m = self.n()
        ang = self.base[:m] + self.w[:m] * now
        r = self.rr[:m]
        z = np.sin(ang)
        S = self.s0 * (0.65 + 0.45 * (z + 1) / 2) * (0.8 + 0.4 * (1 - r / self.Rm))
        X = self.cx + r * np.cos(ang) - S / 2
        Y = self.cy + r * z * self.SQUASH - S / 2
        A = 0.45 + 0.55 * (z + 1) / 2
        return X, Y, S, A, z

    def draw_back(self, p, now, phase, progress):
        cx, cy, R = self.cx, self.cy, self.Rm
        p.save()
        p.translate(cx, cy)
        p.scale(1, self.SQUASH)
        g = QRadialGradient(0, 0, R * 1.05)
        g.setColorAt(0.0, QColor(255, 255, 255, 120))
        g.setColorAt(0.06, QColor(3, 187, 254, 120))
        g.setColorAt(0.30, QColor(30, 120, 255, 45))
        g.setColorAt(0.75, QColor(255, 59, 47, 22))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), R * 1.05, R * 1.05)
        p.restore()

    def draw_front(self, p, now, phase, progress):
        cx, cy, R = self.cx, self.cy, self.Rm
        # bright core on top
        core = QRadialGradient(cx, cy, 46)
        core.setColorAt(0, QColor(255, 255, 255, 230))
        core.setColorAt(0.25, QColor(150, 220, 255, 150))
        core.setColorAt(1, QColor(30, 155, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(core)
        p.drawEllipse(QPointF(cx, cy), 46, 46)
        if phase == "scan":
            p.save()
            p.translate(cx, cy)
            p.scale(1, self.SQUASH)
            ang = -(now * 110) % 360
            cg = QConicalGradient(0, 0, ang)
            cg.setColorAt(0.0, QColor(3, 187, 254, 110))
            cg.setColorAt(0.03, QColor(30, 155, 255, 40))
            cg.setColorAt(0.09, QColor(0, 0, 0, 0))
            cg.setColorAt(0.985, QColor(0, 0, 0, 0))
            cg.setColorAt(1.0, QColor(255, 59, 47, 120))
            p.setBrush(cg)
            p.drawEllipse(QPointF(0, 0), R * 1.02, R * 1.02)
            p.restore()
        elif phase == "label":
            rad = ease(progress) * self.Rm * 1.05
            grad = brand_gradient(cx - rad, 0, cx + rad, 0)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for w, al in ((10, 0.15), (5, 0.35), (2, 1.0)):
                p.setOpacity(al)
                p.setPen(QPen(grad, w))
                p.drawEllipse(QPointF(cx, cy), rad, rad * self.SQUASH)
            p.setOpacity(1)

    def scan_mask(self, now, progress):
        rad = ease(progress) * self.Rm * 1.05
        return np.abs(self.rr[: self.n()] - rad) < self.Rm * 0.035


# =============================================================================
class WallStyle(Style):
    key, name = "wall", "3D Wall"
    blurb = "An endless photo wall tilted in 3D, rolling towards you"
    cap = 1500

    def layout(self):
        a = self.st.area
        m = self.capacity()
        self.C = max(8, math.ceil(math.sqrt(m * 2.2)))
        self.Rr = max(6, math.ceil(m / self.C))
        cx = a.center().x()
        src = QPolygonF([QPointF(0, 0), QPointF(self.C, 0), QPointF(self.C, self.Rr), QPointF(0, self.Rr)])
        dst = QPolygonF([QPointF(cx - a.width() * 0.26, a.y() - a.height() * 0.02),
                         QPointF(cx + a.width() * 0.34, a.y() - a.height() * 0.02),
                         QPointF(a.right() + a.width() * 0.22, a.bottom() + a.height() * 0.06),
                         QPointF(a.x() - a.width() * 0.10, a.bottom() + a.height() * 0.06)])
        self.T = QTransform()
        QTransform.quadToQuad(src, dst, self.T)
        i = np.arange(m)
        self.col = (i % self.C).astype(float)
        self.row = (i // self.C).astype(float)

    def _y(self, now):
        m = self.n()
        return (self.row[:m] + now * 0.45) % self.Rr

    def _map(self, x, y):
        T = self.T
        w = T.m13() * x + T.m23() * y + T.m33()
        return (T.m11() * x + T.m21() * y + T.m31()) / w, (T.m12() * x + T.m22() * y + T.m32()) / w

    def frame(self, now):
        m = self.n()
        y = self._y(now)
        x = self.col[:m]
        x0, y0 = self._map(x + 0.06, y + 0.06)
        x1, y1 = self._map(x + 0.94, y + 0.94)
        S = np.maximum(1.0, x1 - x0)
        far = np.clip(y / (self.Rr * 0.35), 0, 1)           # fade into the distance
        near = np.clip((self.Rr - y) / 0.6, 0, 1)            # fade at the wrap
        A = far * near
        return x0, y0, S, A, y

    def draw_tiles(self, p, now, X, Y, S, A, Z, show, phase):
        tiles = self.st.tiles
        y = Z
        x = self.col[: len(Z)]
        idx = np.nonzero(show & (A > 0.02))[0]
        p.save()
        p.setTransform(self.T, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for i in idx[np.argsort(y[idx])]:
            p.setOpacity(float(A[i]))
            p.drawPixmap(QRectF(float(x[i]) + 0.06, float(y[i]) + 0.06, 0.88, 0.88), tiles[i].pm, SRC)
        p.restore()
        p.setOpacity(1)

    def _scan_row(self, now, phase, progress):
        return ((now * 0.5) % 1.0) * self.Rr if phase == "scan" else (0.35 + 0.65 * ease(progress)) * self.Rr

    def draw_front(self, p, now, phase, progress):
        a = self.st.area
        # depth fog at the top
        fog = QLinearGradient(0, a.y() - 10, 0, a.y() + a.height() * 0.30)
        fog.setColorAt(0, QColor(6, 10, 20, 255))
        fog.setColorAt(1, QColor(6, 10, 20, 0))
        p.fillRect(QRectF(0, 0, self.st.width(), a.y() + a.height() * 0.30), fog)
        if phase not in ("scan", "label"):
            return
        r = self._scan_row(now, phase, progress)
        xa, ya = self._map(np.array([-0.3]), np.array([r]))
        xb, yb = self._map(np.array([self.C + 0.3]), np.array([r]))
        A_, B_ = QPointF(float(xa[0]), float(ya[0])), QPointF(float(xb[0]), float(yb[0]))
        glow_line(p, A_, B_, brand_gradient(A_.x(), 0, B_.x(), 0))

    def scan_mask(self, now, progress):
        r = self._scan_row(now, "label", progress)
        return np.abs(self._y(now) + 0.5 - r) < 0.6


# =============================================================================
class NeuralStyle(Style):
    key, name = "neural", "Neural"
    blurb = "A living AI network: photos link up, duplicates glow red, then cluster by folder"
    cap = 1100

    def layout(self):
        a = self.st.area
        m = self.capacity()
        rng = np.random.default_rng(3)
        mx, my = a.width() * 0.04, a.height() * 0.06
        self.bx = a.x() + mx + rng.random(m) * (a.width() - 2 * mx)
        self.by = a.y() + my + rng.random(m) * (a.height() - 2 * my)
        self.ph = rng.random((2, m)) * 2 * math.pi
        self.sp = 0.35 + rng.random(m) * 0.6
        self.s0 = max(6.0, min(38.0, math.sqrt(a.width() * a.height() * 0.2 / m)))
        # 2 nearest neighbours -> network edges
        pts = np.stack([self.bx, self.by], 1)
        edges = set()
        for start in range(0, m, 400):
            d = ((pts[start:start + 400, None, :] - pts[None, :, :]) ** 2).sum(-1)
            d[np.arange(d.shape[0]), np.arange(start, start + d.shape[0])] = np.inf
            nn = np.argsort(d, 1)[:, :2]
            for k, row in enumerate(nn):
                i = start + k
                for j in row:
                    edges.add((min(i, j), max(i, j)))
        self.edges = np.array(sorted(edges), dtype=int).reshape(-1, 2)
        self.cluster = None
        self.dup_edges = np.zeros((0, 2), int)
        self.pulses = []
        self.on_plan()

    def on_plan(self):
        st = self.st
        if not st.cards or not st.tiles:
            return
        m = self.capacity()
        a = st.area
        rng = np.random.default_rng(9)
        n_c = len(st.cards)
        cx, cy = a.center().x(), a.center().y()
        centers = []
        for k in range(n_c):
            ang = -math.pi / 2 + 2 * math.pi * k / n_c
            rx, ry = (a.width() * 0.34, a.height() * 0.32) if n_c > 1 else (0, 0)
            centers.append((cx + rx * math.cos(ang), cy + ry * math.sin(ang)))
        self.centers = centers
        tx, ty = np.array(self.bx[:m]), np.array(self.by[:m])
        counts = [0] * n_c
        for i in range(min(m, len(st.tiles))):
            c = st.tiles[i].card
            if isinstance(c, int) and c >= 0:
                counts[c] += 1
        for i in range(min(m, len(st.tiles))):
            c = st.tiles[i].card
            if not isinstance(c, int) or c < 0:
                continue
            rad = math.sqrt(counts[c]) * self.s0 * 0.75
            r, t = rad * math.sqrt(rng.random()), rng.random() * 2 * math.pi
            tx[i], ty[i] = centers[c][0] + r * math.cos(t), centers[c][1] + r * math.sin(t) * 0.8
        self.cluster = (tx, ty)
        self.dup_edges = np.array([e for e in st.dup_pairs if e[0] < m and e[1] < m], dtype=int).reshape(-1, 2)

    def _mix(self, now):
        st = self.st
        if self.cluster is None or st.phase not in ("label", "file", "done"):
            return 0.0
        if st.phase == "label":
            return ease((now - st.t_phase) / (st.LABEL_TIME * 0.9))
        return 1.0

    def frame(self, now):
        m = self.n()
        X = self.bx[:m] + np.sin(now * self.sp[:m] + self.ph[0, :m]) * 14
        Y = self.by[:m] + np.cos(now * self.sp[:m] * 0.8 + self.ph[1, :m]) * 10
        mix = self._mix(now)
        if mix > 0:
            tx, ty = self.cluster
            X = X * (1 - mix) + (tx[:m] + np.sin(now * self.sp[:m] + self.ph[0, :m]) * 3) * mix
            Y = Y * (1 - mix) + (ty[:m] + np.cos(now * self.sp[:m] + self.ph[1, :m]) * 3) * mix
        S = np.full(m, self.s0)
        self._cx, self._cy = X, Y  # centres
        return X - S / 2, Y - S / 2, S, np.ones(m), np.zeros(m)

    def draw_back(self, p, now, phase, progress):
        X, Y = getattr(self, "_cx", None), getattr(self, "_cy", None)
        if X is None or len(X) < 2:
            return
        m = len(X)
        mix = self._mix(now)
        e = self.edges[(self.edges[:, 0] < m) & (self.edges[:, 1] < m)]
        if len(e):
            d = np.hypot(X[e[:, 0]] - X[e[:, 1]], Y[e[:, 0]] - Y[e[:, 1]])
            lim = self.s0 * 9
            keep = d < lim
            e, d = e[keep], d[keep]
            alpha = (1 - d / lim) * (1 - 0.7 * mix)
            for lo, hi, a in ((0.0, 0.33, 25), (0.33, 0.66, 55), (0.66, 1.01, 95)):
                sel = e[(alpha >= lo) & (alpha < hi)]
                if len(sel):
                    p.setPen(QPen(QColor(80, 170, 255, a), 1))
                    p.drawLines([QPointF(X[i], Y[i]) for pair in sel for i in pair])
        de = self.dup_edges
        if len(de) and phase == "label" and mix < 0.95:
            pulse = 0.6 + 0.4 * math.sin(now * 6)
            p.setPen(QPen(QColor(255, 59, 47, int(220 * pulse * (1 - mix))), 1.6))
            p.drawLines([QPointF(X[i], Y[i]) for pair in de for i in pair])
        # synapse pulses travelling along edges
        if phase in ("scan", "label") and len(e):
            if len(self.pulses) < 26:
                k = e[np.random.randint(len(e))]
                self.pulses.append([int(k[0]), int(k[1]), now])
            alive = []
            p.setPen(Qt.PenStyle.NoPen)
            for i, j, t0 in self.pulses:
                f = (now - t0) / 0.7
                if f >= 1 or i >= m or j >= m:
                    continue
                alive.append([i, j, t0])
                x, y = X[i] + (X[j] - X[i]) * f, Y[i] + (Y[j] - Y[i]) * f
                g = QRadialGradient(x, y, 9)
                c = CYAN if (i + j) % 3 else RED
                g.setColorAt(0, QColor(c.red(), c.green(), c.blue(), 255))
                g.setColorAt(1, QColor(c.red(), c.green(), c.blue(), 0))
                p.setBrush(g)
                p.drawEllipse(QPointF(x, y), 9, 9)
            self.pulses = alive

    def draw_front(self, p, now, phase, progress):
        if phase != "label" or self.cluster is None:
            return
        from .stage import mono  # local import to avoid a cycle
        a = min(1.0, max(0.0, (progress - 0.4) / 0.4))
        if a <= 0:
            return
        p.setFont(mono(9, True))
        p.setOpacity(a)
        from PySide6.QtGui import QFontMetricsF
        fm = QFontMetricsF(p.font())
        for c, (x, y) in zip(self.st.cards, self.centers):
            if c.is_people:
                continue
            w = fm.horizontalAdvance(c.title) + 20
            r = QRectF(x - w / 2, y - 12, w, 24)
            p.setPen(QPen(QColor(255, 59, 47, 160) if c.is_delete else QColor(30, 155, 255, 160), 1))
            p.setBrush(QColor(6, 10, 20, 225))
            p.drawRoundedRect(r, 12, 12)
            p.setPen(QColor("#ff7a6e") if c.is_delete else QColor("#8fd0ff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, c.title)
        p.setOpacity(1)

    def scan_mask(self, now, progress):
        return np.random.random(self.n()) < 0.012


# =============================================================================
class MatrixStyle(Style):
    key, name = "matrix", "Matrix Rain"
    blurb = "Photos pour down in columns like digital rain"
    cap = 1500

    def layout(self):
        a = self.st.area
        m = self.capacity()
        rng = np.random.default_rng(21)
        self.s0 = max(12.0, min(38.0, math.sqrt(a.width() * a.height() * 0.5 / m)))
        self.C = max(4, int(a.width() // (self.s0 * 1.25)))
        rows = math.ceil(m / self.C)
        self.H = a.height() + self.s0 * 3
        self.sp = max(self.s0 * 1.15, self.H / max(1, rows))
        self.H = max(self.H, rows * self.sp)
        self.colx = a.x() + (np.arange(self.C) + 0.5) * (a.width() / self.C) - self.s0 / 2
        self.speed = 40 + rng.random(self.C) * 70
        self.phase = rng.random(self.C) * self.H
        i = np.arange(m)
        self.col = i % self.C
        self.row = i // self.C

    def frame(self, now):
        m = self.n()
        a = self.st.area
        c = self.col[:m]
        y = (self.row[:m] * self.sp + now * self.speed[c] + self.phase[c]) % self.H
        Y = a.y() - self.s0 * 1.5 + y
        X = self.colx[c]
        top = np.clip((Y - a.y() + self.s0) / (self.s0 * 3), 0, 1)
        bottom = np.clip((a.bottom() - Y) / (self.s0 * 4), 0, 1)
        A = top * bottom
        return X, Y, np.full(m, self.s0), A, y

    def draw_back(self, p, now, phase, progress):
        a = self.st.area
        p.setPen(Qt.PenStyle.NoPen)
        for k in range(self.C):
            hy = a.y() + (now * self.speed[k] * 1.7 + self.phase[k] * 1.3) % (a.height() + 200) - 100
            x = self.colx[k] + self.s0 / 2
            g = QLinearGradient(0, hy - 160, 0, hy)
            g.setColorAt(0, QColor(3, 187, 254, 0))
            g.setColorAt(1, QColor(3, 187, 254, 70))
            p.setBrush(g)
            p.drawRect(QRectF(x - 1.5, hy - 160, 3, 160))
            p.setBrush(QColor(255, 80, 50, 200))
            p.drawEllipse(QPointF(x, hy), 2.6, 2.6)

    def _scan_y(self, now, phase, progress):
        a = self.st.area
        return a.y() + (((now * 0.5) % 1.0) if phase == "scan" else ease(progress)) * a.height()

    def draw_front(self, p, now, phase, progress):
        if phase not in ("scan", "label"):
            return
        a = self.st.area
        y = self._scan_y(now, phase, progress)
        glow_line(p, QPointF(a.x(), y), QPointF(a.right(), y), brand_gradient(a.x(), 0, a.right(), 0))

    def scan_mask(self, now, progress):
        X, Y, S, A, _ = self.frame(now)
        return np.abs(Y + S / 2 - self._scan_y(now, "label", progress)) < S * 0.7


# =============================================================================
class BlackHoleStyle(Style):
    key, name = "blackhole", "Black Hole"
    blurb = "Photos spiral into a black hole with a blazing blue-red accretion disk"
    cap = 1500
    SQUASH = 0.42

    def layout(self):
        a = self.st.area
        m = self.capacity()
        rng = np.random.default_rng(13)
        self.cx, self.cy = a.center().x(), a.center().y()
        self.R = min(a.width() * 0.47, a.height() * 0.47 / self.SQUASH)
        self.rc = min(a.width(), a.height()) * 0.075
        self.rate = 0.045 + rng.random(m) * 0.05
        self.ph = rng.random(m)
        self.base = rng.random(m) * 2 * math.pi
        self.s0 = max(8.0, min(40.0, math.sqrt(a.width() * a.height() * 0.30 / m)))

    def origin(self):
        return QPointF(self.cx, self.cy)

    def frame(self, now):
        m = self.n()
        u = (now * self.rate[:m] + self.ph[:m]) % 1.0
        r = self.rc * 1.15 + (self.R - self.rc * 1.15) * (1 - u) ** 1.3
        ang = self.base[:m] + 2 * math.pi * 2.4 * u ** 1.7 + now * 0.15
        z = np.sin(ang)
        S = self.s0 * (0.3 + 0.7 * r / self.R) * (0.85 + 0.3 * (z + 1) / 2)
        X = self.cx + r * np.cos(ang) - S / 2
        Y = self.cy + r * z * self.SQUASH - S / 2
        A = np.minimum(1, u / 0.06) * np.minimum(1, (1 - u) / 0.15) * (0.55 + 0.45 * (z + 1) / 2)
        self._r = r
        return X, Y, S, A, z

    def draw_back(self, p, now, phase, progress):
        cx, cy, R = self.cx, self.cy, self.R
        p.save()
        p.translate(cx, cy)
        p.scale(1, self.SQUASH)
        g = QRadialGradient(0, 0, R)
        g.setColorAt(0.0, QColor(255, 255, 255, 0))
        g.setColorAt(0.08, QColor(255, 136, 0, 150))
        g.setColorAt(0.16, QColor(255, 59, 47, 110))
        g.setColorAt(0.35, QColor(30, 155, 255, 55))
        g.setColorAt(0.7, QColor(30, 110, 255, 18))
        g.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), R, R)
        p.restore()

    def draw_front(self, p, now, phase, progress):
        cx, cy, rc = self.cx, self.cy, self.rc
        # gravitational-lensing glow and photon ring
        halo = QRadialGradient(cx, cy, rc * 2.6)
        halo.setColorAt(0.35, QColor(255, 140, 40, 150))
        halo.setColorAt(0.5, QColor(30, 155, 255, 70))
        halo.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(halo)
        p.drawEllipse(QPointF(cx, cy), rc * 2.6, rc * 2.6)
        p.setBrush(QColor(0, 0, 0))
        p.drawEllipse(QPointF(cx, cy), rc, rc)
        ring = QConicalGradient(cx, cy, (now * 90) % 360)
        for pos, c in ((0, CYAN), (0.3, BLUE), (0.55, RED), (0.8, ORANGE), (1, CYAN)):
            ring.setColorAt(pos, c)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for w, al in ((7, 0.25), (2.2, 1.0)):
            p.setOpacity(al)
            p.setPen(QPen(ring, w))
            p.drawEllipse(QPointF(cx, cy), rc * 1.08, rc * 1.08)
        p.setOpacity(1)
        if phase in ("scan", "label"):
            rad = (((now * 0.45) % 1.0) if phase == "scan" else ease(progress)) * self.R
            grad = brand_gradient(cx - rad, 0, cx + rad, 0)
            for w, al in ((8, 0.12), (2, 0.8 if phase == "label" else 0.45)):
                p.setOpacity(al)
                p.setPen(QPen(grad, w))
                p.drawEllipse(QPointF(cx, cy), rad, rad * self.SQUASH)
            p.setOpacity(1)

    def scan_mask(self, now, progress):
        self.frame(now)
        return np.abs(self._r - ease(progress) * self.R) < self.R * 0.035


# =============================================================================
class PolaroidStyle(Style):
    key, name = "polaroid", "Polaroid Desk"
    blurb = "Photos drop onto a desk as instant prints while a flash light scans them"
    cap = 100_000
    SHOW = 200

    def layout(self):
        a = self.st.area
        m = self.capacity()
        rng = np.random.default_rng(17)
        self.s = max(40.0, min(92.0, math.sqrt(a.width() * a.height() / self.SHOW) * 1.15))
        mx, my = self.s * 0.7, self.s * 0.75
        self.px = a.x() + mx + rng.random(m) * (a.width() - 2 * mx)
        self.py = a.y() + my + rng.random(m) * (a.height() - 2 * my)
        self.rot = rng.normal(0, 11, m)

    def frame(self, now):
        m = self.n()
        S = np.full(m, self.s)
        A = np.zeros(m)
        A[max(0, m - self.SHOW):] = 1.0
        return self.px[:m] - S / 2, self.py[:m] - S / 2, S, A, np.arange(m, dtype=float)

    def draw_back(self, p, now, phase, progress):
        a = self.st.area
        g = QRadialGradient(a.center().x(), a.center().y(), a.width() * 0.65)
        g.setColorAt(0, QColor(24, 34, 64, 150))
        g.setColorAt(1, QColor(6, 10, 20, 0))
        p.fillRect(self.st.rect(), g)

    def draw_tiles(self, p, now, X, Y, S, A, Z, show, phase):
        tiles = self.st.tiles
        idx = np.nonzero(show & (A > 0.02))[0]
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for i in idx:
            t = tiles[i]
            drop = min(1.0, (now - t.born) / 0.4) if phase == "scan" else 1.0
            k = 1 + 0.6 * (1 - drop) ** 2
            s = float(S[i]) * k
            p.save()
            p.translate(float(X[i] + S[i] / 2), float(Y[i] + S[i] / 2))
            p.rotate(float(self.rot[i]) + (1 - drop) * 25)
            p.setOpacity(float(A[i]))
            fw, fh = s * 1.14, s * 1.36
            frame = QRectF(-fw / 2, -fh / 2 + s * 0.08, fw, fh)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 110))
            p.drawRect(frame.translated(3, 5))
            p.setBrush(QColor("#f4f1ea"))
            p.drawRect(frame)
            p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), t.pm, SRC)
            p.restore()
        p.setOpacity(1)

    def _spot(self, now, phase, progress):
        a = self.st.area
        if phase == "scan":
            return (a.center().x() + math.sin(now * 0.9) * a.width() * 0.4,
                    a.center().y() + math.sin(now * 1.7) * a.height() * 0.35)
        f = ease(progress)
        return (a.x() + f * a.width(), a.center().y() + math.sin(f * 14) * a.height() * 0.38)

    def draw_front(self, p, now, phase, progress):
        if phase not in ("scan", "label"):
            return
        x, y = self._spot(now, phase, progress)
        r = self.s * 1.8
        g = QRadialGradient(x, y, r)
        g.setColorAt(0, QColor(200, 235, 255, 90))
        g.setColorAt(0.6, QColor(30, 155, 255, 40))
        g.setColorAt(1, QColor(30, 155, 255, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r, r)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(brand_gradient(x - r, y, x + r, y), 2))
        p.drawEllipse(QPointF(x, y), r * 0.62, r * 0.62)

    def scan_mask(self, now, progress):
        x, y = self._spot(now, "label", progress)
        m = self.n()
        return np.hypot(self.px[:m] - x, self.py[:m] - y) < self.s * 1.3


# =============================================================================
def _load_preview(path, side=420):
    from PIL import Image, ImageOps
    from PySide6.QtGui import QImage
    try:
        with Image.open(path) as im:
            try:
                im.draft("RGB", (side * 2, side * 2))
            except Exception:
                pass
            im = ImageOps.exif_transpose(im).convert("RGB")
            im = ImageOps.fit(im, (side, int(side * 1.25)))
            data = im.tobytes()
            return QImage(data, im.width, im.height, im.width * 3, QImage.Format.Format_RGB888).copy()
    except Exception:
        return None


class SwipeStyle(Style):
    key, name = "swipe", "Swipe Deck"
    blurb = "Photo cards flick right to keep (blue) or left to delete (red)"
    cap = 100_000
    label_time = 3.6

    def __init__(self, stage):
        super().__init__(stage)
        from concurrent.futures import ThreadPoolExecutor
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.previews = {}
        self.pending = {}
        self.t0 = 0.0
        self.seen_phase = None
        self.seq = []
        self.counts = [0, 0]
        self._last_k = -1

    def layout(self):
        a = self.st.area
        self.ch = min(a.height() * 0.80, 470)
        self.cw = self.ch * 0.8
        self.cx, self.cy = a.center().x(), a.center().y() - 4

    def origin(self):
        return QPointF(self.cx, self.cy)

    def on_plan(self):
        tiles = self.st.tiles
        keep = [i for i, t in enumerate(tiles) if not t.bad]
        bad = [i for i, t in enumerate(tiles) if t.bad]
        seq = []
        while keep or bad:
            for _ in range(2):
                if keep:
                    seq.append(keep.pop(0))
            if bad:
                seq.append(bad.pop(0))
        self.seq = seq

    def frame(self, now):
        m = self.n()
        S = np.full(m, 12.0)
        return np.full(m, self.cx - 6), np.full(m, self.cy - 6), S, np.zeros(m), np.zeros(m)

    def _pix(self, i):
        t = self.st.tiles[i]
        pm = self.previews.get(t.path)
        if pm is not None:
            return pm
        if t.path not in self.pending and len(self.pending) < 6:
            self.pending[t.path] = self.pool.submit(_load_preview, t.path)
        return t.pm

    def _collect(self):
        from PySide6.QtGui import QPixmap
        for path, fut in list(self.pending.items()):
            if fut.done():
                img = fut.result()
                if img is not None:
                    self.previews[path] = QPixmap.fromImage(img)
                elif path in self.st.by_path:
                    self.previews[path] = self.st.by_path[path].pm
                del self.pending[path]
        if len(self.previews) > 60:
            for k in list(self.previews)[:20]:
                self.previews.pop(k, None)

    def _card(self, p, i, dx, dy, rot, scale, alpha, stamp=None, stamp_col=None, stamp_a=0.0):
        t = self.st.tiles[i]
        w, h = self.cw * scale, self.ch * scale
        p.save()
        p.translate(self.cx + dx, self.cy + dy)
        p.rotate(rot)
        p.setOpacity(alpha)
        r = QRectF(-w / 2, -h / 2, w, h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 120))
        p.drawRoundedRect(r.translated(0, 10), 22, 22)
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(r, 22, 22)
        p.setClipPath(path)
        pm = self._pix(i)
        if pm is not None:
            p.drawPixmap(r, pm, QRectF(pm.rect()))
        shade = QLinearGradient(0, h * 0.15, 0, h / 2)
        shade.setColorAt(0, QColor(0, 0, 0, 0))
        shade.setColorAt(1, QColor(4, 8, 18, 230))
        p.fillRect(r, shade)
        p.setClipping(False)
        from .stage import mono, sans
        p.setPen(QColor("#e8eefc"))
        p.setFont(sans(13 * scale, QFont.Weight.Bold))
        name = os.path.basename(t.path)
        p.drawText(QRectF(-w / 2 + 18, h / 2 - 62 * scale, w - 36, 26 * scale), Qt.AlignmentFlag.AlignLeft, name)
        p.setFont(mono(8.5 * scale))
        p.setPen(QColor("#8fd0ff") if not t.bad else QColor("#ff8a7e"))
        p.drawText(QRectF(-w / 2 + 18, h / 2 - 34 * scale, w - 36, 20 * scale), Qt.AlignmentFlag.AlignLeft,
                   t.tag or "reading…")
        p.setPen(QPen(QColor(255, 255, 255, 40), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 22, 22)
        if stamp and stamp_a > 0:
            p.setOpacity(alpha * stamp_a)
            p.save()
            left = stamp_col == RED
            p.translate(w / 2 - 30 - 80 if left else -w / 2 + 30 + 80, -h / 2 + 64)
            p.rotate(16 if left else -16)
            p.setFont(sans(17 * scale, QFont.Weight.ExtraBold))
            sr = QRectF(-90, -24, 180, 48)
            p.setPen(QPen(stamp_col, 4))
            p.drawRoundedRect(sr, 8, 8)
            p.drawText(sr, Qt.AlignmentFlag.AlignCenter, stamp)
            p.restore()
        p.restore()
        p.setOpacity(1)

    def draw_tiles(self, p, now, X, Y, S, A, Z, show, phase):
        st = self.st
        n = len(st.tiles)
        if not n:
            return
        self._collect()
        if phase != self.seen_phase:
            self.seen_phase, self.t0, self._last_k = phase, now, -1
            if phase == "label":
                self.counts = [0, 0]
        fade = 1.0
        if phase == "file":
            fade = max(0.0, 1 - (now - st.t_phase) / 1.0)
            if fade <= 0:
                return
        period = 0.42 if phase == "scan" else 0.30
        el = now - self.t0
        k = int(el / period)
        f = (el / period) % 1.0
        order = self.seq if (phase in ("label", "file") and self.seq) else list(range(max(0, n - 400), n))

        def at(j):
            return order[j % len(order)]

        if phase == "label" and k != self._last_k and self._last_k >= 0:
            prev = st.tiles[at(self._last_k)]
            self.counts[0 if prev.bad else 1] += 1
        self._last_k = k
        for j, (dy, sc) in ((3, (36, 0.86)), (2, (24, 0.91)), (1, (12, 0.955))):
            self._card(p, at(k + j), 0, dy, 0, sc, 0.9 * fade)
        top = at(k)
        t = st.tiles[top]
        go = ease(max(0.0, (f - 0.5) / 0.5))
        if phase == "scan":
            direction, stamp, col = 1, "READ", CYAN
        elif t.bad:
            direction, stamp, col = -1, (t.tag or "delete").upper(), RED
        else:
            direction, stamp, col = 1, "KEEP", BLUE
        wob = math.sin(now * 3) * 1.2 * (1 - go)
        self._card(p, top, direction * go * self.st.area.width() * 0.62, -go * 30, direction * go * 22 + wob,
                   1.0, fade * (1 - go * 0.7), stamp, col, min(1.0, max(0.0, (f - 0.25) / 0.3)))
        for j in range(k + 1, k + 5):  # preload
            self._pix(at(j))

    def draw_front(self, p, now, phase, progress):
        if phase not in ("scan", "label"):
            return
        from .stage import mono, sans
        y = self.cy
        for side, col, sym, label, cnt in ((-1, RED, "✕", "_To Delete", self.counts[0]),
                                          (1, BLUE, "✓", "Keep", self.counts[1])):
            x = self.cx + side * (self.cw / 2 + 120)
            p.setPen(QPen(col, 2))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 30))
            p.drawEllipse(QPointF(x, y), 38, 38)
            p.setFont(sans(20, QFont.Weight.Bold))
            p.drawText(QRectF(x - 38, y - 38, 76, 76), Qt.AlignmentFlag.AlignCenter, sym)
            p.setFont(mono(9, True))
            p.setPen(QColor("#e8eefc"))
            if phase == "label":
                p.drawText(QRectF(x - 80, y + 46, 160, 20), Qt.AlignmentFlag.AlignCenter, f"{cnt:,}")
            p.setPen(QColor("#7d8bb0"))
            p.drawText(QRectF(x - 80, y + 66, 160, 18), Qt.AlignmentFlag.AlignCenter, label)


STYLES = [MosaicStyle, GlobeStyle, GalaxyStyle, WallStyle, NeuralStyle,
          SwipeStyle, PolaroidStyle, MatrixStyle, BlackHoleStyle]
STYLE_BY_KEY = {s.key: s for s in STYLES}
