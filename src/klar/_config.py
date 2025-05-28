import os
from pathlib import Path
import importlib
import importlib.resources
from dataclasses import dataclass

from gi.repository import Gtk


def load_system_style(filename="style.css", priority=0):
    with importlib.resources.files("klar.resources").joinpath(filename).open("rb") as f:
        provider = Gtk.CssProvider()
        css_data = f.read()
        provider.load_from_data(css_data)
        return provider


def load_user_style(filename="style.css"):
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    user_css_path = os.path.join(config_home, "klar", filename)
    if os.path.isfile(user_css_path):
        with open(user_css_path, "rb") as f:
            user_provider = Gtk.CssProvider()
            css_data = f.read()
            user_provider.load_from_data(css_data)
            return user_provider
    return None


@dataclass
class BrightnessProvider:
    max_brightness: int
    brightness_file: str
    source: str


def guess_default_brightness_provider(base: Path) -> BrightnessProvider:
    if not base.is_dir():
        return None

    best = None
    best_max = -1
    for subdir in base.iterdir():
        max_brightness_file = subdir / "max_brightness"
        brightness_file = subdir / "brightness"

        if max_brightness_file.is_file() and brightness_file.is_file():
            with open(max_brightness_file) as f:
                max_brightness = int(f.read())

            if max_brightness > best_max:
                best = BrightnessProvider(
                    max_brightness=max_brightness,
                    brightness_file=brightness_file.as_posix(),
                    source=subdir.name,
                )
                best_max = max_brightness

    return best


DEFAULT_BRIGHTNESS_PROVIDER = guess_default_brightness_provider(
    Path("/sys", "class", "backlight")
)
DEFAULT_KEYBOARD_BRIGHTNESS_PROVIDER = guess_default_brightness_provider(
    Path("/sys", "class", "leds")
)
DEFAULT_CSS_PROVIDER = load_system_style(filename="style.css")
DEFAULT_DARK_CSS_PROVIDER = load_system_style(filename="style-dark.css")

DEFAULT_USER_CSS_PROVIDER = load_user_style(filename="style.css")
DEFAULT_DARK_USER_CSS_PROVIDER = load_user_style(filename="style-dark.css")
