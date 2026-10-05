"""Qt 列表模型行为测试：增删改、角色值与稳定 ID。"""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

from PySide6.QtCore import QModelIndex, Qt

from qt_bridge.models import DownloadTaskModel, ListModelBase, MusicRowModel, PlaylistSongModel


class Counter:
    def __init__(self):
        self.count = 0

    def __call__(self, *args):
        self.count += 1


class ListModelBaseTests(unittest.TestCase):
    def setUp(self):
        self.model = ListModelBase()
        self.model.ROLES = ("id", "name", "status")
        self.model.id_role = "id"

    def test_roles_mapping(self):
        roles = self.model.roleNames()
        self.assertEqual(roles[Qt.UserRole + 1], b"id")
        self.assertEqual(roles[Qt.UserRole + 3], b"status")

    def test_rowCount_and_data(self):
        self.assertEqual(self.model.rowCount(), 0)
        self.model.append_item({"id": 1, "name": "歌曲", "status": "等待中"})
        self.assertEqual(self.model.rowCount(), 1)
        index = self.model.index(0)
        self.assertEqual(self.model.data(index, Qt.UserRole + 1), 1)
        self.assertEqual(self.model.data(index, Qt.UserRole + 2), "歌曲")
        self.assertIsNone(self.model.data(index, Qt.DisplayRole))
        self.assertIsNone(self.model.data(QModelIndex(), Qt.UserRole + 1))
        self.assertIsNone(self.model.data(self.model.index(5), Qt.UserRole + 1))

    def test_append_rejects_duplicate_id(self):
        self.assertTrue(self.model.append_item({"id": 1, "name": "a"}))
        self.assertFalse(self.model.append_item({"id": 1, "name": "b"}))
        self.assertEqual(self.model.rowCount(), 1)

    def test_insert_signal_pair(self):
        counter = Counter()
        self.model.rowsInserted.connect(lambda *_: counter())
        self.model.append_item({"id": 1, "name": "a"})
        self.assertEqual(counter.count, 1)

    def test_update_item(self):
        counter = Counter()
        self.model.append_item({"id": 1, "name": "a", "status": "等待中"})
        self.model.dataChanged.connect(lambda *_: counter())
        self.assertTrue(self.model.update_item(1, {"status": "下载中"}))
        self.assertEqual(self.model.data(self.model.index(0), Qt.UserRole + 3), "下载中")
        self.assertEqual(counter.count, 1)
        self.assertFalse(self.model.update_item(99, {"status": "x"}))

    def test_upsert_inserts_or_updates(self):
        inserted = self.model.upsert_item({"id": 1, "name": "a"})
        self.assertTrue(inserted)
        updated = self.model.upsert_item({"id": 1, "name": "a2"})
        self.assertFalse(updated)
        self.assertEqual(self.model.item_at(0)["name"], "a2")
        self.assertEqual(self.model.rowCount(), 1)

    def test_remove_item(self):
        counter = Counter()
        self.model.rowsRemoved.connect(lambda *_: counter())
        self.model.append_item({"id": 1, "name": "a"})
        self.model.append_item({"id": 2, "name": "b"})
        self.assertTrue(self.model.remove_item(1))
        self.assertEqual(self.model.rowCount(), 1)
        self.assertEqual(self.model.item_at(0)["id"], 2)
        self.assertEqual(counter.count, 1)
        self.assertFalse(self.model.remove_item(1))

    def test_reset_items_and_clear(self):
        counter = Counter()
        self.model.modelReset.connect(lambda: counter())
        self.model.append_item({"id": 1, "name": "a"})
        self.model.reset_items([{"id": 2, "name": "b"}, {"id": 3, "name": "c"}])
        self.assertEqual(self.model.rowCount(), 2)
        self.assertEqual(counter.count, 1)
        self.model.clear()
        self.assertEqual(self.model.rowCount(), 0)

    def test_item_at_out_of_range(self):
        self.assertIsNone(self.model.item_at(-1))
        self.assertIsNone(self.model.item_at(0))

    def test_concrete_models_roles(self):
        tasks = DownloadTaskModel()
        self.assertEqual(tasks.ROLES, ("jobId", "title", "sourceKind", "fmt",
                                       "status", "detail", "output"))
        self.assertEqual(tasks.id_role, "jobId")
        tasks.append_item({"jobId": 7, "title": "歌", "status": "等待中"})
        self.assertEqual(tasks.data(tasks.index(0), Qt.UserRole + 1), 7)
        self.assertEqual(tasks.index_of(7), 0)
        self.assertEqual(tasks.index_of("不存在"), -1)

        songs = PlaylistSongModel()
        self.assertEqual(songs.id_role, "songId")
        rows = MusicRowModel()
        self.assertEqual(rows.id_role, "path")


if __name__ == "__main__":
    unittest.main()
