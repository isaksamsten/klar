import logging
from ctypes import CDLL
import math
from typing import Generator, Iterable

CDLL("libgtk4-layer-shell.so.0")
import gi  # noqa: E402

gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import time  # noqa: E402

from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

from ._config import (  # noqa: E402
    DEFAULT_CSS_PROVIDER,
    DEFAULT_DARK_CSS_PROVIDER,
    DEFAULT_DARK_USER_CSS_PROVIDER,
    DEFAULT_USER_CSS_PROVIDER,
    config,
)

from ._monitor import (  # noqa: E402
    Monitor,
    PulseAudioMonitor,
    PowerMonitor,
    BrightnessMonitor,
    StatusModel,
)

logger = logging.getLogger(__name__)


def ease_out_cubic(t):
    return 1 - pow(1 - t, 3)


class GenericTransition:
    def __init__(
        self, method, *, before, setter, initial, target, duration=200, easing=None
    ):
        self._timer_id = None
        self.initial = initial
        self.target = target
        self._current = None
        self.method = method
        self.setter = setter
        self.before = before
        self.duration = duration
        self.easing = easing

    def __call__(self, *args, **kwargs):
        before = self.before(*args, **kwargs)
        if hasattr(self.duration, "__call__"):
            duration = self.duration(*args, **kwargs)
        else:
            duration = self.duration

        if not before:
            initial, target = self.target, self.initial
        else:
            initial = self.initial
            target = self.target

        self._current = initial
        easing = self.easing
        if easing is None:
            easing = ease_out_cubic

        if duration == 0:
            self.setter(target)
            self.method(*args, **kwargs)
            return

        if before:
            self.setter(initial)
            self.method(*args, **kwargs)

        def idle_add():
            delta = target - initial
            start_time = time.monotonic()

            def do_animation():
                elapsed = (time.monotonic() - start_time) * 1000
                t = min(elapsed / duration, 1.0)
                eased_t = easing(t)
                self._current = initial + delta * eased_t
                if t < 1.0:
                    self.setter(self._current)
                    return True
                else:
                    self._timer_id = None
                    self._current = None
                    self.setter(target)
                    if not before:
                        self.method(*args, **kwargs)
                    return False

            if self._timer_id is not None:
                GLib.source_remove(self._timer_id)

            self._timer_id = GLib.timeout_add(16, do_animation)

        GLib.idle_add(idle_add)


class StatusSegment(Gtk.Box):
    def __init__(self, height=2, width=-1):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL)
        self.set_name("status-segment")
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(width, height)

    def set_active(self, active):
        if active:
            self.add_css_class("active")
        else:
            self.remove_css_class("active")

    def set_warning(self, warning):
        if warning:
            self.add_css_class("warning")
        else:
            self.remove_css_class("warning")


class StatusBar(Gtk.Box):
    def __init__(self, levels=10, exponent=1.0):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=1, name="status-bar"
        )
        self.levels = levels
        self.exponent = exponent
        self.set_hexpand(True)
        for i in range(levels):
            self.append(StatusSegment(height=6))

    def __iter__(self) -> Iterable[StatusSegment]:
        current = self.get_first_child()
        while current is not None:
            yield current
            current = current.get_next_sibling()

    def set_level(self, level: float):
        level = max(0.0, min(1.0, level))
        level = level ** (1 / self.exponent)
        filled_levels = math.floor(self.levels * level)
        for i, status_segment in enumerate(list(self)):
            status_segment.set_active(i < filled_levels)
            status_segment.set_warning(level > 1.0)


class StatusIndicator(Gtk.Box):
    model: StatusModel

    def __init__(
        self,
        *,
        model: StatusModel,
        icon_size: int = 88,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, name=model.name)
        self.image = Gtk.Image.new()
        self.image.set_pixel_size(icon_size)
        self.image.add_css_class("icon")
        self.append(self.image)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.CENTER)

        if model.levels > 0:
            self.status_bar = StatusBar(model.levels, model.exponent)
            self.append(self.status_bar)
        else:
            self.status_bar = None
        self._model_value_id = None
        self._model_icon_id = None
        self.model = model
        self._model_value_id = self.model.connect(
            "notify::value", lambda model, prop: self.on_value_change(model.value)
        )
        self._model_icon_id = self.model.connect(
            "notify::icon", lambda model, prop: self.on_icon_change(model.icon)
        )
        self.on_value_change(model.value)
        self.on_icon_change(model.icon)

    def on_value_change(self, progress):
        if self.status_bar is not None:
            self.status_bar.set_level(progress)

    def on_icon_change(self, icon):
        if icon is not None:
            self.image.set_from_gicon(icon)


class KlarWindow(Gtk.Window):
    def __init__(self, app) -> None:
        super().__init__(application=app)
        self.set_name("klar")
        main_view = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        main_view.set_name("main-view")
        self.stack = Gtk.Stack(
            hhomogeneous=True,
            vhomogeneous=True,
            transition_type=Gtk.StackTransitionType.NONE,
        )
        main_view.append(self.stack)
        self.set_child(main_view)

        def show_hide_duration(visible):
            return (
                config.appearance.animation.reveal.duration
                if visible
                else config.appearance.animation.hide.duration
            )

        self.set_visible = GenericTransition(
            self.set_visible,
            before=lambda x: x,
            setter=self.set_opacity,
            initial=0.01,
            target=1.0,
            duration=show_hide_duration,
        )

    def add_status_indicator(self, status_indicator: StatusIndicator):
        self.stack.add_named(status_indicator, status_indicator.get_name())

    def switch_to(self, name):
        self.stack.set_visible_child_name(name)


def create_monitors() -> Generator[Monitor]:
    if config.monitor.display.enabled:
        yield BrightnessMonitor(
            "display-brightness-symbolic",
            file=config.monitor.display.device,
            max_brightness=config.monitor.display.max_brightness,
            levels=config.monitor.display.levels,
            exponent=config.monitor.display.exponent,
        )

    if config.monitor.keyboard.enabled:
        yield BrightnessMonitor(
            "keyboard-brightness-symbolic",
            file=config.monitor.keyboard.device,
            max_brightness=config.monitor.keyboard.max_brightness,
            levels=config.monitor.keyboard.levels,
            exponent=config.monitor.keyboard.exponent,
        )

    if config.monitor.power.enabled:
        yield PowerMonitor()

    if config.monitor.pulseaudio.enabled:
        yield PulseAudioMonitor(levels=config.monitor.pulseaudio.levels)


class KlarApp(Adw.Application):
    window: KlarWindow | None

    def __init__(self) -> None:
        super().__init__(application_id="se.samsten.klar")
        self.window = None
        self._timer_id = None

    def do_activate(self):
        def show_callback(model, _prop):
            if self.window is None:
                return

            if self._timer_id is None:
                self.window.set_visible(True)
                display = Gdk.Display.get_default()
                surface = self.window.get_surface()
                if display is not None and surface is not None:
                    monitor = display.get_monitor_at_surface(surface)
                    LayerShell.set_monitor(self.window, monitor)
            else:
                GLib.source_remove(self._timer_id)

            self.window.switch_to(model.name)

            def hide():
                if self.window is not None:
                    self.window.set_visible(False)
                self._timer_id = None
                return False

            self._timer_id = GLib.timeout_add(1000, hide)

        self.window = KlarWindow(self)
        for monitor in create_monitors():
            monitor.start()
            if monitor.is_started():
                logger.info(
                    "%s has been started and is listening", monitor.__class__.__name__
                )
                status_model = monitor.new_model()
                status_model.connect("notify", show_callback)
                status_indicator = StatusIndicator(
                    model=status_model, icon_size=config.appearance.icon_size
                )
                self.window.add_status_indicator(status_indicator)
            else:
                logger.info("%s could not be started", monitor.__class__.__name__)

        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "klar")
        LayerShell.set_layer(self.window, LayerShell.Layer.OVERLAY)
        if config.appearance.bottom_margin >= 0:
            LayerShell.set_anchor(self.window, LayerShell.Edge.BOTTOM, True)
            LayerShell.set_margin(
                self.window, LayerShell.Edge.BOTTOM, config.appearance.bottom_margin
            )
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.NONE)


def main():
    app = KlarApp()
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            DEFAULT_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        if DEFAULT_USER_CSS_PROVIDER is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                DEFAULT_USER_CSS_PROVIDER,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2,
            )
    else:
        logger.error("Could not find default display")

    if app.get_style_manager().get_dark() or config.appearance.system_theme == "dark":
        _set_dark_style()

    if config.appearance.system_theme == "auto":
        app.get_style_manager().connect("notify::dark", on_dark)

    app.register(None)
    if app.get_is_remote():
        logger.info("klar is already running...")
    else:
        app.run(None)


def on_dark(style_manager, _prop):
    if style_manager.get_dark():
        _set_dark_style()
    else:
        display = Gdk.Display.get_default()
        if display is not None:
            Gtk.StyleContext.remove_provider_for_display(
                display, DEFAULT_DARK_CSS_PROVIDER
            )
            if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
                Gtk.StyleContext.remove_provider_for_display(
                    display, DEFAULT_DARK_USER_CSS_PROVIDER
                )
        else:
            logger.error("Could not find default display")


def _set_dark_style():
    display = Gdk.Display.get_default()
    if display is not None:
        Gtk.StyleContext.add_provider_for_display(
            display,
            DEFAULT_DARK_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
        )
        if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
            Gtk.StyleContext.add_provider_for_display(
                display,
                DEFAULT_DARK_USER_CSS_PROVIDER,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3,
            )
    else:
        logger.error("Could not find default display")
