from laptopguard.alerts import format_alert


def test_alert_contains_location_link_when_available():
    metadata = {'event': 'failed_auth', 'timestamp': '2026-09-14T12:00:00+00:00', 'location': {'latitude': 17.3, 'longitude': 78.4, 'source': 'modem-gps'}}
    subject, body = format_alert(metadata)
    assert 'failed_auth' in subject
    assert 'https://maps.google.com/?q=17.3,78.4' in body
