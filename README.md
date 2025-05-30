# klar

klar is a minimalist On-Screen Display (OSD) for Linux that shows visual
indicators for brightness, audio, and power events

- It requires almost zero configuration, simply start the program and use
  whatever tool you normally use to change volume or brightness
- Responds to dark/light theme switches
- Looks can be customized with CSS.

## Screencast

https://github.com/user-attachments/assets/25562f18-77d4-4d63-b0a6-3d2a97d845b7


## Installation

```
pipx install --system-site-packages git+https://github.com/isaksamsten/klar.git
```

> [!NOTE]
> You must use `--system-site-packages` to avoid having to build `pygobjects`
> from source. You also need to install the following system packages:
>
> - `python3-gobject`
> - `gtk4-layer-shell`
> - `libadwaita`
> - `python3-pulsectl`
>
> These are the names of the packages on Fedora.

## Configuration

`klar` can be configured through `config.toml` file in the
`$XDG_CONFIG_DIR/klar` (typically `~/.config/klar`). The default configuration is:

```toml
[appearance]
icon_size=80
system_theme="auto"

[appearance.animation.reveal]
duration=20

[appearance.animation.hide]
duration=200

[monitor.keyboard]
enabled=true
levels=16

[monitor.display]
enabled=true
levels=16

[monitor.pulseaudio]
enabled=true
levels=16

[monitor.power]
enabled=true
```

`klar` tries to guess the correct device for `monitor.display` and
`monitor.keyboard` but sometimes fails to detect the correct device. You can
manually specify the correct device as:

```toml
[monitor.keyboard]
enabled=true
device="/sys/class/leds/kbd_backlight/"
```

You can find the correct device by using `light -L` and check the `/sys/class/`
directory for the brightness controller.

To configure the style, place a `style.css` (for light mode) and
`style-dark.css` (for dark-mode) in the configuration directory.

To only change colors, define color variables (these are the default light mode
colors):

```css
:root {
  --bg-color: rgba(229, 229, 234, 0.7);
  --fg-color: rgb(72, 72, 74);
  --indicator-inactive-color: rgb(209, 209, 214);
  --indicator-active-color: rgb(99, 99, 102);
}
```

To change other aspects, the following items can be styled:

- `#klar` the main window (has a large padding to allow for shadows on `#main-view`)
- `#main-view` the main view
- `.icon` the status icon
- `#status-bar` the status bar below the icon
- `#status-segment` the individual segments
- `#status-segment.active` active segment ("filled")
- `#status-segment.warning` segments when the value is larger than max (e.g.,
  for PulseAudio)
