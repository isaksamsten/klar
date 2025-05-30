import threading
import pulsectl
from typing import override
from gi.repository import Gio, GLib, GObject


class StatusModel(GObject.Object):
    value = GObject.Property(type=float, default=0)
    icon = GObject.Property(type=Gio.Icon, default=None)
    name: str
    levels: int

    def __init__(self, name: str, levels: int = 16):
        super().__init__()
        self.name = name
        self.levels = levels


class Monitor(GObject.Object):
    levels: int

    def __init__(self, levels: int = 0):
        super().__init__()
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
