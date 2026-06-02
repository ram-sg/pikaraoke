# Biaoke

<img width="588" height="339" alt="Image" src="https://i.ibb.co/Z6MTM4wt/biaoke-readme.png" />

Biaoke is a cross-platform karaoke server that brings the professional "KTV" experience to your home. It transforms your computer or Raspberry Pi into a dedicated karaoke station with a full-screen player and an instant web interface. Guests can join by simply scanning a QR code—no app downloads required—to browse your local library, manage the queue, and access countless karaoke hits from YouTube.

- 📱 Instant Mobile Remote: Search and queue songs from any smartphone—just scan and sing.
- 📺 Dedicated Player: High-performance splash screen that can be opened on any web browser for a true karaoke room feel.
- 🌐 YouTube & Local Media: Play your own files or access more from the web.
- 🎹 Live Pitch Shifting: Adjust the key of any song to match your vocal range.
- 🛠️ Admin Control: Manage the queue and settings via a password-protected admin mode.
- 🎯 Hyper-accurate vocal performance scoring system: (not really, it's random. But kind of fun!)
- 🐧 Lightweight & Versatile: Runs anywhere from a basic Raspberry Pi to a high-end PC.

Love Biaoke? This project is independently maintained and free for everyone to enjoy. If Biaoke has made your parties better and you'd like to help keep the project alive and growing, feel free to [buy me a coffee](https://www.buymeacoffee.com/vicwomg)! <br/><br/>
<a href="https://www.buymeacoffee.com/vicwomg" target="_blank"><img src="https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png" alt="Buy Me A Coffee" style="height: 41px !important;width: 174px !important;box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;-webkit-box-shadow: 0px 3px 2px 0px rgba(190, 190, 190, 0.5) !important;" ></a>

[![Conventional Commits](https://img.shields.io/badge/Conventional%20Commits-1.0.0-green.svg)](https://conventionalcommits.org)

## Table of Contents

- [Supported Devices / OS / Platforms](#supported-devices--os--platforms)
- [Quick Install](#quick-install)
- [Manual Installation](#manual-installation)
- [Usage](#usage)
- [Docker](#docker-instructions)
- [Screenshots](#screenshots)
- [Developing biaoke](#developing-biaoke)
- [Troubleshooting](#troubleshooting)

## Supported Devices / OS / Platforms

- OSX
- Windows
- Linux
- Raspberry Pi 4 or higher (Pi3 works ok with overclocking)

## Quick Install

For a streamlined installation that handles all dependencies (uv, ffmpeg, deno) and installs Biaoke, run the following in your terminal:

### Linux & macOS

```sh
curl -fsSL https://raw.githubusercontent.com/vicwomg/biaoke/master/build_scripts/install/install.sh | bash
```

### Windows (PowerShell)

```powershell
irm https://raw.githubusercontent.com/vicwomg/biaoke/master/build_scripts/install/install.ps1 | iex
```

After installation, you can launch biaoke from the command line with `biaoke` or from a desktop shortcut. Re-running the above command will update a previous biaoke installation to the latest version.

## Manual installation (advanced users)

### Prerequisites

- A modern web browser (Chrome/Chromium/Edge recommended)
- Python 3.10 or greater: [Python downloads](https://www.python.org/downloads/)
- FFmpeg (preferably a build with lib-rubberband for transposing): [FFmpeg downloads](https://ffmpeg.org/download.html)
- A js runtime installed to your PATH. [Node.js](https://nodejs.org/en/download/) is most common, [Deno](https://deno.com/) is probably easiest for non-developers.

### Install the biaoke package

We recommend installing biaoke via [uv](https://github.com/astral-sh/uv).

```sh
uv tool install biaoke
```

You may alternately use the standard python `pip install biaoke` installer if you are familiar with virtual environments or you are not concerned with global package isolation.

## Usage

Run biaoke from the command line with:

```sh
biaoke
```

Launches the player in "headed" mode via your default browser. Scan the QR code to connect mobile remotes. Use `biaoke --headless` to run as a background server for external browsers.

See the help command `biaoke --help` for available options.

To upgrade to the latest version of biaoke, run:

```sh
uv tool upgrade biaoke
```

## Docker instructions

Run Biaoke in Docker using the command below. Note the requirements for port mapping, LAN IP specification, and persistent volume mounts (set to ~/.biaoke in the example for simplicity):

```sh
docker run -p 5555:5555 \
  -v ~/biaoke-songs:/app/biaoke-songs \
  -v ~/.biaoke:/home/biaoke/.biaoke \
  vicwomg/biaoke:latest \
  -u http://<YOUR_LAN_IP>:5555
```

For more information and a configurable docker-compose example, [see official Dockerhub repo](https://hub.docker.com/r/vicwomg/biaoke)

## Screenshots

<div style="display: flex; flex-wrap: wrap;">
<img width="250" alt="biaoke-nowplaying" src="https://user-images.githubusercontent.com/4107190/95813193-2cd5c180-0ccc-11eb-89f4-11a69676dc6f.png">
<img width="250" alt="biaoke-queue" src="https://user-images.githubusercontent.com/4107190/95813195-2d6e5800-0ccc-11eb-8f00-1369350a8a1c.png">
<img width="250"  alt="biaoke-browse" src="https://user-images.githubusercontent.com/4107190/95813182-27787700-0ccc-11eb-82c8-fde7f0a631c1.png">
<img width="250"  alt="biaoke-search1" src="https://user-images.githubusercontent.com/4107190/95813197-2e06ee80-0ccc-11eb-9bf9-ddb24d988332.png">
<img width="250"  alt="biaoke-search2" src="https://user-images.githubusercontent.com/4107190/95813190-2ba49480-0ccc-11eb-84e3-f902cbd489a2.png">
<img width="400" height="300" alt="biaoke-tv2" src="https://user-images.githubusercontent.com/4107190/95813564-019fa200-0ccd-11eb-95e1-57a002c357a3.png">
</div>

## Developing biaoke

The Biaoke project utilizes `uv` for dependency management and local development.

- Install [uv](https://github.com/astral-sh/uv)
- Git clone this repo

From the biaoke directory:

```sh
# install dependencies and run biaoke from local code
uv run biaoke
```

See the [Biaoke development guide](https://github.com/vicwomg/biaoke/wiki/Biaoke-development-guide) for more details.

## Troubleshooting and guides

See the [TROUBLESHOOTING wiki](https://github.com/vicwomg/biaoke/wiki/FAQ-&-Troubleshooting) for help with issues.

There are also some great guides [on the wiki](https://github.com/vicwomg/biaoke/wiki/) to running biaoke in all manner of bizarre places including Android, Chromecast, and embedded TVs!
