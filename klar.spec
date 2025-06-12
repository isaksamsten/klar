%define version 0.2.0

Name:           klar
Version:        %{version}
Release:        1%{?dist}
Summary:        A generic OSD

License:        MIT
URL:            https://github.com/isaksamsten/klar
Source0:        %{url}/archive/%{version}/%{name}-%{version}.tar.gz

BuildArch:      noarch

BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-gobject
BuildRequires:  python3-hatchling
BuildRequires:  python3-pip
Requires:       python3-gobject
Requires:       gtk4-layer-shell
Requires:       gtk4
Requires:       libadwaita
Requires:       python3-pulsectl

%description
klar is a minimalist On-Screen Display (OSD) for Linux that shows visual
indicators for brightness, audio, and power events

%prep
%autosetup -n %{name}-%{version}

%build
%pyproject_wheel

%install
%pyproject_install

%files
%license LICENSE
%doc README.md
%{_bindir}/klar
%{python3_sitelib}/klar*

%changelog
* Thu June 12 2025 Isak Samsten <isak@samsten.se> - 0.2.0-1
- Add an option to place the OSD aligned with the bottom of the screen
- Add exponent for more natural brightness control notification
- Ensure that the width of the main window stays constant
- Improve default theme

* Fri May 30 2025 Isak Samsten <isak@samsten.se> - 0.1.0-1
- Initial release
