from laptopguard.brightness import BrightnessController


class Result:
    def __init__(self, stdout=''):
        self.stdout = stdout


def test_boost_restores_previous_brightness_even_on_error():
    calls = []

    def runner(args, **kwargs):
        calls.append(args)
        if args[1:] == ['-m', '-c', 'backlight']:
            return Result('intel_backlight,backlight,400,1000,40%\n')
        return Result()

    ctl = BrightnessController(runner=runner)
    try:
        with ctl.boosted(100):
            raise RuntimeError('capture failed')
    except RuntimeError:
        pass

    assert ['brightnessctl', '-c', 'backlight', 'set', '100%'] in calls
    assert ['brightnessctl', '-c', 'backlight', 'set', '40%'] in calls
