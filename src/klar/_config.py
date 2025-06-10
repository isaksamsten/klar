import tomllib
import os
from pathlib import Path
import importlib
import importlib.resources
from dataclasses import dataclass
from typing import Tuple

from gi.repository import Gtk

import logging


logging.basicConfig()
logger = logging.getLogger(__name__)


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


def _guess_brightness_provider(base: Path) -> Tuple[str | None, int | None]:
    if not base.is_dir():
        return None

    best: Path | None = None
    best_max: int = -1
    for subdir in base.iterdir():
        max_brightness_file = subdir / "max_brightness"
        brightness_file = subdir / "brightness"

        if max_brightness_file.is_file() and brightness_file.is_file():
            with open(max_brightness_file) as f:
                max_brightness = int(f.read())

            if max_brightness > best_max:
                best = brightness_file
                best_max = max_brightness

    if best is not None:
        logger.info("Guessing brightness file %s", best)
    else:
        logger.error("Failed to guess brigness provider, please pass one explicitly")
    return best.as_posix(), best_max


def _get_max_brightness(file: Path) -> int | None:
    try:
        with open(file) as f:
            return int(f.read())
    except Exception:
        logger.exception("Failed to get maximum brightness for %s", file)
        return None


@dataclass
class MonitorBase:
    enabled: bool
    levels: int

    def __post_init__(self):
        if not isinstance(self.levels, int):
            logger.warning("levels must be an int, got %r", self.levels)
            self.levels = 16


@dataclass
class BrightnessConfig(MonitorBase):
    device: str
    max_brightness: int
    exponent: float

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.exponent, float):
            logger.warning("exponent must be a float, got %r", self.exponent)
            self.exponent = 1.0

        if not isinstance(self.max_brightness, int):
            logger.warning(
                "max_brightness must be an integer, got %r", self.max_brightness
            )


@dataclass
class PulseAudioConfig(MonitorBase):
    pass


@dataclass
class PowerConfig(MonitorBase):
    pass


@dataclass
class MonitorConfig:
    keyboard: BrightnessConfig
    display: BrightnessConfig
    power: PowerConfig
    pulseaudio: PulseAudioConfig


@dataclass
class RevealAnimationConfig:
    duration: int


@dataclass
class HideAnimationConfig:
    duration: int


@dataclass
class AnimationConfig:
    reveal: RevealAnimationConfig
    hide: HideAnimationConfig


@dataclass
class AppearanceConfig:
    icon_size: int
    system_theme: str
    animation: AnimationConfig
    bottom_margin: int


@dataclass
class KlarConfig:
    appearance: AppearanceConfig
    monitor: MonitorConfig


def _load_brightness_config(section: dict, base_path: Path):
    enabled = section.get("enabled", True)
    device = None
    max_brightness = None
    if enabled:
        if device := section.get("device"):
            max_brightness = _get_max_brightness(Path(device) / "max_brightness")
        else:
            device, max_brightness = _guess_brightness_provider(base_path)
    return BrightnessConfig(
        enabled=enabled and max_brightness is not None,
        device=device,
        max_brightness=max_brightness,
        levels=section.get("levels", 16),
        exponent=section.get("exponent", 1.0),
    )


def load_configuration(config_path=None):
    config_home = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    config_dir = os.path.join(config_home, "klar")
    if config_path is None:
        config_path = os.path.join(config_dir, "config.toml")
    if os.path.isfile(config_path):
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
    else:
        config = {}

    log_level = config.get("log_level", "WARN")
    if log_level not in ("ERROR", "WARN", "INFO", "DEBUG"):
        log_level = "WARN"

    logging.getLogger().setLevel(log_level)

    appearance_section = config.get("appearance", {})
    animation_section = appearance_section.get("animation", {})
    reveal_section = animation_section.get("reveal", {})
    hide_section = animation_section.get("hide", {})
    monitor_section = config.get("monitor", {})
    keyboard_section = monitor_section.get("keyboard", {})
    display_section = monitor_section.get("display", {})
    pulseaudio_section = monitor_section.get("pulseaudio", {})
    power_section = monitor_section.get("pulseaudio", {})

    display_brightness_config = _load_brightness_config(
        display_section, Path("/sys", "class", "backlight")
    )
    keyboard_brightness_config = _load_brightness_config(
        keyboard_section, Path("/sys", "class", "leds")
    )
    return KlarConfig(
        appearance=AppearanceConfig(
            icon_size=appearance_section.get("icon_size", 88),
            system_theme=appearance_section.get("system_theme", "auto"),
            bottom_margin=appearance_section.get("bottom_margin", 100),
            animation=AnimationConfig(
                reveal=RevealAnimationConfig(
                    duration=reveal_section.get("duration", 20)
                ),
                hide=HideAnimationConfig(duration=hide_section.get("duration", 20)),
            ),
        ),
        monitor=MonitorConfig(
            keyboard=keyboard_brightness_config,
            display=display_brightness_config,
            power=PowerConfig(enabled=power_section.get("enabled", True), levels=0),
            pulseaudio=PulseAudioConfig(
                enabled=pulseaudio_section.get("enabled", True),
                levels=pulseaudio_section.get("levels", 16),
            ),
        ),
    )


config = load_configuration()

DEFAULT_CSS_PROVIDER = load_system_style(filename="style.css")
DEFAULT_DARK_CSS_PROVIDER = load_system_style(filename="style-dark.css")

DEFAULT_USER_CSS_PROVIDER = load_user_style(filename="style.css")
DEFAULT_DARK_USER_CSS_PROVIDER = load_user_style(filename="style-dark.css")
