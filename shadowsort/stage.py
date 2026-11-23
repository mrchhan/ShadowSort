"""The animated 'stage' — photo mosaic, scan line, AI labels, photos flying into folder cards.

Phases:  idle -> scan (photos stream in) -> label (scan line reveals what each photo is)
         -> file (every photo flies into its folder card) -> done (cards with counts)
"""

from __future__ import annotations

import math
import os
import random
import time

import numpy as np
from typing import Dict, List, Optional

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QFont, QFontMetricsF, QImage, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QRadialGradient)
from PySide6.QtWidgets import QWidget

from .analyzer import THUMB

# ----------------------------------------------------------------- palette (Shadow logo)
BG = QColor("#060a14")
PANEL = QColor("#0c1222")
LINE = QColor("#18213a")
BLUE = QColor("#1e9bff")
CYAN = QColor("#03bbfe")
RED = QColor("#ff3b2f")
ORANGE = QColor("#ff8800")
GREEN = QColor("#22d39a")
TEXT = QColor("#e8eefc")
MUTED = QColor("#7d8bb0")

MONO = "Cascadia Mono, Consolas, JetBrains Mono, DejaVu Sans Mono, monospace"


def mono(pt, bold=False):
    f = QFont()
    f.setFamilies([x.strip() for x in MONO.split(",")])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSizeF(pt)
    f.setBold(bold)
    return f


def sans(pt, weight=QFont.Weight.Normal):
    f = QFont()
    f.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Inter", "DejaVu Sans"])
    f.setPointSizeF(pt)
    f.setWeight(weight)
    return f


def brand_gradient(x1, y1, x2, y2, alpha=255):
    g = QLinearGradient(x1, y1, x2, y2)
    for pos, c in ((0.0, CYAN), (0.35, BLUE), (0.7, RED), (1.0, ORANGE)):
        c = QColor(c)
        c.setAlpha(alpha)
        g.setColorAt(pos, c)
    return g


def ease(p):  # easeInOutCubic
    p = max(0.0, min(1.0, p))
    return 4 * p * p * p if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


def ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


class Tile:
    __slots__ = ("pm", "path", "slot", "born", "card", "u", "v", "delay", "dur", "hs", "tag", "bad", "in_heap")

    def __init__(self, pm, path, slot, born):
        self.pm, self.path, self.slot, self.born = pm, path, slot, born
        self.card = -1
        self.u = self.v = 0.0
        self.delay = 0.0
        self.dur = 0.9
        self.hs = 7.0
        self.tag = ""
        self.bad = False
        self.in_heap = False


class Card:
    def __init__(self, key, title, is_delete=False):
        self.key, self.title, self.is_delete = key, title, is_delete
        self.is_people = False
        self.total = 0
        self.landed = 0
        self.covers: List[QPixmap] = []
        self.rect = QRectF()


class Stage(QWidget):
    cardClicked = Signal(str)

    @property
    def LABEL_TIME(self):
        return getattr(self.style, "label_time", 1.8) if getattr(self, "style", None) else 1.8
    FILE_TIME = 3.2
    MAX_FLYING = 2500

    def __init__(self, logo: Optional[QPixmap] = None, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setMinimumSize(640, 420)
        self.logo = logo
        self.phase = "idle"
        self.tiles: List[Tile] = []
        self.by_path: Dict[str, Tile] = {}
        self.cards: List[Card] = []
        self.tags: List[list] = []
        self.total = 0
        self.status = ""
        self.status_color = BLUE
        self.hover = -1
        self.t_phase = time.perf_counter()
        self.clock_start = None
        self.clock_stop = None
        self._cache: Optional[QPixmap] = None
        self._heap_cache: Optional[QPixmap] = None
        self.dup_pairs: List[tuple] = []
        self._frame = None
        self.style = None
        self.area = QRectF(0, 0, 100, 100)
        self.set_style("mosaic")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(16)

    # ------------------------------------------------------------- public API
    def reset(self, status=""):
        self.phase = "idle"
        self.tiles, self.by_path, self.cards, self.tags = [], {}, [], []
        self.total = 0
        self.status = status
        self.status_color = BLUE
        self.clock_start = self.clock_stop = None
        self._cache = self._heap_cache = None
        self.dup_pairs = []
        self._tagged = set()
        self._frame = None
        if self.style:
            self.style.layout()
        self.t_phase = time.perf_counter()

    def start_scan(self):
        self.reset()
        self.phase = "scan"
        self.status = "finding photos"
        self.clock_start = time.perf_counter()
        self._layout()

    def set_style(self, key):
        from .styles import STYLE_BY_KEY
        cls = STYLE_BY_KEY.get(key, STYLE_BY_KEY["mosaic"])
        self.style = cls(self)
        self.tags = []
        self._layout()

    def set_total(self, n):
        if n != self.total:
            self.total = n
            self._layout()

    def add_photo(self, path: str, thumb: Optional[bytes]):
        if thumb:
            img = QImage(thumb, THUMB, THUMB, THUMB * 3, QImage.Format.Format_RGB888)
            pm = QPixmap.fromImage(img)
        else:
            pm = self._placeholder()
        t = Tile(pm, path, len(self.tiles), time.perf_counter())
        self.tiles.append(t)
        self.by_path[path] = t
        if len(self.tiles) > self.total:
            self.set_total(len(self.tiles))

    def set_status(self, text, color=None):
        self.status = text
        if color is not None:
            self.status_color = color

    def show_plan(self, plan, covers: Dict[str, List[QPixmap]]):
        """Animate the finished plan: label sweep, then every photo flies into its folder."""
        out = plan.options.output
        info = {p.path: p for p in plan.photos}
        keys: Dict[str, Card] = {}
        rng = random.Random(7)
        for a in plan.actions:
            rel = os.path.relpath(a.dst, out)
            key = rel.split(os.sep)[0]
            if key not in keys:
                keys[key] = Card(key, key + "/", is_delete=(a.kind == "delete"))
            card = keys[key]
            card.total += 1
            t = self.by_path.get(a.src)
            if t is None:
                self.add_photo(a.src, None)
                t = self.tiles[-1]
            t.card = key  # resolved to index below
            t.bad = a.kind == "delete"
            p = info.get(a.src)
            if t.bad:
                t.tag = a.reason.split(" of ")[0].split(" (")[0].lower()
            elif p is not None:
                conf = p.extra.get("confidence")
                t.tag = (p.category or "photo").split(" ")[0].lower() + (f" {conf:.2f}" if conf else "")
        cards = sorted((c for c in keys.values() if not c.is_delete), key=lambda c: -c.total)
        cards += [c for c in keys.values() if c.is_delete]
        people = [p for p in getattr(plan, "people", []) if not p.hidden]
        if people:
            pc = Card("By Person", "By Person/")
            pc.is_people = True
            pc.total = len(people)
            cards.insert(0, pc)
        index = {c.key: i for i, c in enumerate(cards)}
        for c in cards:
            c.covers = covers.get(c.key, [])
        self.cards = cards
        for t in self.tiles:
            if isinstance(t.card, str):
                t.card = index[t.card]
            u = rng.random()
            mound = 1 - (2 * u - 1) ** 2
            t.u = 0.03 + 0.94 * u
            t.v = 1 - rng.random() ** 1.4 * (0.25 + 0.7 * mound)
            t.delay = rng.random() * (self.FILE_TIME - 1.0)
            t.dur = 0.75 + rng.random() * 0.35
        if len(self.tiles) > self.MAX_FLYING:
            # thousands of photos: animate a sample, the rest are already in their folders
            fly = set(rng.sample(range(len(self.tiles)), self.MAX_FLYING))
            for k, t in enumerate(self.tiles):
                if k not in fly:
                    t.delay, t.dur = 0.0, 0.001
        self.total = len(self.tiles)
        idx = {t.path: i for i, t in enumerate(self.tiles)}
        self.dup_pairs = [(idx[g[0].path], idx[q.path]) for g in plan.groups for q in g[1:]
                          if g[0].path in idx and q.path in idx]
        self._delay = np.array([t.delay for t in self.tiles])
        self._dur = np.array([t.dur for t in self.tiles])
        self._tagged = set()
        self._layout()
        self.phase = "label"
        self.t_phase = time.perf_counter()
        self.set_status(f"recognising photos · {len(self.tiles):,} checked", CYAN)

    def finish_now(self):
        if self.phase in ("label", "file"):
            self._enter_done()

    def elapsed(self) -> float:
        if not self.clock_start:
            return 0.0
        return (self.clock_stop or time.perf_counter()) - self.clock_start

    # ------------------------------------------------------------- layout
    def _layout(self):
        w, h = self.width(), self.height()
        self.area = QRectF(24, 18, w - 48, h - 18 - 76)
        a = self.area
        if getattr(self, "style", None):
            self.style.layout()
            if self.cards:
                self.style.on_plan()

        # folder cards
        nc = len(self.cards)
        if nc:
            ccols = 2 if nc <= 2 else 3 if nc <= 6 else 4 if nc <= 12 else 5
            crows = math.ceil(nc / ccols)
            cg = 14
            cw = min(360.0, (a.width() - cg * (ccols - 1)) / ccols)
            ch = min((a.height() - cg * (crows - 1)) / crows, cw * 0.74)
            top = a.y() + (a.height() - (ch * crows + cg * (crows - 1))) / 2
            left = a.x() + (a.width() - (cw * ccols + cg * (ccols - 1))) / 2
            for i, c in enumerate(self.cards):
                r, k = divmod(i, ccols)
                c.rect = QRectF(left + k * (cw + cg), top + r * (ch + cg), cw, ch)
            heap_s = max(3.0, min(9.0, math.sqrt((cw * ch * 0.25) / max(1, max(c.total for c in self.cards))) * 1.6))
            for t in self.tiles:
                t.hs = heap_s
        self._cache = None
        self._heap_cache = None

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    def _pile(self, card: Card) -> QRectF:
        r = card.rect
        return QRectF(r.x() + 12, r.y() + r.height() * 0.56, r.width() - 24, r.height() * 0.38)

    def _heap_pos(self, t: Tile) -> QPointF:
        p = self._pile(self.cards[t.card])
        return QPointF(p.x() + t.u * (p.width() - t.hs), p.y() + t.v * (p.height() - t.hs))

    def _placeholder(self):
        pm = QPixmap(THUMB, THUMB)
        pm.fill(QColor("#2a1218"))
        return pm

    # ------------------------------------------------------------- animation
    def _tick(self):
        now = time.perf_counter()
        el = now - self.t_phase
        if self.phase == "label" and el >= self.LABEL_TIME:
            self.phase = "file"
            self.t_phase = now
            for c in self.cards:
                c.landed = 0
        elif self.phase == "file":
            if el >= self.FILE_TIME + 0.15:
                self._enter_done()
        self.update()

    def _enter_done(self):
        self.phase = "done"
        self.t_phase = time.perf_counter()
        self.clock_stop = time.perf_counter()
        for c in self.cards:
            c.landed = c.total
        kept = sum(c.total for c in self.cards if not c.is_delete and not c.is_people)
        dele = sum(c.total for c in self.cards if c.is_delete)
        folders = sum(1 for c in self.cards if not c.is_delete and not c.is_people)
        ppl = sum(c.total for c in self.cards if c.is_people)
        extra = f" · {ppl} people" if ppl else ""
        self.set_status(f"preview ready · {kept:,} photos into {folders} folders{extra} · {dele:,} to _To Delete · "
                        f"nothing moved yet", GREEN)
        self._cache = None

    # ------------------------------------------------------------- painting
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), BG)
        self._paint_backdrop(p)
        now = time.perf_counter()
        el = now - self.t_phase
        if self.phase == "idle":
            self._paint_idle(p, now)
        elif self.phase in ("scan", "label"):
            prog = el / self.LABEL_TIME if self.phase == "label" else 0.0
            X, Y, S, A, Z = self._compute_frame(now, fade=True)
            self.style.draw_back(p, now, self.phase, prog)
            self.style.draw_tiles(p, now, X, Y, S, A, Z, np.ones(len(X), bool), self.phase)
            self.style.draw_front(p, now, self.phase, prog)
            if self.phase == "label":
                self._spawn_tags(now, prog)
            self._paint_tags(p, now)
        elif self.phase == "file":
            self._paint_filing(p, now, el)
            self._paint_tags(p, now)
        elif self.phase == "done":
            if self._cache is None or self._cache.size() != self.size():
                self._cache = self._render_done()
            p.drawPixmap(0, 0, self._cache)
            if 0 <= self.hover < len(self.cards):
                self._paint_card_border(p, self.cards[self.hover], hover=True)
        self._paint_status(p, now)
        p.end()

    def _paint_backdrop(self, p):
        # faint dot grid + soft brand glows in the corners
        g = QRadialGradient(self.width() * 0.08, -40, self.width() * 0.55)
        g.setColorAt(0, QColor(30, 155, 255, 38))
        g.setColorAt(1, QColor(30, 155, 255, 0))
        p.fillRect(self.rect(), g)
        g = QRadialGradient(self.width() * 0.95, self.height() + 40, self.width() * 0.55)
        g.setColorAt(0, QColor(255, 59, 47, 30))
        g.setColorAt(1, QColor(255, 59, 47, 0))
        p.fillRect(self.rect(), g)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 10))
        step = 22
        for y in range(10, self.height(), step):
            for x in range(10, self.width(), step):
                p.drawRect(QRectF(x, y, 1.2, 1.2))

    def _paint_idle(self, p, now):
        cx, cy = self.width() / 2, self.height() / 2 - 40
        r = 74
        # rotating brand ring
        ang = (now * 60) % 360
        cg = QConicalGradient(cx, cy, ang)
        for pos, c in ((0, CYAN), (0.25, BLUE), (0.5, RED), (0.75, ORANGE), (1, CYAN)):
            cg.setColorAt(pos, c)
        for width, alpha in ((14, 40), (8, 80), (3, 255)):
            pen = QPen(cg, width)
            p.setOpacity(alpha / 255)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(cx, cy), r + 8, r + 8)
        p.setOpacity(1)
        if self.logo and not self.logo.isNull():
            path = QPainterPath()
            path.addEllipse(QPointF(cx, cy), r, r)
            p.save()
            p.setClipPath(path)
            p.drawPixmap(QRectF(cx - r, cy - r, 2 * r, 2 * r), self.logo, QRectF(self.logo.rect()))
            p.restore()
        p.setPen(TEXT)
        p.setFont(sans(20, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, cy + r + 30, self.width(), 40), Qt.AlignmentFlag.AlignHCenter, "Drop a photo folder here")
        p.setPen(MUTED)
        p.setFont(sans(10.5))
        p.drawText(QRectF(0, cy + r + 72, self.width(), 24), Qt.AlignmentFlag.AlignHCenter,
                   "ShadowSort reads every photo, keeps the best shot of each duplicate and files the rest into folders.")

    def blank_pixmap(self):
        pm = QPixmap(self.size())
        pm.fill(Qt.GlobalColor.transparent)
        return pm

    def _compute_frame(self, now, fade=True):
        X, Y, S, A, Z = self.style.frame(now)
        m = len(X)
        if fade and m:
            born = np.fromiter((t.born for t in self.tiles[:m]), float, m)
            A = A * np.clip((now - born) / 0.35, 0, 1)
        self._frame = (X, Y, S, A)
        return X, Y, S, A, Z

    def _spawn_tags(self, now, progress):
        m = self.style.n()
        if not m:
            return
        X, Y, S, A = self._frame
        mask = self.style.scan_mask(now, progress)[:m] & (A > 0.5)
        cand = [i for i in np.nonzero(mask)[0] if i not in self._tagged and self.tiles[i].tag]
        if not cand:
            return
        target = min(170, max(12, m // 5))
        quota = max(1, int(target * 0.016 / self.LABEL_TIME * 1.8))
        random.shuffle(cand)
        for i in cand[: quota * 4]:
            if quota <= 0:
                break
            x, y = X[i], Y[i]
            if any(abs(self._tag_xy(o[0])[0] - x) < 115 and abs(self._tag_xy(o[0])[1] - y) < 20 for o in self.tags):
                continue
            self._tagged.add(i)
            self.tags.append([i, self.tiles[i].tag, self.tiles[i].bad, now])
            quota -= 1

    def _tag_xy(self, i):
        X, Y, S, A = self._frame
        if i < len(X):
            return float(X[i] + S[i] / 2), float(Y[i])
        return -999.0, -999.0

    def _paint_tags(self, p, now):
        if self._frame is None:
            return
        p.setFont(mono(7.5, True))
        fm = QFontMetricsF(p.font())
        keep = []
        for tag in self.tags:
            i, text, bad, born = tag
            age = now - born
            if age > 1.1:
                continue
            keep.append(tag)
            x, y = self._tag_xy(i)
            if x < -900:
                continue
            a = min(1.0, age / 0.12) * (1 - max(0.0, (age - 0.8) / 0.3))
            w = fm.horizontalAdvance(text) + 10
            r = QRectF(x - w / 2, y - 17 - age * 6, w, 15)
            p.setOpacity(a)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 59, 47, 230) if bad else QColor(14, 40, 80, 235))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QPen(QColor("#ffd2cc") if bad else QColor("#bfe6ff")))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)
        p.setOpacity(1)
        self.tags = keep

    def _paint_filing(self, p, now, el):
        appear = ease_out(el / 0.5)
        n = len(self.tiles)
        prog = (el - self._delay[:n]) / self._dur[:n]
        waiting = prog <= 0
        landed = prog >= 1
        for c in self.cards:
            c.landed = 0
        cards_idx = np.fromiter((t.card for t in self.tiles), int, n)
        for k, c in enumerate(self.cards):
            c.landed = c.total if c.is_people else int(np.count_nonzero(landed & (cards_idx == k)))
        # the style keeps animating the photos that haven't left yet
        X, Y, S, A, Z = self._compute_frame(now, fade=False)
        m = len(X)
        # the remaining photos shrink back and fade behind the cards while they leave
        q = ease(el / self.FILE_TIME)
        o = self.style.origin()
        if m:
            k = 1 - 0.45 * q
            cxs, cys = X + S / 2, Y + S / 2
            S = S * k
            X = o.x() + (cxs - o.x()) * k - S / 2
            Y = o.y() + (cys - o.y()) * k - S / 2
            A = A * (1 - 0.55 * q)
        p.setOpacity(1 - 0.6 * q)
        self.style.draw_back(p, now, "file", 0.0)
        p.setOpacity(1)
        self.style.draw_tiles(p, now, X, Y, S, A, Z, waiting[:m], "file")
        p.setOpacity(appear)
        for c in self.cards:
            self._paint_card(p, c, covers_alpha=max(0.0, (el - self.FILE_TIME * 0.6) / (self.FILE_TIME * 0.4)),
                             bg_alpha=150 + int(105 * q))
        p.setOpacity(1)
        # landed photos go into a cached heap image
        if self._heap_cache is None or self._heap_cache.size() != self.size():
            self._heap_cache = self.blank_pixmap()
            for t in self.tiles:
                t.in_heap = False
        new = [i for i in np.nonzero(landed)[0] if not self.tiles[i].in_heap]
        if new:
            hp_ = QPainter(self._heap_cache)
            for i in new:
                t = self.tiles[i]
                hp = self._heap_pos(t)
                hp_.drawPixmap(QRectF(hp.x(), hp.y(), t.hs, t.hs), t.pm, QRectF(0, 0, THUMB, THUMB))
                t.in_heap = True
            hp_.end()
        p.drawPixmap(0, 0, self._heap_cache)
        # photos in flight
        src = QRectF(0, 0, THUMB, THUMB)
        for i in np.nonzero(~waiting & ~landed)[0]:
            t = self.tiles[i]
            e = ease(float(prog[i]))
            if i < m and A[i] > 0.05:
                ax, ay, s0, a0 = float(X[i]), float(Y[i]), float(S[i]), float(A[i])
            else:
                ax, ay, s0, a0 = o.x(), o.y(), 4.0, 0.0
            b = self._heap_pos(t)
            size = s0 + (t.hs - s0) * e
            x = ax + (b.x() - ax) * e
            y = ay + (b.y() - ay) * e - math.sin(math.pi * e) * 60
            p.setOpacity(a0 + (1 - a0) * min(1.0, e * 3))
            p.drawPixmap(QRectF(x, y, size, size), t.pm, src)
        p.setOpacity(1)
        for c in self.cards:
            self._paint_count(p, c, c.landed)
        landed_n = int(np.count_nonzero(landed))
        dele = sum(c.landed for c in self.cards if c.is_delete)
        self.set_status(f"filing photos · {landed_n - dele:,} placed · {dele:,} to _To Delete", ORANGE)

    def _render_done(self) -> QPixmap:
        pm = QPixmap(self.size())
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for c in self.cards:
            self._paint_card(p, c, heap=True, covers_alpha=1.0)
            self._paint_count(p, c, c.total)
        p.end()
        return pm

    def _paint_card(self, p, c: Card, heap=False, covers_alpha=1.0, bg_alpha=255):
        r = c.rect
        p.setPen(Qt.PenStyle.NoPen)
        bg = QLinearGradient(r.topLeft(), r.bottomLeft())
        bg.setColorAt(0, QColor(14, 21, 40, bg_alpha))
        bg.setColorAt(1, QColor(10, 15, 29, bg_alpha))
        p.setBrush(bg)
        p.drawRoundedRect(r, 14, 14)
        self._paint_card_border(p, c)
        # title
        p.setFont(mono(9.5, True))
        p.setPen(QColor("#ff7a6e") if c.is_delete else QColor("#ffb066") if c.is_people else QColor("#8fd0ff"))
        p.drawText(QRectF(r.x() + 16, r.y() + 12, r.width() - 32, 20),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                   QFontMetricsF(p.font()).elidedText(c.title, Qt.TextElideMode.ElideRight, r.width() - 32))
        if heap:
            idx = self.cards.index(c)
            for t in self.tiles:
                if t.card == idx:
                    hp = self._heap_pos(t)
                    p.drawPixmap(QRectF(hp.x(), hp.y(), t.hs, t.hs), t.pm, QRectF(0, 0, THUMB, THUMB))
        if covers_alpha > 0 and c.covers:
            self._paint_covers(p, c, min(1.0, covers_alpha))

    def _paint_card_border(self, p, c: Card, hover=False):
        r = c.rect.adjusted(0.5, 0.5, -0.5, -0.5)
        if hover:
            p.setPen(QPen(brand_gradient(r.left(), r.top(), r.right(), r.bottom()), 1.8))
        else:
            p.setPen(QPen(QColor(255, 59, 47, 90) if c.is_delete else LINE, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, 14, 14)

    def _paint_covers(self, p, c: Card, alpha):
        r = c.rect
        size = min(r.height() * 0.36, r.width() * 0.26)
        cx, cy = r.x() + r.width() * 0.28, r.y() + r.height() * 0.50
        angles = [-10, 7, -2][: len(c.covers)]
        p.save()
        p.setOpacity(alpha)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for pm, ang in zip(c.covers[::-1], angles[::-1]):
            if pm.isNull():
                continue
            ar = pm.width() / max(1, pm.height())
            w, h = (size * 1.25, size * 1.25 / ar) if ar >= 1 else (size * ar, size)
            p.save()
            p.translate(cx, cy)
            p.rotate(ang)
            rect = QRectF(-w / 2, -h / 2, w, h)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 120))
            p.drawRoundedRect(rect.translated(3, 5), 8, 8)
            path = QPainterPath()
            path.addRoundedRect(rect, 8, 8)
            p.setClipPath(path)
            p.drawPixmap(rect, pm, QRectF(pm.rect()))
            p.setClipping(False)
            p.setPen(QPen(QColor(255, 255, 255, 70), 1.2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(rect, 8, 8)
            p.restore()
        p.restore()

    def _paint_count(self, p, c: Card, n):
        r = c.rect
        x = r.x() + r.width() * 0.55
        y = r.y() + r.height() * 0.30
        size = max(15.0, min(26.0, r.height() * 0.12))
        p.setFont(sans(size, QFont.Weight.Bold))
        p.setPen(QColor("#ff6b5e") if c.is_delete else QColor("#ffb066") if c.is_people else TEXT)
        p.drawText(QRectF(x, y, r.right() - x - 10, size * 1.8),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, f"{n:,}")
        p.setFont(mono(8))
        p.setPen(MUTED)
        p.drawText(QRectF(x + 2, y + size * 1.7, 120, 16), Qt.AlignmentFlag.AlignLeft,
                   "to review" if c.is_delete else "people" if c.is_people else "photos")

    def _paint_status(self, p, now):
        if not self.status:
            return
        p.setFont(mono(9))
        fm = QFontMetricsF(p.font())
        w = fm.horizontalAdvance(self.status) + 54
        r = QRectF((self.width() - w) / 2, self.height() - 52, w, 34)
        p.setPen(QPen(QColor(255, 255, 255, 22), 1))
        p.setBrush(QColor(10, 15, 30, 235))
        p.drawRoundedRect(r, 17, 17)
        pulse = 0.55 + 0.45 * math.sin(now * 5)
        dot = QColor(self.status_color)
        glow = QColor(dot)
        glow.setAlpha(int(70 * pulse))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(r.x() + 20, r.center().y()), 7, 7)
        p.setBrush(dot)
        p.drawEllipse(QPointF(r.x() + 20, r.center().y()), 3.5, 3.5)
        p.setPen(TEXT)
        p.drawText(r.adjusted(34, 0, -14, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.status)

    # ------------------------------------------------------------- mouse
    def _card_at(self, pos):
        if self.phase != "done":
            return -1
        for i, c in enumerate(self.cards):
            if c.rect.contains(QPointF(pos)):
                return i
        return -1

    def mouseMoveEvent(self, e):
        h = self._card_at(e.position())
        if h != self.hover:
            self.hover = h
            self.setCursor(Qt.CursorShape.PointingHandCursor if h >= 0 else Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, e):
        i = self._card_at(e.position())
        if i >= 0:
            self.cardClicked.emit(self.cards[i].key)
        elif self.phase in ("label", "file"):
            self.finish_now()  # click to skip the animation
