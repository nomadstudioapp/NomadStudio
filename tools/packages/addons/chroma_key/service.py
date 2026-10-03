"""Chroma Key — General-purpose solid/gradient background removal by color.

Keys on chrominance (Cb/Cr in YCbCr) rather than raw RGB distance, so it's
robust to lighting gradients/vignettes that keep the background's color
family but vary its brightness across the image — the case that trips up
naive color-distance thresholding.

Adapted from an externally-drafted baseline algorithm into the NomadStudio
addon shape (pure PIL/numpy/scipy service, zero Flask — see routes.py for
the HTTP layer and addons/README.md for the addon contract).
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image
from scipy import ndimage


# Neutral protection (see remove_background). Below this background
# saturation the background is itself near-grey and "neutral" can't be told
# apart from it, so the protection is skipped.
NEUTRAL_PROTECT_MIN_SAT = 8.0
# A pixel starts turning opaque once it carries less than (1 - START) of the
# background's colour, and is fully opaque RAMP further on: with 0.3/0.4,
# 70% background -> transparent, 30% or less -> opaque.
NEUTRAL_PROTECT_START = 0.3
NEUTRAL_PROTECT_RAMP = 0.4

# Coverage (the "is this a chroma-key image?" warning) is measured on a top
# band this tall, as a fraction of the image: the backdrop shows there even
# when the subject fills most of the frame.
COVERAGE_BORDER_FRACTION = 0.08
# ...and a border pixel is backdrop when its hue is within ~18 degrees of the
# background's and it keeps at least a third of its saturation (vignettes).
COVERAGE_MIN_COS = 0.95
COVERAGE_MIN_SHARE = 0.35


def _rgb_to_ycbcr(arr: np.ndarray) -> np.ndarray:
    """Vectorized RGB -> YCbCr (ITU-R BT.601). arr: float32 HxWx3 in [0,255]."""
    R, G, B = arr[..., 0], arr[..., 1], arr[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    Cb = -0.168736 * R - 0.331264 * G + 0.5 * B + 128
    Cr = 0.5 * R - 0.418688 * G - 0.081312 * B + 128
    return np.stack([Y, Cb, Cr], axis=-1)


def detect_background(
    image: Image.Image,
    downscale_to: int = 64,
    quant_levels: int = 24,
    refine_size: int = 512,
):
    """Estimate the dominant background color and how "flat" the background is.

    Works by downscaling with a box filter (averages away thin foreground
    detail like text/logos), quantizing in chroma space (Cb/Cr — ignores
    luma, so lighting gradients/vignettes on a single-color background don't
    split it into multiple buckets), and taking the most frequent bucket.

    This replaces the older border-ring sampling approach: it doesn't assume
    the image border is pure background, so it also works when the subject
    touches or bleeds past the edges.

    Parameters
    ----------
    image : PIL.Image
    downscale_to : int
        Size of the box-filtered thumbnail used to build the histogram.
    quant_levels : int
        Number of buckets per chroma channel (256 // quant_levels = bucket width).
    refine_size : int
        Size of the mid-res image used to compute the precise averaged color
        once the dominant bucket is known.

    Returns
    -------
    (bg_color, coverage) : (np.ndarray[3], float)
        bg_color: estimated background RGB.
        coverage: fraction of the top band that matches the background.
                  As a rule of thumb: coverage > ~0.85 -> good chroma-key
                  candidate (flat/vignetted solid background). Lower than
                  that -> likely a photo/complex scene, use a segmentation
                  model instead.
    """
    img = image.convert("RGB")

    small = img.resize((downscale_to, downscale_to), Image.Resampling.BOX)
    small_arr = np.array(small).astype(np.float32)
    small_cbcr = _rgb_to_ycbcr(small_arr)[..., 1:]  # Cb, Cr only

    bucket_size = 256 // quant_levels
    quantized = (small_cbcr // bucket_size).astype(np.int32)
    flat = quantized.reshape(-1, 2)

    buckets, counts = np.unique(flat, axis=0, return_counts=True)
    dominant_bucket = buckets[np.argmax(counts)]

    mid = img.resize((refine_size, refine_size), Image.Resampling.BOX)
    mid_arr = np.array(mid).astype(np.float32)
    mid_cbcr = _rgb_to_ycbcr(mid_arr)[..., 1:]
    mid_quant = (mid_cbcr // bucket_size).astype(np.int32)
    mask = np.all(mid_quant == dominant_bucket, axis=-1)
    bg_color = mid_arr[mask].mean(axis=0)

    # Coverage asks "is the backdrop one flat colour?", not "how much of the
    # picture is backdrop?" — a subject filling the frame isn't a reason to
    # warn. So it's measured on the top band only: the sides and bottom are
    # where subjects get cropped (measured 2026-10-03 on two studio shots, a
    # vignetted synthetic and 15 ordinary photos: top band 0.92-1.00 for
    # chroma shots, at most 0.60 for photos; the full ring overlapped). The
    # colour itself is still picked from the whole image above, which is
    # what keeps detection working when the subject touches edges.
    # A pixel counts as backdrop when its chroma points the same way as the
    # background's — not when it lands in the exact same histogram bucket: a
    # vignette scales chroma down towards neutral without turning it, and
    # exact buckets split such a backdrop into many.
    band = max(1, int(round(refine_size * COVERAGE_BORDER_FRACTION)))
    border = np.zeros(mask.shape, dtype=bool)
    border[:band] = True
    bg_chroma = _rgb_to_ycbcr(bg_color.reshape(1, 1, 3))[0, 0, 1:] - 128.0
    bg_sat = float(np.hypot(*bg_chroma))
    if bg_sat > NEUTRAL_PROTECT_MIN_SAT:
        px = mid_cbcr[border] - 128.0
        px_sat = np.hypot(px[:, 0], px[:, 1])
        cos = (px @ bg_chroma) / np.maximum(px_sat * bg_sat, 1e-6)
        coverage = ((cos > COVERAGE_MIN_COS) & (px_sat > COVERAGE_MIN_SHARE * bg_sat)).mean()
    else:
        coverage = mask[border].mean()

    return bg_color, float(coverage)


def remove_background(
    image: Image.Image,
    bg_color=None,
    tolerance: float = 30.0,
    feather: float = 25.0,
    despeckle_min_size: int = 15,
    decontaminate: bool = True,
    blur_sigma: float = 0.8,
    choke: float = 0.0,
) -> Image.Image:
    """Remove a solid or vignetted background of a known (or auto-detected) color.

    Parameters
    ----------
    image : PIL.Image
        Already-loaded PIL Image.
    bg_color : (r,g,b) or None
        Background color to key out. If None, auto-detected via
        `detect_background()` (dominant chroma-space histogram bucket over
        the whole downscaled image — not just the border ring).
    tolerance : float
        Cb/Cr distance below which a pixel is treated as fully background.
        Raise if background fringes survive; lower if foreground gets eaten.
    feather : float
        Extra Cb/Cr distance over which alpha ramps 0->1 (antialiasing band).
    despeckle_min_size : int
        Foreground connected components smaller than this (pixels) are
        dropped — cleans up noise/compression artifacts misread as foreground.
    decontaminate : bool
        Strip residual background-color spill from semi-transparent edge
        pixels so no colored fringe shows when compositing on a new bg. Uses
        an exact "uncomposite" (inverts observed = fg*alpha + bg*(1-alpha)),
        not a heuristic push, so it removes anti-aliasing spill in one step.
    blur_sigma : float
        Gaussian blur on the final alpha channel for smoother edges.
    choke : float
        Erodes the alpha matte inward by roughly this many pixels before
        blurring. 0 = off. Use when a colored fringe survives despeckle +
        decontamination — this discards the problem ring physically instead
        of color-correcting it (which gets numerically unstable at very low
        alpha). Try 0.5-2; higher values eat into fine detail (hair strands
        can visibly thin out), so nudge up gradually rather than jumping
        straight to a big value.

    Returns
    -------
    PIL.Image in RGBA mode.
    """
    img = image.convert("RGB")
    arr = np.array(img).astype(np.float32)

    coverage = None
    if bg_color is None:
        bg_color, coverage = detect_background(img)
    else:
        bg_color = np.array(bg_color, dtype=np.float32)

    ycbcr = _rgb_to_ycbcr(arr)
    bg_ycbcr = _rgb_to_ycbcr(bg_color.reshape(1, 1, 3))[0, 0]

    # Distance in chroma plane only — ignores luma, so vignettes/gradients
    # in an otherwise-uniform background don't fool the key.
    dcb = ycbcr[..., 1] - bg_ycbcr[1]
    dcr = ycbcr[..., 2] - bg_ycbcr[2]
    dist = np.sqrt(dcb ** 2 + dcr ** 2)

    alpha = np.clip((dist - tolerance) / max(feather, 1e-6), 0, 1)

    # Neutral protection. White, grey and black all sit at the centre of the
    # Cb/Cr plane, so on a muted background (a photographic studio green is
    # only ~30 from neutral) the distance above lumps eyes, white fabric and
    # shadows in with the backdrop. Unmix instead: project each pixel onto
    # the neutral->background axis. A neutral pixel carries 0% of the
    # background's colour (opaque), the backdrop 100% (transparent), and a
    # hair strand blended over the screen sits in between — so wispy edges
    # keep their partial alpha. Pixels coloured off that axis (red hair, a
    # yellow coat) are already opaque by distance; max() keeps the stronger.
    bg_chroma = np.array([bg_ycbcr[1] - 128.0, bg_ycbcr[2] - 128.0])
    bg_sat = float(np.hypot(*bg_chroma))
    if bg_sat > NEUTRAL_PROTECT_MIN_SAT:
        axis = bg_chroma / bg_sat
        share = ((ycbcr[..., 1] - 128.0) * axis[0] + (ycbcr[..., 2] - 128.0) * axis[1]) / bg_sat
        unmixed = np.clip((1.0 - share - NEUTRAL_PROTECT_START) / NEUTRAL_PROTECT_RAMP, 0, 1)
        alpha = np.maximum(alpha, unmixed)

    # Despeckle: drop small isolated foreground blobs (sensor/compression noise)
    if despeckle_min_size > 0:
        fg_mask = alpha > 0.5
        opened = ndimage.binary_opening(fg_mask, structure=np.ones((3, 3)))
        labeled, n = ndimage.label(opened)
        if n > 0:
            sizes = ndimage.sum(opened, labeled, range(1, n + 1))
            small = np.isin(labeled, [i + 1 for i, s in enumerate(sizes) if s < despeckle_min_size])
            alpha[small] = 0

    if choke > 0:
        # Choke / matte shrink: erode the alpha channel inward, physically
        # discarding the outermost fringe pixels instead of trying to
        # color-correct them. Most reliable fix for a stubborn colored halo
        # that survives spill suppression + decontamination — those are
        # color math and can only do so much right at very low alpha, where
        # dividing by a near-zero alpha to "undo" the blend gets unstable.
        # Physically removing that thin ring sidesteps the instability
        # entirely. Typical useful range: 0.5-2 (px-ish; it's a Gaussian
        # erosion radius, not a hard pixel count, so fractional values work).
        alpha = np.clip(alpha - ndimage.gaussian_filter((alpha < 0.5).astype(np.float32), sigma=choke), 0, 1)

    if blur_sigma > 0:
        alpha = ndimage.gaussian_filter(alpha, sigma=blur_sigma)
    alpha = np.clip(alpha, 0, 1)

    rgb = arr.copy()

    # Spill suppression: green-screen (and other saturated backgrounds) light
    # bounces onto the subject and tints pixels the key considers fully
    # opaque — most visible on fine hair/fuzzy edges, where you get color
    # bleed a few pixels *into* the silhouette, not just at the alpha ramp.
    # The edge decontamination below only corrects pixels scaled by
    # (1 - alpha), so a pixel the key reads as 100% foreground gets zero
    # correction even if it's visibly tinted. This pass is independent of
    # alpha: for each pixel, find which of the background's two "non-key"
    # channels is closest to the background's dominant channel, and clamp
    # the background's dominant channel so it doesn't exceed the max of the
    # other two — the same idea as classic green/blue-screen spill
    # suppression (Ultimatte-style), generalized to an arbitrary key color.
    bg_channel = int(np.argmax(bg_color))  # which RGB channel the background is keyed on
    other_channels = [c for c in range(3) if c != bg_channel]
    dominant = rgb[..., bg_channel]
    other_max = np.maximum(rgb[..., other_channels[0]], rgb[..., other_channels[1]])
    spill_excess = np.clip(dominant - other_max, 0, None)
    # only suppress where there's real foreground (alpha>0) — leave background as-is
    spill_excess = spill_excess * (alpha > 0.02)
    rgb[..., bg_channel] = dominant - spill_excess

    if decontaminate:
        # Exact color decontamination: invert the assumed over-compositing
        # equation instead of just nudging color away from bg_color. Partial-
        # alpha edge pixels are a real blend of true_fg*alpha + bg*(1-alpha)
        # (this is what anti-aliasing against a screen physically produces,
        # separate from — and usually bigger than — light-bounce spill).
        # Solving directly for true_fg removes it in one step:
        #   true_fg = (observed - bg_color * (1 - alpha)) / alpha
        # Only applied where alpha is meaningfully >0 and <1 — fully opaque
        # pixels are untouched (handled by the spill-suppression pass above
        # instead), fully transparent pixels don't matter.
        edge = (alpha > 0.02) & (alpha < 0.98)
        a_safe = np.where(edge, alpha, 1.0)[..., None]
        uncomposited = (rgb - bg_color * (1 - a_safe)) / a_safe
        rgb = np.where(edge[..., None], uncomposited, rgb)
        rgb = np.clip(rgb, 0, 255)

    rgba = np.dstack([rgb.astype(np.uint8), (alpha * 255).astype(np.uint8)])
    out = Image.fromarray(rgba, mode="RGBA")
    out.info["chroma_key_coverage"] = coverage
    return out


def _parse_hex_color(hex_str: str):
    """Parse '#rrggbb' or 'rrggbb' into an (r,g,b) tuple, or None if invalid/blank."""
    if not hex_str:
        return None
    s = hex_str.strip().lstrip("#")
    if len(s) != 6:
        return None
    try:
        return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    except ValueError:
        return None


def _rgb_to_hex(rgb) -> str:
    r, g, b = (max(0, min(255, int(round(v)))) for v in rgb)
    return "#{:02x}{:02x}{:02x}".format(r, g, b)


def detect_background_from_bytes(image_bytes: bytes):
    """Run auto-detection only (no keying) and return (hex_color, coverage).

    Used by the "Detect" button in the UI so the user can see/tweak the
    auto-detected color before switching to manual mode, independent of
    actually running the full background removal.
    """
    img = Image.open(io.BytesIO(image_bytes))
    bg_color, coverage = detect_background(img)
    return _rgb_to_hex(bg_color), coverage


def process_image_bytes(
    image_bytes: bytes,
    bg_color_hex: str | None = None,
    tolerance: float = 30.0,
    feather: float = 25.0,
    despeckle_min_size: int = 15,
    decontaminate: bool = True,
    blur_sigma: float = 0.8,
    choke: float = 0.0,
):
    """Returns (png_bytes, coverage). coverage is None when bg_color_hex was
    supplied manually (no auto-detection ran)."""
    img = Image.open(io.BytesIO(image_bytes))
    bg_color = _parse_hex_color(bg_color_hex) if bg_color_hex else None
    result = remove_background(
        img,
        bg_color=bg_color,
        tolerance=tolerance,
        feather=feather,
        despeckle_min_size=despeckle_min_size,
        decontaminate=decontaminate,
        blur_sigma=blur_sigma,
        choke=choke,
    )
    coverage = result.info.get("chroma_key_coverage")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue(), coverage
