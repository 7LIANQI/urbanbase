"""插件发现：id 唯一、分类合法、顺序稳定。"""
from core.plugin import CATEGORY_IDS, discover


def test_discover():
    ps = discover()
    ids = [p.id for p in ps]
    assert len(ids) == len(set(ids)) >= 6
    assert all(p.category in CATEGORY_IDS for p in ps)
    assert ids[0] == "download.collect"
