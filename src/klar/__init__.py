from ctypes import CDLL
from decimal import MAX_PREC
from typing import Callable, Generator, Iterable, List, override

CDLL("libgtk4-layer-shell.so.0")
import gi

gi.require_version("Gtk4LayerShell", "1.0")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

import threading
import time

import pulsectl

from ._config import (
    DEFAULT_CSS_PROVIDER,
    DEFAULT_USER_CSS_PROVIDER,
    DEFAULT_DARK_CSS_PROVIDER,
    DEFAULT_DARK_USER_CSS_PROVIDER,
    config,
)


from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk
from gi.repository import Gtk4LayerShell as LayerShell


class Monitor(GObject.Object):
    levels: int

    def __init__(self, levels: int = 0):
        super().__init__()
        print(self.__class__, levels)
        self.levels = levels

    def start(self) -> None:
        self.do_start()

    def close(self) -> None:
        self.do_stop()

    def is_started(self) -> bool:
        return False

    def do_stop(self):
        raise NotImplementedError()

    def do_start(self):
        raise NotImplementedError()

    def new_model(self):
        raise NotImplementedError()


class FileMonitor(Monitor):
    def __init__(self, file: Gio.File | None, *, levels: int) -> None:
        super().__init__(levels=levels)
        self._file = file
        self._file_monitor: Gio.FileMonitor | None = None
        self._file_monitor_id: int | None = None

    @override
    def do_start(self):
        if self._file is not None:
            self._file_monitor = self._file.monitor(Gio.FileMonitorFlags.NONE, None)
            self._file_monitor_id = self._file_monitor.connect(
                "changed", self._on_file_change
            )

    @override
    def is_started(self) -> bool:
        return self._file is not None

    @override
    def do_stop(self) -> None:
        if self._file is not None:
            self._file_monitor.cancel()
            self._file_monitor.disconnect(self._file_monitor_id)
            self._file_monitor_id = None
            self._file_monitor = None
            self._file = None

    def _on_file_change(self, monitor, file, other_file, event_type):
        if event_type == Gio.FileMonitorEvent.CHANGES_DONE_HINT:
            with open(file) as file:
                self.on_change(file.read())

    def on_change(self, data: str) -> None:
        pass


class BrightnessMonitor(FileMonitor):
    brightness = GObject.Property(type=float, default=0.0)

    def __init__(self, icon, *, file: str, max_brightness: int, levels: int):
        super().__init__(Gio.File.new_for_path(file), levels=levels)
        self.icon = icon
        self.max_brightness = max_brightness

    @override
    def on_change(self, data: str) -> None:
        self.brightness = int(data) / self.max_brightness

    def new_model(self):
        path = self._file.get_path()
        if not self.is_started():
            raise ValueError(f"BrightnessMonitor for {path} has not been started")

        model = StatusModel(f"brightness-{path}", self.levels)
        model.icon = Gio.ThemedIcon.new(self.icon)
        self.bind_property("brightness", model, "value")
        return model


class PowerMonitor(Monitor):
    connected = GObject.Property(type=bool, default=False)

    def __init__(self) -> None:
        super().__init__()
        self._dbus_ac_proxy = None
        self._dbus_batter_proxy = None
        self._dbus_ac_proxy_id = None

    def _get_ac_and_battery_proxy(
        self,
    ) -> tuple[Gio.DBusProxy | None, Gio.DBusProxy | None]:
        upower_proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM,
            Gio.DBusProxyFlags.NONE,
            None,
            "org.freedesktop.UPower",
            "/org/freedesktop/UPower",
            "org.freedesktop.UPower",
            None,
        )

        result = upower_proxy.call_sync(
            "EnumerateDevices", None, Gio.DBusCallFlags.NONE, -1, None
        )

        ac_device_proxy = None
        battery_device_proxy = None
        for obj_path in result.unpack()[0]:
            device_proxy = Gio.DBusProxy.new_for_bus_sync(
                Gio.BusType.SYSTEM,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.UPower",
                obj_path,
                "org.freedesktop.UPower.Device",
                None,
            )
            typ = device_proxy.get_cached_property("Type")
            if ac_device_proxy is None and typ is not None and typ.unpack() == 1:
                ac_device_proxy = device_proxy
            elif battery_device_proxy is None and typ is not None and typ.unpack() == 2:
                battery_device_proxy = device_proxy

            if ac_device_proxy is not None and battery_device_proxy is not None:
                break

        return ac_device_proxy, battery_device_proxy

    @override
    def do_start(self):
        self._dbus_ac_proxy, self._dbus_batter_proxy = self._get_ac_and_battery_proxy()
        if self._dbus_ac_proxy is not None:
            self._dbus_ac_proxy_id: int = self._dbus_ac_proxy.connect(
                "g-properties-changed", self._on_properties_changed
            )

    @override
    def is_started(self):
        return self._dbus_ac_proxy is not None

    @override
    def do_stop(self):
        if self._dbus_ac_proxy:
            self._dbus_ac_proxy.disconnect(self._dbus_ac_proxy_id)

    def _on_properties_changed(self, proxy, changed, invalidated):
        if "Online" in changed.keys():
            self.connected = changed["Online"]

    @override
    def new_model(self):
        if not self.is_started():
            raise ValueError()

        model = StatusModel("ac", levels=0)

        def update_icon(binding, prop):
            percentage = 0
            if self._dbus_batter_proxy is not None:
                if self._dbus_batter_proxy:
                    perc_variant = self._dbus_batter_proxy.get_cached_property(
                        "Percentage"
                    )
                    if perc_variant is not None:
                        percentage = perc_variant.unpack()

            if self.connected:
                if percentage >= 95:
                    icon_name = "battery-level-100-charging-symbolic"
                elif percentage >= 75:
                    icon_name = "battery-level-80-charging-symbolic"
                elif percentage >= 55:
                    icon_name = "battery-level-60-charging-symbolic"
                elif percentage >= 35:
                    icon_name = "battery-level-40-charging-symbolic"
                elif percentage >= 15:
                    icon_name = "battery-level-20-charging-symbolic"
                else:
                    icon_name = "battery-level-10-charging-symbolic"
            else:
                if percentage >= 95:
                    icon_name = "battery-level-100-symbolic"
                elif percentage >= 75:
                    icon_name = "battery-level-80-symbolic"
                elif percentage >= 55:
                    icon_name = "battery-level-60-symbolic"
                elif percentage >= 35:
                    icon_name = "battery-level-40-symbolic"
                elif percentage >= 15:
                    icon_name = "battery-level-20-symbolic"
                else:
                    icon_name = "battery-level-10-symbolic"

            model.icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)

        self.connect("notify::connected", update_icon)
        return model


class PulseAudioMonitor(Monitor):
    volume = GObject.Property(type=float, default=0.0)
    mute = GObject.Property(type=bool, default=False)
    current_sink = GObject.Property(type=str, default="")

    def __init__(self, *, levels: int) -> None:
        super().__init__(levels=levels)

        self._timers_lock = threading.Lock()
        self._timers = {}
        self._pulse_listen = pulsectl.Pulse(
            "klar-pulse-daemon-listen", threading_lock=True, connect=False
        )
        self._pulse_query = pulsectl.Pulse(
            "klar-pulse-daemon-query", threading_lock=True, connect=False
        )

        self._pulse_event_listen_thread = threading.Thread(
            None, self._pulse_listen.event_listen, daemon=True
        )
        self._is_started = False

    def do_start(self):
        try:
            self._pulse_listen.connect()
            self._pulse_query.connect()
            self._pulse_listen.event_mask_set("sink", "source")
            self._pulse_listen.event_callback_set(self._on_pulse_event_change)
            self._pulse_event_listen_thread.start()
        finally:
            self._is_started = True

    def do_stop(self):
        self._pulse_listen.close()
        self._pulse_query.close()
        self._pulse_event_listen_thread.join()

    @override
    def is_started(self):
        return self._is_started

    def _on_pulse_event_change(self, ev):
        with self._timers_lock:
            if index := self._timers.get(ev.index):
                GLib.source_remove(index)

            # We need to debounce otherwise we get triggered on
            # multiple events. 20ms seems to be ok...
            self._timers[ev.index] = GLib.timeout_add(
                20, self._on_pulse_event_timeout, ev.index
            )

    def _on_pulse_event_timeout(self, index):
        try:
            with self._timers_lock:
                del self._timers[index]

            sink = self._pulse_query.sink_default_get()
            volume = sink.volume
            if self.current_sink == "" or self.mute != sink.mute:
                self.mute = sink.mute

            if self.volume != volume.value_flat:
                self.volume = volume.value_flat

            if self.current_sink != sink.name:
                self.current_sink = sink.name
        except Exception:
            pass
        return False

    def new_model(self):
        if not self._pulse_event_listen_thread.is_alive():
            raise ValueError("PulseAudioMonitor has not been started")

        model = StatusModel("pulse", self.levels)

        def volume_to_icon_name(volume):
            icon_name = "audio-volume-low-symbolic"
            if volume > 1.0:
                icon_name = "audio-volume-overamplified-symbolic"
            elif volume > 0.66:
                icon_name = "audio-volume-high-symbolic"
            elif volume > 0.33:
                icon_name = "audio-volume-medium-symbolic"
            elif volume <= 0.0:
                icon_name = "audio-volume-muted-symbolic"
            return icon_name

        def update_icon(binding, prop):
            if self.mute:
                icon_name = "audio-volume-muted-symbolic"
            else:
                icon_name = volume_to_icon_name(self.volume)
            model.icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)

        def transform_volume_to_icon(binding, volume):
            if not self.mute:
                icon_name = volume_to_icon_name(volume)
                model.icon = Gio.ThemedIcon.new_with_default_fallbacks(icon_name)

        self.bind_property("volume", model, "value")
        self.bind_property(
            "volume", model, "icon", transform_to=transform_volume_to_icon
        )
        self.connect("notify::mute", update_icon)
        update_icon(None, None)
        return model


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


class StatusModel(GObject.Object):
    value = GObject.Property(type=float, default=0)
    icon = GObject.Property(type=Gio.Icon, default=None)
    name: str
    levels: int

    def __init__(self, name: str, levels: int = 16):
        super().__init__()
        self.name = name
        self.levels = levels


class StatusBar(Gtk.Box):
    def __init__(self, levels=10):
        super().__init__(
            orientation=Gtk.Orientation.HORIZONTAL, spacing=2, name="status-bar"
        )
        self.levels = levels
        self.set_hexpand(True)
        for i in range(levels):
            self.append(StatusSegment(height=10))

    def __iter__(self) -> Iterable[StatusSegment]:
        current = self.get_first_child()
        while current is not None:
            yield current
            current = current.get_next_sibling()

    def set_level(self, level: float):
        filled_levels = int(round(max(0.0, min(1.0, level)) * self.levels))
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
            self.status_bar = StatusBar(model.levels)
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
        )

    if config.monitor.keyboard.enabled:
        yield BrightnessMonitor(
            "keyboard-brightness-symbolic",
            file=config.monitor.keyboard.device,
            max_brightness=config.monitor.keyboard.max_brightness,
            levels=config.monitor.keyboard.levels,
        )

    if config.monitor.power.enabled:
        yield PowerMonitor()

    if config.monitor.pulseaudio.enabled:
        yield PulseAudioMonitor(levels=config.monitor.pulseaudio.levels)


class KlarApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id="se.samsten.klar")
        self.window = None
        self._timer_id = None

    def do_activate(self):
        def show_callback(model, prop):
            if self._timer_id is None:
                self.window.set_visible(True)
                display = Gdk.Display.get_default()
                monitor = display.get_monitor_at_surface(self.window.get_surface())
                LayerShell.set_monitor(self.window, monitor)
            else:
                GLib.source_remove(self._timer_id)

            self.window.switch_to(model.name)

            def hide():
                self.window.set_visible(False)
                self._timer_id = None
                return False

            self._timer_id = GLib.timeout_add(1000, hide)

        self.window = KlarWindow(self)
        for monitor in create_monitors():
            monitor.start()
            if monitor.is_started():
                status_model = monitor.new_model()
                status_model.connect("notify", show_callback)
                status_indicator = StatusIndicator(
                    model=status_model, icon_size=config.appearance.icon_size
                )
                self.window.add_status_indicator(status_indicator)

        LayerShell.init_for_window(self.window)
        LayerShell.set_namespace(self.window, "klar")
        LayerShell.set_layer(self.window, LayerShell.Layer.OVERLAY)
        LayerShell.auto_exclusive_zone_enable(self.window)
        LayerShell.set_keyboard_mode(self.window, LayerShell.KeyboardMode.NONE)


def main():
    app = KlarApp()
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        DEFAULT_CSS_PROVIDER,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )
    if DEFAULT_USER_CSS_PROVIDER is not None:
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            DEFAULT_USER_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 2,
        )

    if app.get_style_manager().get_dark() or config.appearance.system_theme == "dark":
        _set_dark_style()

    if config.appearance.system_theme == "dark":
        app.get_style_manager().connect("notify::dark", on_dark)

    app.register(None)
    app.run()


def on_dark(style_manager, prop):
    if style_manager.get_dark():
        _set_dark_style()
    else:
        Gtk.StyleContext.remove_provider_for_display(
            Gdk.Display.get_default(), DEFAULT_DARK_CSS_PROVIDER
        )
        if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
            Gtk.StyleContext.remove_provider_for_display(
                Gdk.Display.get_default(), DEFAULT_DARK_USER_CSS_PROVIDER
            )


def _set_dark_style():
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        DEFAULT_DARK_CSS_PROVIDER,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1,
    )
    if DEFAULT_DARK_USER_CSS_PROVIDER is not None:
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            DEFAULT_DARK_USER_CSS_PROVIDER,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 3,
        )
