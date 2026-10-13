"""工具箱：按分类列出所有工具插件，支持搜索，双击运行。"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from core.icons import icon
from core.plugin import CATEGORIES

_ROLE = Qt.ItemDataRole.UserRole


class Toolbox(QWidget):
    def __init__(self, plugins, run):
        super().__init__()
        self._run = run
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索工具…")
        self.search.setClearButtonEnabled(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(14)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        for cat_id, name in CATEGORIES:
            items = [p for p in plugins if p.category == cat_id]
            if not items:
                continue
            top = QTreeWidgetItem([name])
            top.setIcon(0, icon("folder"))
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(top)
            for p in items:
                it = QTreeWidgetItem([p.title])
                it.setIcon(0, icon(p.icon))
                it.setData(0, _ROLE, p.id)
                it.setToolTip(0, p.description)
                top.addChild(it)
            top.setExpanded(True)
        self.tree.itemActivated.connect(self._open)
        self.tree.itemDoubleClicked.connect(self._open)
        self.search.textChanged.connect(self._filter)

    def _open(self, item, *_):
        pid = item.data(0, _ROLE)
        if pid:
            self._run(pid)

    def _filter(self, text):
        t = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            shown = 0
            for j in range(top.childCount()):
                c = top.child(j)
                hide = bool(t) and t not in (c.text(0) + c.toolTip(0)).lower()
                c.setHidden(hide)
                shown += not hide
            top.setHidden(shown == 0)
            top.setExpanded(True)
