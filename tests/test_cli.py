from laptopguard.cli import build_parser


def test_cli_parses_hardening_audit():
    args = build_parser().parse_args(['hardening-audit'])
    assert args.command == 'hardening-audit'


def test_cli_parses_location_test():
    args = build_parser().parse_args(['location-test'])
    assert args.command == 'location-test'


def test_cli_parses_internal_lock_watch_user():
    args = build_parser().parse_args(['lock-watch-user'])
    assert args.command == 'lock-watch-user'
