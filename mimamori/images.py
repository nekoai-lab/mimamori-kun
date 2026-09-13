"""受け取った画像を、モデルが読める形にそろえる。

実物で分かったこと（2026-09-13）:
    親が iPhone から送ってくる画面写真は **HEIC** だった（4032×3024・3MB）。
    HEIC はそのままではモデルに渡せず、渡すと意味の分からない 500 になる。
    ここで JPEG に直し、直せないときは**人に分かる言葉で断る**。

大きさも落とす。学校PCの画面を撮った写真は、長辺を1600pxにしても文字は読める。
そのままだと1枚3MBで、読み取りが遅くなるだけ。
"""
from __future__ import annotations

import io
from typing import Tuple

MAX_EDGE = 1600
HEIC_BRANDS = (b"ftypheic", b"ftypheix", b"ftyphevc", b"ftypheim", b"ftypmif1", b"ftypmsf1")


def looks_heic(data: bytes) -> bool:
    return len(data) > 12 and any(b in data[:32] for b in HEIC_BRANDS)


def normalize(data: bytes, content_type: str) -> Tuple[bytes, str]:
    """(画像データ, MIMEタイプ) を返す。読めない形式は ValueError。

    Pillow が入っていない環境では、JPEG/PNG はそのまま通す（縮小だけ諦める）。
    HEIC だけは直せないので、その場合ははっきり断る。
    """
    ct = (content_type or "").lower()
    heic = looks_heic(data) or "heic" in ct or "heif" in ct

    try:
        from PIL import Image
    except ImportError:
        if heic:
            raise ValueError(
                "iPhone の写真形式（HEIC）です。この環境では開けません。"
                "写真を「JPEG」で保存し直すか、スクリーンショットを送ってください。"
            )
        return data, ct or "image/jpeg"

    if heic:
        try:
            import pillow_heif

            pillow_heif.register_heif_opener()
        except ImportError:
            raise ValueError(
                "iPhone の写真形式（HEIC）です。この環境では開けません。"
                "写真を「JPEG」で保存し直すか、スクリーンショットを送ってください。"
            )

    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"画像として開けませんでした（{e}）。別の形式で送ってください。") from e

    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    w, h = im.size
    if max(w, h) > MAX_EDGE:
        scale = MAX_EDGE / max(w, h)
        im = im.resize((max(1, int(w * scale)), max(1, int(h * scale))))

    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"
