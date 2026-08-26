"""Derive the web-sized brand images from the masters, with no image library.

WHY THIS EXISTS. The masters the founder supplied are print-sized — the square mark is
1024x1024 and **412 KB**, and the two lockups are 2172x724. Referencing those directly
would ship 412 KB of PNG to every console page for a 36px sidebar mark, on a 1 vCPU box
whose webhook ack budget is 500 ms (DEPLOYMENT §2b). The three obvious alternatives were
each worse:

  - `next/image` runtime optimisation: Next 15 needs `sharp` for it, `sharp` is not in
    this lockfile, and adding a native dependency for a logo is a supply-chain decision
    (hard rule 9) with a compile on the VPS attached to it.
  - ImageMagick / ffmpeg: not installed here, and adding a system dependency to a build
    is the same trade one layer down.
  - Hand-tracing the mark as SVG: it is the founder's artwork, and eyeballing it would
    put an approximation of their logo on a client-facing site.

So this reads PNG and writes PNG with `zlib` and `struct` alone. It is run by hand and
its OUTPUT IS COMMITTED — this is not a build step. Re-run it when a master changes:

    uv run python -m scripts.generate_brand_assets

TWO THINGS THAT ARE EASY TO GET WRONG AND ARE DONE RIGHT HERE.

**Premultiplied alpha.** Averaging RGBA naively across a box that straddles an edge
mixes the colour of fully transparent pixels into the result. Those pixels are usually
black, so a green mark on transparency acquires a dark fringe that only shows up once
the image is on a light surface — i.e. after it ships. Every average below is taken on
premultiplied values and un-premultiplied at the end.

**Box averaging, not nearest.** The mark is flat colour with long curved edges; nearest
sampling at 1024→108 aliases those curves into visible steps. A box filter over the exact
source rectangle each destination pixel covers is the correct resampling for downscaling
by a large factor, and at these ratios it is indistinguishable from a proper Lanczos pass
on flat artwork.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MASTERS = REPO / "apps" / "web" / "public" / "brand"
APP = REPO / "apps" / "web" / "src" / "app"

#: master -> (output path, width). Heights follow the master's aspect ratio exactly, so
#: nothing here can distort the artwork by a rounding choice.
#:
#: The widths are ~3x the largest size each asset is rendered at, which is what keeps it
#: crisp on a 3x phone without paying for the master. The sidebar mark renders at 36 CSS
#: px, the wordmark's ink at roughly 20 px tall inside a 3:1 canvas that is 54% ink.
DERIVATIVES: list[tuple[str, Path, int]] = [
    ("calevate-icon-logo-no-text.png", MASTERS / "icon.png", 216),
    ("calevate-full-logo-without-tagline.png", MASTERS / "wordmark.png", 720),
    ("calevate-full-logo-with-tagline.png", MASTERS / "lockup.png", 720),
    # Next's App Router file conventions: `app/icon.png` and `app/apple-icon.png` are
    # picked up automatically and emit their own <link> tags, so no `metadata.icons`
    # entry is needed and none is written. 180 is Apple's stated touch-icon size.
    ("calevate-icon-logo-no-text.png", APP / "icon.png", 192),
    ("calevate-icon-logo-no-text.png", APP / "apple-icon.png", 180),
]

#: The sizes packed into `app/favicon.ico`.
#:
#: `favicon.ico` IS WHY THE TAB STILL SHOWED THE OLD MARK after `icon.png` landed. Next
#: emits BOTH files' link tags and gives the `.ico` `sizes="any"`, which browsers read as
#: "usable at every size" and prefer over a single-resolution PNG. Adding `icon.png` beside
#: a stale `.ico` therefore changes nothing a user can see — the file that has to change is
#: this one. Deleting it instead would work, but an `.ico` at the well-known path is also
#: what a crawler, a feed reader and a bookmark bar fetch without reading any markup.
#:
#: 16/32/48 covers the tab, the bookmark bar and Windows' larger list views. The images are
#: embedded as PNG rather than BMP, which every browser has accepted since IE11 and which
#: keeps the alpha channel exact — a BMP-in-ICO carries its transparency in a separate
#: 1-bit mask, so the mark's antialiased curves would come back with hard edges.
FAVICON_SIZES = (16, 32, 48)


def read_rgba(path: Path) -> tuple[int, int, bytearray]:
    """Decode a non-interlaced 8-bit RGBA PNG into a flat byte buffer."""
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"{path.name} is not a PNG")
    pos, idat, width, height = 8, bytearray(), 0, 0
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        body = data[pos + 8 : pos + 8 + length]
        if kind == b"IHDR":
            width, height, depth, colour, _c, _f, interlace = struct.unpack(">IIBBBBB", body)
            if (depth, colour, interlace) != (8, 6, 0):
                raise ValueError(
                    f"{path.name}: expected 8-bit RGBA, non-interlaced; got depth={depth} "
                    f"colour={colour} interlace={interlace}"
                )
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length

    raw = zlib.decompress(bytes(idat))
    stride = width * 4
    out = bytearray(height * stride)
    previous = bytearray(stride)
    read = 0
    for y in range(height):
        filter_type = raw[read]
        read += 1
        line = bytearray(raw[read : read + stride])
        read += stride
        # The five PNG filters (RFC 2083 §6). Written out rather than table-driven: this
        # is the one place a subtle mistake produces an image that looks *almost* right.
        if filter_type == 1:  # Sub
            for i in range(4, stride):
                line[i] = (line[i] + line[i - 4]) & 0xFF
        elif filter_type == 2:  # Up
            for i in range(stride):
                line[i] = (line[i] + previous[i]) & 0xFF
        elif filter_type == 3:  # Average
            for i in range(stride):
                left = line[i - 4] if i >= 4 else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif filter_type == 4:  # Paeth
            for i in range(stride):
                left = line[i - 4] if i >= 4 else 0
                up_left = previous[i - 4] if i >= 4 else 0
                up = previous[i]
                estimate = left + up - up_left
                da, db, dc = (
                    abs(estimate - left),
                    abs(estimate - up),
                    abs(estimate - up_left),
                )
                nearest = left if (da <= db and da <= dc) else (up if db <= dc else up_left)
                line[i] = (line[i] + nearest) & 0xFF
        elif filter_type != 0:
            raise ValueError(f"{path.name}: unknown PNG filter {filter_type}")
        out[y * stride : (y + 1) * stride] = line
        previous = line
    return width, height, out


def box_downsample(src: bytearray, sw: int, sh: int, dw: int, dh: int) -> bytearray:
    """Area-average `src` into `dw`x`dh`, averaging PREMULTIPLIED colour.

    See the module docstring: averaging straight RGBA pulls the colour of transparent
    pixels into every edge, which on this artwork means a dark halo around green.
    """
    dst = bytearray(dw * dh * 4)
    for dy in range(dh):
        y0, y1 = dy * sh // dh, max(dy * sh // dh + 1, (dy + 1) * sh // dh)
        for dx in range(dw):
            x0, x1 = dx * sw // dw, max(dx * sw // dw + 1, (dx + 1) * sw // dw)
            rs = gs = bs = a_sum = 0
            for sy in range(y0, y1):
                row = sy * sw * 4
                for sx in range(x0, x1):
                    i = row + sx * 4
                    a = src[i + 3]
                    rs += src[i] * a
                    gs += src[i + 1] * a
                    bs += src[i + 2] * a
                    a_sum += a
            count = (y1 - y0) * (x1 - x0)
            o = (dy * dw + dx) * 4
            alpha = a_sum // count
            if a_sum:
                # Un-premultiply against the SUMMED alpha, not the averaged one: that is
                # what makes a half-covered edge pixel carry the mark's colour at half
                # opacity rather than a colour darkened towards zero.
                dst[o] = min(255, rs // a_sum)
                dst[o + 1] = min(255, gs // a_sum)
                dst[o + 2] = min(255, bs // a_sum)
            dst[o + 3] = alpha
    return dst


def write_rgba(path: Path, width: int, height: int, pixels: bytearray) -> None:
    """Write an 8-bit RGBA PNG, every scanline filter 0.

    Filter 0 throughout, and `zlib` at level 9: the artwork is flat colour, so the
    filters buy almost nothing over what DEFLATE already finds, and an unfiltered file is
    one fewer thing to be subtly wrong in a script with no library to check it against.
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + kind
            + body
            + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw += pixels[y * stride : (y + 1) * stride]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def write_ico(path: Path, images: list[tuple[int, bytes]]) -> None:
    """Pack `(size, png_bytes)` pairs into a Windows ICO.

    The format is a 6-byte ICONDIR, one 16-byte ICONDIRENTRY per image, then the image
    data (docs.microsoft.com/en-us/previous-versions/ms997538(v=msdn.10)). A dimension of
    256 is stored as 0 — the field is one byte — which is why nothing here may exceed 48
    without handling that case; `FAVICON_SIZES` is asserted against it rather than trusted.
    """
    if any(size > 255 for size, _ in images):
        raise ValueError("an ICO dimension above 255 must be stored as 0; see the docstring")
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    directory, blob = b"", b""
    for size, png in images:
        directory += struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(png), offset + len(blob))
        blob += png
    path.write_bytes(header + directory + blob)


def main() -> int:
    for master_name, out, width in DERIVATIVES:
        master = MASTERS / master_name
        sw, sh, pixels = read_rgba(master)
        # Height from the master's ratio, so no entry in the table can squash the mark.
        height = max(1, round(width * sh / sw))
        write_rgba(out, width, height, box_downsample(pixels, sw, sh, width, height))
        print(
            f"{out.relative_to(REPO)}  {width}x{height}  "
            f"{out.stat().st_size / 1024:.0f}KB  (from {master_name} {sw}x{sh})"
        )
    # The favicon last, reusing the same downsampler so the tab mark cannot drift from
    # the one in the sidebar.
    sw, sh, pixels = read_rgba(MASTERS / "calevate-icon-logo-no-text.png")
    packed: list[tuple[int, bytes]] = []
    for size in FAVICON_SIZES:
        scratch = APP / f".favicon-{size}.png"
        write_rgba(scratch, size, size, box_downsample(pixels, sw, sh, size, size))
        packed.append((size, scratch.read_bytes()))
        scratch.unlink()
    ico = APP / "favicon.ico"
    write_ico(ico, packed)
    print(
        f"{ico.relative_to(REPO)}  {'/'.join(str(s) for s in FAVICON_SIZES)}  "
        f"{ico.stat().st_size / 1024:.0f}KB  (from calevate-icon-logo-no-text.png {sw}x{sh})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
