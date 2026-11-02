# Cameo Automator

A free, local-network web controller for the Silhouette Cameo 2. Run it on Linux alongside OctoPrint; prepare SVG designs in Inkscape on your everyday computer.

## Current features

- Live USB connection and machine status, polled every three seconds.
- SVG upload and preview of the processed paths actually used for motion.
- Uniform scaling, placement in millimeters, bounds validation within 304 × 304 mm.
- Travel-only test, pen, and cut modes; speed, pressure, and multiple passes.
- Carriage travel to zero or the documented 304 mm usable width.
- Cancel remaining movements after the current buffered movement completes.
- A user systemd service for automatic startup.

Travel-only mode sends no initialization, pressure, tool-selection, or draw commands. Carriage travel returns the material-feed coordinate to zero too. Speed range is 1–10. Cut mode currently assumes a standard 0.9 mm blade offset; blade depth is adjusted manually.

## Installation on Linux Mint / Ubuntu

```sh
sudo apt install python3-venv libusb-1.0-0
# Put this repository at ~/cameo-controller
cd ~/cameo-controller
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sh setup-host.sh
mkdir -p ~/.config/systemd/user
cp cameo-controller.service ~/.config/systemd/user/
```

Create `host.env` with the host's actual LAN address:

```text
CAMEO_BIND=YOUR_LAN_IP
CAMEO_HOSTS=YOUR_LAN_IP,127.0.0.1,localhost
```

Then start the service:

```sh
systemctl --user daemon-reload
systemctl --user enable --now cameo-controller
```

Open `http://YOUR_LAN_IP:8091`. Configure a DHCP reservation so the address stays stable. If a host firewall blocks access, permit TCP 8091 only from the intended local network.

The USB setup grants only the installing account access to vendor/product `0b4d:112b`. It also enables user-service startup after logout. It does not change OctoPrint.

## Design workflow

Trace bitmap images in Inkscape, remove the original bitmap, convert text and clones to paths, and save SVG. Upload, check dimensions and all paths, load the material and tool, and explicitly confirm readiness before starting. SVG width/height and viewBox determine physical dimensions. Shapes are sampled into line segments and previewed using the same rounded 0.05 mm coordinates sent to the machine.

## Limits and operational status

This is an early controller, not a mature replacement for commercial cutting software. Basic USB status and carriage/circle motion were demonstrated on a Cameo 2 during development. Automated tests verify SVG sizing, transform handling, bounds, request confirmation, and travel packets. Full controller pen/cut jobs, cancellation during real cutting, and reboot recovery still need physical acceptance testing. Start with a small tool-free motion test.

- Cancellation is **not an emergency stop**: buffered motion completes first. Use the machine controls or power switch for an immediate stop.
- No automatic resume after restart or USB interruption. Uploaded designs and job state are in memory.
- No registration-mark print-and-cut alignment, automatic material detection, nesting, or persistent queue yet.
- Original SVG colors, fills, and stroke widths do not select operations. Every supported visible shape becomes a followed path.
- Unsupported text, images, clones, clipping, masks, scripts, and linked content are rejected. Convert/remove these in Inkscape first.
- Restricted to a 304 mm square area for the first version, even with larger mats.
- The web interface is for a **trusted LAN**. It uses request tokens and host validation to limit cross-site requests, but does not provide user authentication or HTTPS. Do not expose it directly to the Internet.
- Keep hands and cleaning materials clear during movement. Manual loading and checking remain necessary.

## Verification and maintenance

```sh
.venv/bin/python -m unittest -v
systemctl --user status cameo-controller
journalctl --user -u cameo-controller -n 50
```

## Roadmap

Physical acceptance tests, authenticated access, durable job history, improved path sampling, configurable material area and blade offsets, and an optional combined workshop landing page linking to OctoPrint.

## Protocol references

Cameo protocol behavior was checked against the GPLv2 [inkscape-silhouette driver](https://github.com/fablabnbg/inkscape-silhouette), particularly its Cameo 2 USB IDs, 0.05 mm units, M/D commands, status query, and speed/pressure ranges. This repository uses its own minimal transport and web interface; it does not vendor that driver.
