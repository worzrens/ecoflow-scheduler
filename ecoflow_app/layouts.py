"""Responsive helpers: wrapping FlowLayout and a width-aware Reflow container."""
from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QGridLayout, QLayout, QScrollArea, QSizePolicy, QSplitter, QSplitterHandle,
                               QVBoxLayout, QWidget)


class FlowLayout(QLayout):
    """Lays items left to right and wraps to the next line when the width runs out."""

    def __init__(self, parent=None, hspacing: int = 10, vspacing: int = 8):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, w):
        return self._layout(QRect(0, 0, w, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        lines: list[list[tuple]] = []
        cur: list[tuple] = []
        x = r.x()
        for it in self._items:
            sz = it.sizeHint()
            nx = x + sz.width()
            if nx > r.right() + 1 and cur:
                lines.append(cur)
                cur, x = [], r.x()
                nx = x + sz.width()
            cur.append((it, sz, x))
            x = nx + self._h
        if cur:
            lines.append(cur)
        y = r.y()
        for line in lines:
            lh = max(sz.height() for _, sz, _ in line)
            if not test:   # labels and controls of different heights share one centre line
                for it, sz, ix in line:
                    it.setGeometry(QRect(QPoint(ix, y + (lh - sz.height()) // 2), sz))
            y += lh + self._v
        return (y - self._v if lines else y) - rect.y() + m.bottom()


Placement = tuple[QWidget, int, int, int, int]   # widget, row, col, rowSpan, colSpan


class Reflow(QWidget):
    """A page whose widgets are re-arranged in a grid by plan(width, height) -> (placements, col_stretch,
    row_stretch[, mode]). `mode` lets a plan switch presentation without changing positions."""

    def __init__(self, plan):
        super().__init__()
        self._plan = plan
        self._key: object = None
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(14)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def rearrange(self, width: int, height: int):
        res = self._plan(width, height)
        placements, col_stretch, row_stretch = res[:3]
        mode = res[3] if len(res) > 3 else None
        key = (tuple((id(w), r, c, rs, cs) for w, r, c, rs, cs in placements), tuple(col_stretch.items()),
               tuple(row_stretch.items()), mode)
        if key == self._key:
            return
        self._key = key
        for i in range(self.grid.count() - 1, -1, -1):
            item = self.grid.takeAt(i)
            if item and item.widget():
                item.widget().hide()
        for i in range(12):
            self.grid.setColumnStretch(i, 0)
            self.grid.setRowStretch(i, 0)
        for w, r, c, rs, cs in placements:
            self.grid.addWidget(w, r, c, rs, cs)
            w.show()
        for c, s_ in col_stretch.items():
            self.grid.setColumnStretch(c, s_)
        for r, s_ in row_stretch.items():
            self.grid.setRowStretch(r, s_)


class ReflowScroll(QScrollArea):
    """Scroll area that feeds its *viewport* size to the Reflow plan (so content only scrolls when it truly cannot fit)."""

    def __init__(self, plan):
        super().__init__()
        self.page = Reflow(plan)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setWidget(self.page)
        self.viewport().installEventFilter(self)
        self.page.rearrange(1000, 800)

    def _refit(self):
        vp = self.viewport().size()
        self.page.rearrange(vp.width(), vp.height())

    def eventFilter(self, obj, ev):
        if obj is self.viewport() and ev.type() == QEvent.Resize:
            self._refit()
        return super().eventFilter(obj, ev)

    def showEvent(self, e):
        super().showEvent(e)
        self._refit()


class GripHandle(QSplitterHandle):
    """Invisible gap that shows a small grip only while hovered or dragged (like a window manager)."""

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hover = False
        self._down = False

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._down = True
        self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._down = False
        self.update()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        if not (self._hover or self._down):
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2ee68a" if self._down else "#4a505c"))
        w, h = self.width(), self.height()
        if self.orientation() == Qt.Vertical:      # stacked widgets -> horizontal grip
            p.drawRoundedRect(QRectF(w / 2 - 26, h / 2 - 3, 52, 6), 3, 3)
        else:
            p.drawRoundedRect(QRectF(w / 2 - 3, h / 2 - 26, 6, 52), 3, 3)


class GripSplitter(QSplitter):
    def __init__(self, orientation):
        super().__init__(orientation)
        self.setHandleWidth(14)
        self.setChildrenCollapsible(False)
        self.setOpaqueResize(True)

    def createHandle(self):
        return GripHandle(self.orientation(), self)


class SplitPage(QScrollArea):
    """Cards in resizable splitters. Wide: rows of two side by side; narrow: one column. Footer label below.

    `cards` maps a key to a widget; `wide_rows` lists the keys per row for the wide layout, `narrow` the order for the
    narrow one."""
    WIDE = 1180

    def __init__(self, cards: dict[str, QWidget], footer, wide_rows: list[list[str]], narrow: list[str]):
        super().__init__()
        self.cards = dict(cards)
        self.wide_rows, self.narrow = wide_rows, narrow
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        root = QWidget()
        self._v = QVBoxLayout(root)
        self._v.setContentsMargins(0, 0, 0, 0)
        self._v.setSpacing(10)
        self._v.addWidget(footer)
        self.setWidget(root)
        self._outer = None
        self._tops: list[GripSplitter] = []
        self._mode = None
        self.viewport().installEventFilter(self)
        self._build("wide")

    def _build(self, mode: str):
        if mode == self._mode:
            return
        self._mode = mode
        for c in self.cards.values():
            c.setParent(None)
        old = self._outer
        outer = GripSplitter(Qt.Vertical)
        self._tops = []
        if mode == "wide":
            for row in self.wide_rows:
                if len(row) == 1:
                    outer.addWidget(self.cards[row[0]])
                    continue
                top = GripSplitter(Qt.Horizontal)
                for key in row:
                    top.addWidget(self.cards[key])
                    top.setStretchFactor(top.count() - 1, 1)
                outer.addWidget(top)
                self._tops.append(top)
            n = len(self.wide_rows)
        else:
            for key in self.narrow:
                outer.addWidget(self.cards[key])
            n = len(self.narrow)
        for i in range(n):
            outer.setStretchFactor(i, 1)
        self._v.insertWidget(0, outer, 1)
        self._outer = outer
        if old is not None:
            old.setParent(None)
            old.deleteLater()
        for c in self.cards.values():
            c.show()
        QTimer.singleShot(0, lambda: self._default_sizes(n))

    def _default_sizes(self, n: int):
        h = max(self.viewport().height(), 500)
        # tall cards (calendar views) need room: give every row at least its minimum, the splitter adds the rest
        self._outer.setSizes([int(h * 0.9 / max(n, 1))] * n)
        w = max(self.viewport().width(), 400)
        for top in self._tops:
            top.setSizes([w // top.count()] * top.count())

    def eventFilter(self, obj, ev):
        if obj is self.viewport() and ev.type() == QEvent.Resize:
            self._build("wide" if self.viewport().width() >= self.WIDE else "narrow")
        return super().eventFilter(obj, ev)
