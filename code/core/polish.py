"""统一旧版面板的外观：去 emoji、清除内联样式、统一间距，使其服从全局主题。"""
import re

from PyQt6.QtWidgets import (
    QAbstractButton, QBoxLayout, QGridLayout, QGroupBox, QLabel, QLayout, QPushButton, QWidget,
)

# 行首的 emoji / 图形符号（含 ▶ ■ ✔ ✅ ❌ ⚠ 等）及其后的空格
_LEAD = re.compile(r"^[\s‍️←-⇿⌀-⏿■-◿☀-➿⬀-⯿"
                   r"\U0001F000-\U0001FFFF]+")


def clean_text(s):
    return _LEAD.sub("", s) if s else s


def polish(root):
    """递归处理 root 下所有控件与布局。可重复调用。"""
    for w in [root] + root.findChildren(QWidget):
        css = w.styleSheet()
        if isinstance(w, QGroupBox):
            w.setTitle(clean_text(w.title()))
            lay = w.layout()
            if lay is not None:
                lay.setContentsMargins(14, 18, 14, 12)
        elif isinstance(w, QAbstractButton):
            w.setText(clean_text(w.text()))
            if isinstance(w, QPushButton) and css:
                if "#d9534f" in css:
                    w.setProperty("danger", True)
                elif "#1a73e8" in css or "background" in css:
                    w.setProperty("primary", True)
                w.setStyleSheet("")
        elif isinstance(w, QLabel):
            if not w.text().lstrip().startswith("<"):
                w.setText(clean_text(w.text()))
            if css and w.objectName() not in ("pageTitle", "pageDesc", "toolHeader"):
                if "font-size: 16px" in css:
                    w.setObjectName("sectionTitle")
                    w.setStyleSheet("")
                elif "background" in css:
                    w.setObjectName("infoBar")
                    w.setStyleSheet("")
                elif "color" in css and "monospace" not in css:
                    w.setObjectName("pageDesc")
                    w.setStyleSheet("")
    pull_buttons_into_groups(root)
    for lay in root.findChildren(QLayout):
        lay.setSpacing(8)


def _buttons_only(layout):
    ws = [layout.itemAt(i).widget() for i in range(layout.count())]
    ws = [w for w in ws if w is not None]
    return bool(ws) and all(isinstance(w, QPushButton) for w in ws)


def pull_buttons_into_groups(root):
    """纵向布局里「紧跟在分组框后面的一行按钮」移进该分组框内：按钮属于哪个分组就放在哪个分组里。"""
    layouts = ([root.layout()] if root.layout() else []) + root.findChildren(QLayout)
    for lay in layouts:
        if not isinstance(lay, QBoxLayout) or lay.direction() != QBoxLayout.Direction.TopToBottom:
            continue
        moves = []
        for i in range(1, lay.count()):
            sub, prev = lay.itemAt(i).layout(), lay.itemAt(i - 1).widget()
            if (sub is not None and isinstance(prev, QGroupBox) and prev.layout() is not None
                    and _buttons_only(sub)):
                moves.append((i, prev))
        for i, grp in reversed(moves):
            item = lay.takeAt(i)
            sub = item.layout()
            target = grp.layout()
            if isinstance(target, QGridLayout):
                target.addLayout(sub, target.rowCount(), 0, 1, max(target.columnCount(), 1))
            else:
                target.addLayout(sub)
