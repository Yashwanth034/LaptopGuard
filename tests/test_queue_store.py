from pathlib import Path
from laptopguard.queue_store import EncryptedQueue


def test_queue_is_encrypted_and_round_trips(tmp_path: Path):
    key = tmp_path / 'queue.key'
    queue = EncryptedQueue(tmp_path / 'queue', key)
    attachment = tmp_path / 'photo.jpg'
    attachment.write_bytes(b'not-a-real-jpeg-secret')

    item = queue.enqueue({'subject': 'alert', 'body': 'hello'}, [attachment])
    raw = item.read_bytes()
    assert b'not-a-real-jpeg-secret' not in raw

    payload, files = queue.read(item)
    assert payload['subject'] == 'alert'
    assert files['photo.jpg'] == b'not-a-real-jpeg-secret'
