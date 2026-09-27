from pathlib import Path
from laptopguard.evidence import sha256_file, write_metadata


def test_write_metadata_hashes_existing_attachments(tmp_path: Path):
    photo = tmp_path / 'photo.jpg'
    photo.write_bytes(b'abc')
    target = tmp_path / 'metadata.json'
    data = write_metadata(target, {'event': 'failed_auth'}, [photo])
    assert data['sha256']['photo.jpg'] == sha256_file(photo)
    assert target.is_file()
