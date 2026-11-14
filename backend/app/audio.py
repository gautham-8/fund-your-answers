"""Compress recordings before storing them (WAV 16 kHz mono ~32 KB/s -> MP3 32 kbps ~4 KB/s)."""

import asyncio
import logging
import shutil

log = logging.getLogger("viva.audio")

FFMPEG = shutil.which("ffmpeg")


async def to_mp3(data: bytes) -> bytes | None:
    """Return MP3 bytes, or None if ffmpeg is unavailable or fails (caller then keeps the original)."""
    if not FFMPEG:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            FFMPEG, "-hide_banner", "-loglevel", "error",
            "-i", "pipe:0", "-ac", "1", "-codec:a", "libmp3lame", "-b:a", "32k", "-f", "mp3", "pipe:1",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(data), timeout=60)
    except (OSError, asyncio.TimeoutError) as e:
        log.warning("ffmpeg failed to run: %s", e)
        return None
    if proc.returncode != 0 or not out:
        log.warning("ffmpeg could not convert audio: %s", err.decode(errors="ignore")[:200])
        return None
    return out
