from laptopguard.location import parse_mmcli_location


def test_parse_mmcli_gps_location():
    text = '''GPS | longitude: 78.486671 | latitude: 17.385044 | altitude: 530.0'''
    sample = parse_mmcli_location(text)
    assert sample is not None
    assert round(sample.latitude, 6) == 17.385044
    assert round(sample.longitude, 6) == 78.486671
    assert sample.source == 'modem-gps'
