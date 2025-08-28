import tempfile, os
from adapters.subscribers_file import FileSubscriberStore


def test_add_remove_and_persistence():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, 'subs.json')
        store = FileSubscriberStore(path)
        assert store.count() == 0
        assert store.add(1)
        assert not store.add(1)
        assert store.exists(1)
        assert store.count() == 1
        assert store.remove(1)
        assert not store.remove(1)
        assert store.count() == 0
        # reload new instance
        store2 = FileSubscriberStore(path)
        assert store2.count() == 0

