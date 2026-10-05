"""QML 列表模型基建：dict 行 + 声明式角色名（重构文档 §6.4）。

- 行内操作通过稳定 ID（id_role），不使用显示文本作为主键；
- 增删改严格成对发出 begin/end 通知；
- 批量替换用 reset（调用方不得在每次进度事件里整体 reset）。
"""
from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt


class ListModelBase(QAbstractListModel):
    ROLES: tuple[str, ...] = ()
    id_role = "id"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[dict] = []

    # ---- Qt 模型接口 ----
    def roleNames(self):
        return {Qt.UserRole + 1 + index: name.encode("utf-8")
                for index, name in enumerate(self.ROLES)}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        offset = role - Qt.UserRole - 1
        if not 0 <= offset < len(self.ROLES):
            return None
        return self._items[index.row()].get(self.ROLES[offset])

    # ---- 行操作 ----
    @property
    def items(self) -> list[dict]:
        return list(self._items)

    def item_at(self, row: int) -> dict | None:
        if not 0 <= row < len(self._items):
            return None
        return dict(self._items[row])

    def index_of(self, item_id) -> int:
        for row, item in enumerate(self._items):
            if item.get(self.id_role) == item_id:
                return row
        return -1

    def append_item(self, item: dict) -> bool:
        """按 id 去重追加：已存在同 id 行时返回 False。"""
        if self.index_of(item.get(self.id_role)) != -1:
            return False
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(dict(item))
        self.endInsertRows()
        return True

    def upsert_item(self, item: dict) -> bool:
        """按 id 更新或追加；返回 True 表示发生了插入。"""
        item_id = item.get(self.id_role)
        row = self.index_of(item_id)
        if row == -1:
            return self.append_item(item)
        merged = {**self._items[row], **item}
        self._items[row] = merged
        model_index = self.index(row)
        self.dataChanged.emit(model_index, model_index)
        return False

    def update_item(self, item_id, updates: dict) -> bool:
        row = self.index_of(item_id)
        if row == -1:
            return False
        self._items[row] = {**self._items[row], **updates}
        model_index = self.index(row)
        self.dataChanged.emit(model_index, model_index)
        return True

    def remove_item(self, item_id) -> bool:
        row = self.index_of(item_id)
        if row == -1:
            return False
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._items[row]
        self.endRemoveRows()
        return True

    def clear(self):
        self.reset_items([])

    def reset_items(self, items: list[dict]):
        self.beginResetModel()
        self._items = [dict(item) for item in items]
        self.endResetModel()


class DownloadTaskModel(ListModelBase):
    """下载队列：任务行（阶段 5 接线）。"""

    ROLES = ("jobId", "title", "sourceKind", "fmt", "status", "detail", "output")
    id_role = "jobId"


class PlaylistSongModel(ListModelBase):
    """网易云歌单歌曲行（阶段 6 接线）。"""

    ROLES = ("songId", "name", "artist", "album", "status")
    id_role = "songId"


class MusicRowModel(ListModelBase):
    """音乐管理行（本地 NCM 扫描 + 下载历史合并，阶段 4 接线）。"""

    ROLES = ("path", "name", "folder", "size", "fmt", "status", "output", "sourceKind")
    id_role = "path"
