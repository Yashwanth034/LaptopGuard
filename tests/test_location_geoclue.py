from laptopguard.location import parse_geoclue_output


def test_parse_geoclue_output():
    sample = parse_geoclue_output('Latitude: 17.385044\nLongitude: 78.486671\nAccuracy: 25.0')
    assert sample is not None
    assert sample.source == 'geoclue'
    assert sample.accuracy_m == 25.0
