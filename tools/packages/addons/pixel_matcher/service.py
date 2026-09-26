"""Pixel Matcher — core image processing logic.

All heavy lifting lives here, isolated from Flask.  The functions accept and
return standard Python types (PIL Images, bytes) so the service is trivially
testable without spinning up the web app.
"""

from __future__ import annotations

import io

from PIL import Image, ImageFilter
import numpy as np
from sklearn.cluster import KMeans


_BAYER_CACHE: dict[int, np.ndarray] = {}


def _bayer_matrix(n: int) -> np.ndarray:
    """Recursive (Knuth) construction of the n×n ordered-dither threshold
    matrix, n a power of two. Returns integer values 0..n*n-1 — the classic
    checkerboard-of-checkerboards pattern used by retro/pixel-art dithering
    (as opposed to Floyd-Steinberg's irregular error-diffusion noise)."""
    if n in _BAYER_CACHE:
        return _BAYER_CACHE[n]
    if n <= 1:
        m = np.zeros((1, 1), dtype=np.int32)
    else:
        smaller = _bayer_matrix(n // 2)
        size = smaller.shape[0]
        m = np.zeros((size * 2, size * 2), dtype=np.int32)
        m[0:size, 0:size] = 4 * smaller + 0
        m[0:size, size:] = 4 * smaller + 2
        m[size:, 0:size] = 4 * smaller + 3
        m[size:, size:] = 4 * smaller + 1
    _BAYER_CACHE[n] = m
    return m


def _tiled_bayer_threshold(height: int, width: int, n: int) -> np.ndarray:
    """(height, width) array of thresholds in (0, 1), tiled from the n×n
    Bayer matrix — compares directly against a 0..1 interpolation weight."""
    matrix = _bayer_matrix(n)
    thresh = (matrix.astype(np.float32) + 0.5) / (n * n)
    reps_y = (height + n - 1) // n
    reps_x = (width + n - 1) // n
    tiled = np.tile(thresh, (reps_y, reps_x))
    return tiled[:height, :width]


def _apply_ordered_dither(pixels: np.ndarray, cluster_centers: np.ndarray, small_height: int, small_width: int, bayer_n: int) -> np.ndarray:
    """Ordered (Bayer) dithering against an arbitrary KMeans palette.

    For each pixel, finds its nearest and second-nearest palette colours and
    the fractional weight between them, then swaps in the second-nearest
    colour wherever that weight exceeds the tiled Bayer threshold at that
    pixel's position — this produces the regular cross-hatched dither
    pattern of retro pixel art instead of a flat quantised block of colour.
    """
    # (n_pixels, num_colors) distance matrix — fine at pixel-art resolutions
    # (a few thousand pixels × up to 256 colours).
    dists = np.linalg.norm(pixels[:, None, :] - cluster_centers[None, :, :], axis=2)
    order = np.argsort(dists, axis=1)
    nearest_idx = order[:, 0]
    second_idx = order[:, 1] if cluster_centers.shape[0] > 1 else order[:, 0]

    d_near = np.take_along_axis(dists, nearest_idx[:, None], axis=1).ravel()
    d_second = np.take_along_axis(dists, second_idx[:, None], axis=1).ravel()
    denom = d_near + d_second
    weight = np.divide(d_near, denom, out=np.zeros_like(d_near), where=denom > 0)

    threshold = _tiled_bayer_threshold(small_height, small_width, bayer_n).ravel()
    use_second = weight > threshold

    chosen_idx = np.where(use_second, second_idx, nearest_idx)
    return cluster_centers[chosen_idx].astype(np.uint8)


def detect_optimal_pixel_size(img: Image.Image, max_size: int = 20) -> int:
    """Detect the best grid cell size for pixel art conversion."""
    candidates = list(range(4, max_size + 1, 2))  # 4, 6, 8, 10 …

    original = np.array(img.convert("RGB"))
    best_size = 8
    best_score = -float("inf")

    for size in candidates:
        if size > min(original.shape[:2]) // 4:
            continue

        small_w = original.shape[1] // size
        small_h = original.shape[0] // size
        if small_w < 8 or small_h < 8:
            continue

        small = img.resize((small_w, small_h), Image.NEAREST)
        upscaled = small.resize(img.size, Image.NEAREST)

        up_array = np.array(upscaled)
        mse = np.mean((original.astype(float) - up_array.astype(float)) ** 2)

        fidelity = 1.0 / (mse + 1)
        resolution_score = size / 12.0
        score = fidelity * resolution_score

        if score > best_score:
            best_score = score
            best_size = size

    return best_size


def _nearest_palette_index(pixels: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Index of the closest palette colour for every pixel, in chunks so a
    256-colour palette on a large grid never builds a huge distance matrix."""
    out = np.empty(pixels.shape[0], dtype=np.int64)
    chunk = 16384
    for start in range(0, pixels.shape[0], chunk):
        block = pixels[start:start + chunk]
        dists = np.linalg.norm(block[:, None, :] - palette[None, :, :], axis=2)
        out[start:start + chunk] = np.argmin(dists, axis=1)
    return out


def pixel_matcher(
    img: Image.Image,
    pixel_size: int | None = None,
    num_colors: int = 16,
    sharpen: bool = True,
    auto_detect: bool = True,
    scale_factor: int = 1,
    dither: int = 0,
    palette: list[tuple[int, int, int]] | None = None,
) -> Image.Image:
    """Convert *img* to pixel art.

    Args:
        img: Input PIL Image (RGB).
        pixel_size: Grid cell size in pixels. When *None* and *auto_detect* is
            True the size is computed automatically; otherwise defaults to 8.
        num_colors: Number of palette colours (KMeans clusters).
        sharpen: Apply a final SHARPEN pass.
        auto_detect: Detect *pixel_size* automatically when not supplied.
        scale_factor: Integer multiplier applied to the output via NEAREST
            resampling to preserve the pixel-art look (1 = original size).
        dither: Ordered (Bayer) dithering matrix size — 0/1 disables it, or
            2/4/8 for a 2×2/4×4/8×8 threshold matrix. Retro cross-hatch
            pattern between adjacent palette colours, not Floyd-Steinberg.
        palette: Fixed RGB colours to map onto (an imported palette). When
            given, KMeans is skipped and *num_colors* is ignored.

    Returns:
        Processed PIL Image (RGB).
    """
    img = img.convert("RGB")
    original_size = img.size

    if auto_detect and pixel_size is None:
        pixel_size = detect_optimal_pixel_size(img)
    elif pixel_size is None:
        pixel_size = 8

    num_colors = max(2, min(num_colors, 256))

    small_width = max(4, original_size[0] // pixel_size)
    small_height = max(4, original_size[1] // pixel_size)

    # Sharpen the source before downscaling so edges are crisper after
    # quantisation — applying it after would break the palette.
    source = img.filter(ImageFilter.SHARPEN) if sharpen else img
    small = source.resize((small_width, small_height), Image.NEAREST)

    pixels = np.array(small).reshape(-1, 3).astype(np.float32)
    if palette and len(palette) >= 2:
        centers = np.array(palette, dtype=np.float32)
        labels = _nearest_palette_index(pixels, centers)
    else:
        # KMeans can't find more clusters than there are distinct pixels.
        n_distinct = len(np.unique(pixels, axis=0))
        kmeans = KMeans(n_clusters=max(1, min(num_colors, n_distinct)), random_state=42, n_init=10)
        labels = kmeans.fit_predict(pixels)
        centers = kmeans.cluster_centers_

    if dither and dither > 1:
        quantized = _apply_ordered_dither(pixels, centers, small_height, small_width, int(dither))
    else:
        quantized = centers[labels].astype(np.uint8)

    quantized_img = Image.fromarray(quantized.reshape(small_height, small_width, 3))

    # scale_factor=1 → keep at small (pixelated) resolution
    # scale_factor>1 → multiply from the small base with NEAREST
    if scale_factor and scale_factor > 1:
        out_w = small_width * scale_factor
        out_h = small_height * scale_factor
        result = quantized_img.resize((out_w, out_h), Image.NEAREST)
    else:
        result = quantized_img

    return result


def process_image_bytes(
    image_bytes: bytes,
    pixel_size: int | None = None,
    num_colors: int = 16,
    scale_factor: int = 1,
    auto_detect: bool = True,
    sharpen: bool = True,
    dither: int = 0,
    palette: list[tuple[int, int, int]] | None = None,
) -> bytes:
    """Decode *image_bytes*, apply pixel_matcher, return PNG bytes."""
    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    result = pixel_matcher(
        img,
        pixel_size=pixel_size,
        num_colors=num_colors,
        sharpen=sharpen,
        auto_detect=auto_detect,
        scale_factor=scale_factor,
        dither=dither,
        palette=palette,
    )
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()
