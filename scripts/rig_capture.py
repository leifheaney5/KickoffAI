#!/usr/bin/env python3
"""rig_capture.py — the capture agent that runs ON the camera rig.

Records the match to local storage **first** and streams it second. That order is
the whole reliability argument: if the wifi drops, the app crashes, or the laptop
runs out of battery, the footage is still on the rig's SSD. A rig that only
streams is a rig that loses matches.

Runs on a Raspberry Pi with a camera module, but nothing here is Pi-specific —
it drives ffmpeg, so any machine with a camera and ffmpeg works, including a
laptop with a webcam for testing.

    # On the rig
    python3 scripts/rig_capture.py --out /media/ssd/matches --serve

    # Test on a laptop, no rig needed
    python3 scripts/rig_capture.py --input 0 --out /tmp/rig --duration 30

The app consumes the stream exactly as it consumes a Veo feed: point Camera &
Feed at the printed RTSP/HLS URL. No app changes are needed for that — a fixed
rig is just a stream that happens not to move.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

_STOP = False


def _request_stop(signum, frame):  # noqa: ARG001
    global _STOP
    _STOP = True


def lan_ip() -> str:
    """This machine's address on the LAN, for printing a reachable URL."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


def default_input() -> str:
    """The camera to record from.

    Prefers the Pi camera stack when present, falls back to V4L2, which covers
    USB cameras on the Pi and webcams everywhere else.
    """
    if shutil.which("libcamera-vid"):
        return "libcamera"
    return "/dev/video0" if os.path.exists("/dev/video0") else "0"


def build_command(args, outfile: str) -> list[str]:
    """The ffmpeg command line. Separated out so it can be tested without a camera.

    A single encode is written to disk and, when serving, *also* pushed to the
    stream — one encode, two sinks, so streaming costs almost nothing and cannot
    degrade the recording.
    """
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-y"]

    src = args.input or default_input()
    if src == "libcamera":
        # The Pi camera stack pipes raw H.264 into ffmpeg.
        cmd += ["-f", "h264", "-i", "-"]
    elif str(src).isdigit():
        cmd += (["-f", "avfoundation", "-framerate", "30", "-i", str(src)]
                if sys.platform == "darwin"
                else ["-f", "v4l2", "-i", f"/dev/video{src}"])
    else:
        cmd += ["-f", "v4l2", "-framerate", str(args.fps),
                "-video_size", args.size, "-i", str(src)]

    if args.duration:
        cmd += ["-t", str(args.duration)]

    # Encode once. Pi 5 has no hardware H.264 encoder, so this is libx264 with a
    # preset chosen to keep a 1080p30 encode inside its thermal budget.
    cmd += ["-c:v", args.codec, "-preset", args.preset, "-crf", str(args.crf),
            "-pix_fmt", "yuv420p", "-g", str(args.fps * 2)]

    if args.serve:
        # tee: identical stream to the file and the RTSP endpoint. The file is
        # listed first deliberately — if the muxer for the stream fails, the
        # recording is already committed.
        rtsp = f"rtsp://{args.rtsp_host}:{args.rtsp_port}/{args.name}"
        cmd += ["-f", "tee", "-map", "0:v",
                f"[f=mp4]{outfile}|[f=rtsp]{rtsp}"]
    else:
        cmd += [outfile]
    return cmd


def write_status(path: str, payload: dict) -> None:
    """Publish rig health so the app (or a person) can see it is alive."""
    tmp = f"{path}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({**payload, "updated": time.time()}, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="rig_capture")
    p.add_argument("--input", help="Camera source: 'libcamera', /dev/videoN, "
                                   "or an index. Auto-detected by default.")
    p.add_argument("--out", default="matches", help="Where recordings are kept.")
    p.add_argument("--name", default="", help="Recording name (default: timestamp).")
    p.add_argument("--size", default="1920x1080", help="Capture resolution.")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--codec", default="libx264")
    p.add_argument("--preset", default="veryfast",
                   help="x264 preset. The Pi 5 has no hardware encoder, so this "
                        "trades quality for staying inside its thermal budget.")
    p.add_argument("--crf", type=int, default=23)
    p.add_argument("--duration", type=float, default=0,
                   help="Stop after N seconds (0 = until stopped).")
    p.add_argument("--serve", action="store_true",
                   help="Also publish RTSP for the app to analyse live. The "
                        "local recording happens either way.")
    p.add_argument("--rtsp-host", default="127.0.0.1",
                   help="Where an RTSP server (e.g. mediamtx) is listening.")
    p.add_argument("--rtsp-port", type=int, default=8554)
    p.add_argument("--status-file", default="rig_status.json")
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ffmpeg command and exit.")
    args = p.parse_args(argv)

    if not shutil.which("ffmpeg"):
        print("ffmpeg is not installed.", file=sys.stderr)
        return 2

    os.makedirs(args.out, exist_ok=True)
    name = args.name or time.strftime("%Y%m%d-%H%M%S")
    outfile = os.path.join(args.out, f"{name}.mp4")
    cmd = build_command(args, outfile)

    if args.dry_run:
        print(" ".join(cmd))
        return 0

    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    print(f"[rig] recording -> {outfile}", flush=True)
    if args.serve:
        url = f"rtsp://{lan_ip()}:{args.rtsp_port}/{args.name or name}"
        print(f"[rig] live at {url}", flush=True)
        print("[rig] point Camera & Feed at that URL.", flush=True)

    started = time.time()
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL)
    try:
        while not _STOP and proc.poll() is None:
            size = os.path.getsize(outfile) if os.path.exists(outfile) else 0
            write_status(args.status_file, {
                "recording": True, "file": outfile,
                "elapsed": round(time.time() - started, 1),
                "bytes": size, "serving": bool(args.serve),
                "free_gb": round(shutil.disk_usage(args.out).free / 1024 ** 3, 1),
            })
            time.sleep(2)
    finally:
        if proc.poll() is None:
            # 'q' lets ffmpeg finalise the MP4 index; without it the recording
            # is unplayable, which would defeat the whole point of recording
            # locally first.
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        size = os.path.getsize(outfile) if os.path.exists(outfile) else 0
        write_status(args.status_file, {"recording": False, "file": outfile,
                                        "bytes": size})
        print(f"[rig] stopped. {outfile} ({size / 1024 ** 2:.0f} MB)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
