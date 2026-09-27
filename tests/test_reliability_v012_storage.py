from pathlib import Path

from laptopguard.location import LocationSample, cached_wifi_location, store_wifi_location
from laptopguard.queue_store import EncryptedQueue
from laptopguard.storage import StorageReserve


def test_wifi_location_cache_matches_multiple_observed_bssids(tmp_path: Path):
    cache = tmp_path / 'wifi-cache.json'
    points = [{'macAddress': '00:11:22:33:44:55'}, {'macAddress': '00:11:22:33:44:66'}, {'macAddress': '00:11:22:33:44:77'}]
    store_wifi_location(cache, points, LocationSample(17.3, 78.4, 'wifi-beacondb', 30).normalized())
    observed = [{'macAddress': '00:11:22:33:44:55'}, {'macAddress': '00:11:22:33:44:66'}, {'macAddress': '00:aa:bb:cc:dd:ee'}]
    sample = cached_wifi_location(cache, observed)
    assert sample is not None
    assert sample.source == 'wifi-cache'
    assert sample.latitude == 17.3


def test_wifi_cache_rejects_single_ap_match(tmp_path: Path):
    cache = tmp_path / 'wifi-cache.json'
    points = [{'macAddress': '00:11:22:33:44:55'}, {'macAddress': '00:11:22:33:44:66'}]
    store_wifi_location(cache, points, LocationSample(17.3, 78.4, 'wifi-beacondb', 30).normalized())
    assert cached_wifi_location(cache, [{'macAddress': '00:11:22:33:44:55'}]) is None


def test_storage_reserve_can_be_released(tmp_path: Path):
    reserve = StorageReserve(tmp_path / '.reserve', bytes_to_reserve=4096)
    reserve.ensure()
    assert reserve.path.exists()
    reserve.release()
    assert not reserve.path.exists()


def test_queue_prunes_oldest_when_requested(tmp_path: Path):
    queue = EncryptedQueue(tmp_path / 'queue', tmp_path / 'key')
    for i in range(5):
        queue.enqueue({'subject': str(i), 'body': 'x'}, [])
    queue.prune_oldest(2)
    assert len(queue.items()) == 3
