"""
Layer Search - Substance 3D Painter (12.x / PySide6)

A search box in the Layers panel header, between the "Base color" dropdown and
the layer icons. Type to get a dropdown of matching layers/groups; pick one and
the stack opens its parent groups and selects it.

Painter rebuilds the Layers header constantly, so the box is NOT put inside it.
It lives on the (stable) Layers dock and is positioned to follow the dropdown.

Install: copy to Documents/Adobe/Adobe Substance 3D Painter/python/plugins/
then enable via the Python menu.

Tested on Substance 3D Painter 12.2. Needs 10.1 or newer (PySide6 + layer stack API).

Copyright (c) 2026 Yenn
Released under the MIT License - see LICENSE.
"""

from PySide6 import QtCore, QtGui, QtWidgets
import shiboken6
import substance_painter as sp
import substance_painter.ui
import substance_painter.textureset
import substance_painter.layerstack
import substance_painter.logging as log

# ---- SETTINGS ---------------------------------------------------------------
GAP = 8                  # px between dropdown / search box / icons
FOLLOW_MS = 120          # how often the box re-syncs with the header
INCLUDE_EFFECTS = False  # also search effects (fill/filter/etc.)
# -----------------------------------------------------------------------------

_state = {"edit": None, "combo": None, "timer": None, "lost": 0,
          "index": {}, "results": None, "logged": False}


def _valid(w):
    return w is not None and shiboken6.isValid(w)


def _same(a, b):
    try:
        return shiboken6.getCppPointer(a)[0] == shiboken6.getCppPointer(b)[0]
    except Exception:
        return False


# ---------------------------------------------------------------- layer index
def _collect(nodes, path, ancestors, out):
    for node in nodes:
        name = node.get_name() or "(unnamed)"
        out.append((" / ".join(path + [name]), node, list(ancestors)))
        if isinstance(node, sp.layerstack.GroupLayerNode):
            _collect(node.sub_layers(), path + [name], ancestors + [node], out)
        if INCLUDE_EFFECTS and isinstance(node, sp.layerstack.LayerNode):
            for eff in list(node.content_effects()) + list(node.mask_effects()):
                out.append((" / ".join(path + [name, eff.get_name() or "effect"]),
                            eff, ancestors + [node]))


def _rebuild_index():
    index, labels = {}, []
    try:
        stack = sp.textureset.get_active_stack()
        entries = []
        _collect(sp.layerstack.get_root_layer_nodes(stack), [], [], entries)
        seen = {}
        for label, node, anc in entries:
            name = node.get_name() or "(unnamed)"
            k = seen.get(name, 0)          # k-th layer with this name, in stack order
            seen[name] = k + 1
            base, n = label, 2
            while label in index:
                label = "%s (%d)" % (base, n)
                n += 1
            parent = " / ".join(a.get_name() or "(unnamed)" for a in anc)
            index[label] = (node, anc, name, k, parent)
            labels.append(label)
    except Exception as e:
        log.warning("Layer Search: could not read layer stack (%s)" % e)
        return
    _state["index"] = index


def _layers_view():
    combo = _state.get("combo")
    p = combo.parentWidget() if _valid(combo) else None
    while p is not None:
        if p.objectName() == "LayersStackView":
            return p
        p = p.parentWidget()
    return None


def _scroll_to(name, k, tries):
    """Scroll the layer list so the k-th row called `name` is near the top.
    Retries briefly: expanding a group needs a moment before its rows exist."""
    try:
        view = _layers_view()
        if view is not None:
            P = QtCore.QPoint
            rows = [l for l in view.findChildren(QtWidgets.QLabel)
                    if l.isVisible() and l.text() == name]
            rows.sort(key=lambda l: l.mapToGlobal(P(0, 0)).y())
            if len(rows) > k:
                label = rows[k]
                area = label
                while area is not None and not (
                        isinstance(area, QtWidgets.QAbstractScrollArea)
                        and area.verticalScrollBar().maximum() > 0):
                    area = area.parentWidget()
                if area is not None:
                    sb = area.verticalScrollBar()
                    y = label.mapTo(area.viewport(), P(0, 0)).y()
                    # land just under the results list (it floats over the top of the stack)
                    want = 40
                    res = _state.get("results")
                    if _valid(res) and res.isVisible():
                        bottom = res.mapToGlobal(P(0, res.height())).y()
                        want = max(want, area.viewport().mapFromGlobal(P(0, bottom)).y() + 8)
                    sb.setValue(sb.value() + y - want)
                return
    except Exception as e:
        log.warning("Layer Search: scroll failed (%s)" % e)
        return
    if tries > 0:
        QtCore.QTimer.singleShot(80, lambda: _scroll_to(name, k, tries - 1))


def _goto(label):
    hit = _state.get("index", {}).get(label)
    if not hit:
        return
    node, ancestors, name, k, _parent = hit
    try:
        for grp in ancestors:
            if grp.is_collapsed():
                grp.set_collapsed(False)
        sp.layerstack.set_selected_nodes([node])
    except Exception as e:
        log.error("Layer Search: failed to select layer (%s)" % e)
        return
    QtCore.QTimer.singleShot(60, lambda: _scroll_to(name, k, 15))


# ------------------------------------------------------------------------ UI
class _EditEvents(QtCore.QObject):
    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QtCore.QEvent.FocusIn:
            _rebuild_index()
            _refresh()
        elif t == QtCore.QEvent.KeyPress:
            k = ev.key()
            res = _state.get("results")
            if k == QtCore.Qt.Key_Escape:
                obj.clear()
                _hide_results()
                return True
            if _valid(res) and res.isVisible():
                if k in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Up):
                    n = res.model().rowCount()
                    row = res.currentIndex().row()
                    row = (0 if k == QtCore.Qt.Key_Down else n - 1) if row < 0 else \
                          max(0, min(n - 1, row + (1 if k == QtCore.Qt.Key_Down else -1)))
                    res.setCurrentIndex(res.model().index(row, 0))
                    res.scrollTo(res.currentIndex())
                    return True
                if k in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
                    idx = res.currentIndex()
                    if not idx.isValid() and res.model().rowCount():
                        idx = res.model().index(0, 0)
                    if idx.isValid():
                        _goto(idx.data())
                    return True
        return False


class _ResultDelegate(QtWidgets.QStyledItemDelegate):
    """Row = layer name, then its parent path in grey."""
    ROW_H = 26

    def sizeHint(self, option, index):
        sz = super().sizeHint(option, index)
        return QtCore.QSize(sz.width(), self.ROW_H)

    def paint(self, painter, option, index):
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        label = opt.text
        hit = _state.get("index", {}).get(label)
        name, parent = (hit[2], hit[4]) if hit else (label, "")
        opt.text = ""
        style = opt.widget.style() if opt.widget else QtWidgets.QApplication.style()
        style.drawControl(QtWidgets.QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        selected = bool(opt.state & QtWidgets.QStyle.State_Selected)
        painter.save()
        fm = painter.fontMetrics()
        r = opt.rect.adjusted(8, 0, -8, 0)
        main = QtGui.QColor(255, 255, 255) if selected else QtGui.QColor(232, 232, 232)
        grey = QtGui.QColor(215, 225, 240) if selected else QtGui.QColor(172, 172, 172)
        painter.setPen(main)
        name_txt = fm.elidedText(name, QtCore.Qt.ElideRight, int(r.width() * 0.6))
        painter.drawText(r, int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), name_txt)
        if parent:
            x = fm.horizontalAdvance(name_txt) + 14
            painter.setPen(grey)
            rest = fm.elidedText(parent, QtCore.Qt.ElideLeft, max(10, r.width() - x))
            painter.drawText(r.adjusted(x, 0, 0, 0),
                             int(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft), rest)
        painter.restore()


class _EscapeAnywhere(QtCore.QObject):
    """Esc hides the results list wherever the keyboard focus is in Painter."""

    def eventFilter(self, obj, ev):
        if ev.type() == QtCore.QEvent.KeyPress and ev.key() == QtCore.Qt.Key_Escape:
            res, edit = _state.get("results"), _state.get("edit")
            if _valid(res) and res.isVisible():
                if _valid(edit) and edit.hasFocus():
                    return False                   # the box handles it (clears + hides)
                _hide_results()
                return True                        # only swallowed when it closed the list
        return False


class _Results(QtWidgets.QListView):
    """Floating results list. A plain tool window (not a Qt popup), so it never grabs
    the mouse or focus: you can scroll / click the layer stack with it still open."""
    ROW_H = 26
    MAX_ROWS = 14
    WIDTH = 560

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint
                            | QtCore.Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setModel(QtCore.QStringListModel(self))
        self.setItemDelegate(_ResultDelegate(self))

    def mouseReleaseEvent(self, ev):
        if ev.button() == QtCore.Qt.LeftButton:
            idx = self.indexAt(ev.position().toPoint())
            if idx.isValid():
                self.setCurrentIndex(idx)
                _goto(idx.data())
        ev.accept()


def _hide_results(keep_wanted=False):
    if not keep_wanted:
        _state["wanted"] = False
    res = _state.get("results")
    if _valid(res):
        res.hide()


def _position_results():
    res, edit = _state.get("results"), _state.get("edit")
    if not (_valid(res) and _valid(edit) and edit.isVisible()):
        return
    n = min(res.model().rowCount(), _Results.MAX_ROWS)
    scr = edit.screen().availableGeometry()
    w = min(_Results.WIDTH, scr.width() - 20)
    pos = edit.mapToGlobal(QtCore.QPoint(0, edit.height() + 2))
    x = min(pos.x(), scr.right() - w)
    res.setGeometry(max(scr.left(), x), pos.y(), w, n * _Results.ROW_H + 4)


def _refresh():
    """Re-filter the list for the current text (called on every edit)."""
    res, edit = _state.get("results"), _state.get("edit")
    if not (_valid(res) and _valid(edit)):
        return
    q = edit.text().strip().lower()
    if not q:
        _hide_results()
        return
    labels = [l for l in _state.get("index", {}) if q in l.lower()][:300]
    res.model().setStringList(labels)
    if not labels:
        _hide_results()
        return
    _state["wanted"] = True
    _position_results()
    if not res.isVisible():
        res.show()
    res.scrollToTop()


def _app_state(state):
    res = _state.get("results")
    if state != QtCore.Qt.ApplicationActive:      # switched to another program
        _hide_results(keep_wanted=True)
    elif _valid(res) and _state.get("wanted") and not res.isVisible():
        res.show()


def _make_edit(parent):
    edit = QtWidgets.QLineEdit(parent)
    edit.setPlaceholderText("Search layers...")
    edit.setClearButtonEnabled(True)
    edit.textChanged.connect(lambda _t: _refresh())
    ev = _EditEvents(edit)
    edit.installEventFilter(ev)
    _state["events"] = ev
    old = _state.get("results")
    if _valid(old):
        old.deleteLater()
    _state["results"] = _Results(sp.ui.get_main_window())
    return edit



def _find_header_combo():
    """The Layers panel channel dropdown. Matched by Painter's object names so the
    viewport's Material dropdown (which lists the same channels) is never picked."""
    for w in QtWidgets.QApplication.allWidgets():
        try:
            if not (isinstance(w, QtWidgets.QComboBox) and _valid(w) and w.isVisible()):
                continue
            if w.objectName() != "channelSelector":
                continue
            p = w.parentWidget()
            while p is not None:
                if p.objectName() == "LayersStackView":
                    return w
                p = p.parentWidget()
        except RuntimeError:
            continue
    return None


def _dock_of(widget):
    p = widget.parentWidget()
    while p is not None:
        if isinstance(p, QtWidgets.QDockWidget):
            return p
        p = p.parentWidget()
    return widget.window()


def _style_like(edit, combo):
    """Match the search box to the neighbouring dropdown: same height, fill, border, text colour."""
    bg, border, text, h = "#2d2d2d", "#4d4d4d", "#e3e3e3", 26
    try:
        im = combo.grab().toImage()
        W, H = im.width(), im.height()
        bg = im.pixelColor(W // 2, H // 2).name()
        border = im.pixelColor(W // 2, 0).name()
        text = combo.palette().color(QtGui.QPalette.Text).name()
        h = combo.height()
    except Exception:
        pass
    edit.setStyleSheet(
        "QLineEdit{background:%s;border:1px solid %s;border-radius:3px;color:%s;"
        "padding:0px 8px;min-height:%dpx;max-height:%dpx;"
        "selection-background-color:%s;}"
        "QLineEdit:focus{border:1px solid #8a8a8a;}" % (bg, border, text, h - 2, h - 2, border))
    edit.setProperty("_h", h)
    res = _state.get("results")
    if _valid(res):
        res.setStyleSheet(
            "QListView{background:%s;border:1px solid %s;color:%s;outline:0;}"
            "QListView::item:hover{background:#3a3a3a;}"
            "QListView::item:selected{background:#3d5a80;}" % (bg, border, text))


def _place(edit, combo):
    """Put the box right of the dropdown and left of the first icon button."""
    dock = edit.parentWidget()
    header = combo.parentWidget()
    if edit.property("_h") != combo.height():
        _style_like(edit, combo)
    P = QtCore.QPoint
    left = combo.mapTo(dock, P(combo.width() + GAP, 0)).x()
    top = combo.mapTo(dock, P(0, 0)).y()
    right = header.mapTo(dock, P(header.width(), 0)).x() - GAP
    for b in header.findChildren(QtWidgets.QAbstractButton):
        try:
            if _valid(b) and b.isVisible() and not _same(b, edit):
                pt = b.mapTo(dock, P(0, 0))
                # only the icons on the dropdown's own row, not layer-row buttons below it
                if abs(pt.y() - top) > combo.height() // 2 or pt.y() + b.height() > top + combo.height() * 2:
                    continue
                if pt.x() > left:
                    right = min(right, pt.x() - GAP)
        except RuntimeError:
            continue
    if right - left < 120:      # something odd limited the width: fall back to "leave room for the icons"
        right = max(right, header.mapTo(dock, P(header.width(), 0)).x() - GAP - 190)
    rect = QtCore.QRect(left, top, max(80, right - left), combo.height())
    if edit.geometry() != rect:
        edit.setGeometry(rect)
    edit.raise_()


def _follow():
    """Timer: keep the box glued to the Layers header, whatever Painter rebuilds."""
    try:
        edit, combo = _state.get("edit"), _state.get("combo")
        if not (_valid(combo) and combo.isVisible()):
            # header gone (project closed / rebuilt / tab hidden): look for a new one, throttled
            _state["lost"] += 1
            if _state["lost"] % 5 == 1:
                combo = _find_header_combo()
                _state["combo"] = combo
            if combo is None:
                if _valid(edit) and _state["lost"] > 10:      # header really gone, not just rebuilding
                    _hide_results(keep_wanted=True)
                    edit.hide()
                return
        _state["lost"] = 0
        dock = _dock_of(combo)
        if not _valid(edit):
            edit = _make_edit(dock)
            _state["edit"] = edit
            _rebuild_index()
        elif not _same(edit.parentWidget(), dock):
            edit.setParent(dock)
        _place(edit, combo)
        res = _state.get("results")
        if _valid(res):
            if _state.get("wanted") and edit.isVisible() and edit.text().strip():
                if not res.isVisible():
                    res.show()                 # came back after Painter rebuilt the header
                _position_results()
            elif res.isVisible():
                res.hide()
        if not edit.isVisible():
            edit.show()
            edit.raise_()
        if not _state["logged"]:
            _state["logged"] = True
            log.info("Layer Search: attached to Layers header (box %s)" % edit.geometry())
    except Exception:
        import traceback
        _state["errors"] = _state.get("errors", 0) + 1
        if _state["errors"] <= 3:
            log.error("Layer Search error:\n" + traceback.format_exc())


def start_plugin():
    _state.update(index={}, lost=0, logged=False, errors=0, wanted=False)
    QtGui.QGuiApplication.instance().applicationStateChanged.connect(_app_state)
    esc = _EscapeAnywhere(sp.ui.get_main_window())
    QtWidgets.QApplication.instance().installEventFilter(esc)
    _state["esc"] = esc
    timer = QtCore.QTimer(sp.ui.get_main_window())
    timer.setInterval(FOLLOW_MS)
    timer.timeout.connect(_follow)
    timer.start()
    _state["timer"] = timer
    log.info("Layer Search: started (waiting for Layers panel)")


def close_plugin():
    timer, edit = _state.get("timer"), _state.get("edit")
    try:
        QtGui.QGuiApplication.instance().applicationStateChanged.disconnect(_app_state)
    except Exception:
        pass
    esc = _state.get("esc")
    if _valid(esc):
        QtWidgets.QApplication.instance().removeEventFilter(esc)
        esc.deleteLater()
    res = _state.get("results")
    if _valid(res):
        res.hide()
        res.deleteLater()
    if _valid(timer):
        timer.stop()
        timer.deleteLater()
    if _valid(edit):
        edit.setParent(None)
        edit.deleteLater()
    _state.update(edit=None, combo=None, timer=None, results=None)


if __name__ == "__main__":
    start_plugin()
