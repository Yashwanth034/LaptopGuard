from pathlib import Path
from laptopguard.tamper import TamperBaseline


def test_tamper_baseline_detects_file_change(tmp_path: Path):
    target = tmp_path / 'passwd'
    target.write_text('before')
    baseline = TamperBaseline(tmp_path / 'baseline.json', [target])
    assert baseline.check() == []
    target.write_text('after')
    changes = baseline.check()
    assert len(changes) == 1
    assert changes[0].path == str(target)


def test_new_monitored_path_is_seeded_without_false_alert(tmp_path: Path):
    first = tmp_path / 'first'
    second = tmp_path / 'second'
    first.write_text('a')
    second.write_text('b')
    baseline = TamperBaseline(tmp_path / 'baseline.json', [first])
    assert baseline.check() == []
    expanded = TamperBaseline(tmp_path / 'baseline.json', [first, second])
    assert expanded.check() == []
    second.write_text('changed')
    changes = expanded.check()
    assert [c.path for c in changes] == [str(second)]
