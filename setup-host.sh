#!/bin/sh
set -eu
# Run on the Linux host as the account that will run the controller.
printf '%s\n' "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"0b4d\", ATTR{idProduct}==\"112b\", OWNER=\"$(id -un)\", MODE=\"0600\"" | sudo tee /etc/udev/rules.d/70-cameo-controller.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=usb --attr-match=idVendor=0b4d --attr-match=idProduct=112b
sudo loginctl enable-linger "$(id -un)"
printf '%s\n' 'USB permissions and startup support configured.'
