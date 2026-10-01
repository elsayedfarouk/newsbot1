"""Frame renderer: animated crops of one article image + motion typography."""
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from planner import FRAME_H as H, FRAME_W as W, FULL

FPS = 30
WORK_H = 1500          # working height of the source image used for sampling
TEXT_CX = 500          # text centre, nudged left of the TikTok button column
TRANS_D = 0.5
YEL, GRN, RED = (255, 212, 0), (0, 150, 70), (225, 30, 40)

clamp = lambda x, a=0.0, b=1.0: max(a, min(b, x))
smooth = lambda p: p * p * (3 - 2 * p)
ease_out = lambda p: 1 - (1 - p) ** 3


def ease_back(p: float) -> float:
    c1 = 1.5
    return 1 + (c1 + 1) * (p - 1) ** 3 + c1 * (p - 1) ** 2


def build_background(img: Image.Image) -> np.ndarray:
    """Darkened, green-tinted, heavily blurred cover crop of the article image."""
    bw, bh = int(W * 1.3), int(H * 1.3)
    scale = max(bw / img.width, bh / img.height) / 2
    small = img.resize((int(img.width * scale) + 1, int(img.height * scale) + 1), Image.BICUBIC)
    small = small.filter(ImageFilter.GaussianBlur(14))
    big = small.resize((small.width * 2, small.height * 2), Image.BICUBIC)
    arr = np.asarray(big).astype(np.float32) * 0.38 + np.array([0, 28, 14], np.float32)
    return np.clip(arr, 0, 255).astype(np.uint8)


def build_scrims():
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None]
    x = np.linspace(-1, 1, W, dtype=np.float32)[None, :]
    top = 0.62 * np.clip((0.30 - y) / 0.30, 0, 1) ** 1.3
    bottom = 0.70 * np.clip((y - 0.55) / 0.45, 0, 1) ** 1.2
    full = np.repeat((1 - top - bottom)[:, :, None], W, axis=1)
    vignette = 1 - 0.35 * np.clip(x ** 2 + ((y * 2 - 1) ** 2) * 0.6 - 0.5, 0, 1)
    return full, (vignette * np.ones((H, W), np.float32))[:, :, None]


class FrameRenderer:
    def __init__(self, image_path, font_path, timeline, envelope, duration):
        self.font_path = str(font_path)
        self.scenes, self.texts, self.emphasis = timeline.scenes, timeline.texts, timeline.emphasis
        self.env, self.duration = envelope, duration
        src = Image.open(image_path).convert("RGB")
        self.bg = build_background(src)
        scale = WORK_H / src.height
        self.work = src.resize((max(1, round(src.width * scale)), WORK_H), Image.LANCZOS)
        self.work = self.work.filter(ImageFilter.UnsharpMask(3, 90, 2))
        self.scrim_full, self.scrim_card = build_scrims()
        self.noise = np.random.default_rng(3).normal(0, 3, (H + 40, W + 40, 1)).astype(np.float32)
        self._fonts, self._text_cache, self._shadows, self._masks = {}, {}, {}, {}

    # ---------- text ----------
    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size)
        return self._fonts[size]

    def text_image(self, text, size, style):
        key = (text, size, style)
        if key in self._text_cache:
            return self._text_cache[key]
        while True:
            f = self.font(size)
            l, t, r, b = f.getbbox(text)
            if r - l <= 880 or size < 40:
                break
            size -= 6
        pad = 26
        w, h = r - l + pad * 2 + 40, b - t + pad * 2 + 40
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ox, oy = 20 + pad - l, 20 + pad - t
        rot = 0
        if style in ("yel", "grn"):
            sh = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(sh).rounded_rectangle((28, 30, w - 12, h - 10), 18, fill=(0, 0, 0, 150))
            im = Image.alpha_composite(im, sh.filter(ImageFilter.GaussianBlur(8)))
            d = ImageDraw.Draw(im)
            d.rounded_rectangle((20, 20, w - 20, h - 20), 18, fill=YEL if style == "yel" else GRN)
            d.text((ox, oy), text, font=f, fill=(15, 15, 15) if style == "yel" else (255, 255, 255))
            rot = -2.2 if style == "yel" else 1.6
        else:
            d = ImageDraw.Draw(im)
            d.text((ox + 5, oy + 7), text, font=f, fill=(0, 0, 0, 170), stroke_width=7, stroke_fill=(0, 0, 0, 170))
            d.text((ox, oy), text, font=f, fill=(255, 255, 255), stroke_width=7, stroke_fill=(10, 10, 10))
        if rot:
            im = im.rotate(rot, resample=Image.BICUBIC, expand=True)
        self._text_cache[key] = im
        return im

    def draw_texts(self, canvas, t):
        for item in self.texts:
            if t < item.t_in or t > item.t_out + 0.25:
                continue
            im = self.text_image(item.text, item.size, item.style)
            p = clamp((t - item.t_in) / 0.30)
            scale, alpha, y_off = 0.55 + 0.45 * ease_back(p), clamp(p * 3), (1 - ease_out(p)) * 40
            if t > item.t_out:
                q = clamp((t - item.t_out) / 0.22)
                alpha, scale, y_off = alpha * (1 - q), scale * (1 - 0.08 * q), y_off - 30 * q
            if alpha <= 0:
                continue
            if abs(scale - 1) > 0.002:
                im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BICUBIC)
            if alpha < 0.999:
                im = im.copy()
                im.putalpha(im.getchannel("A").point(lambda v: int(v * alpha)))
            canvas.alpha_composite(im, (int(TEXT_CX - im.width / 2), int(item.y + y_off - im.height / 2)))

    # ---------- camera ----------
    def shake_punch(self, t):
        amp = dx = dy = 0.0
        for te in self.emphasis:
            d = t - te
            if 0 <= d < 0.8:
                e = math.exp(-d * 8)
                amp += 0.07 * e
                dx += 14 * e * math.sin(d * 90)
                dy += 11 * e * math.cos(d * 77)
        return amp, dx, dy

    @staticmethod
    def camera_at(scene, lt):
        kf = scene.cam
        if lt <= kf[0][0]:
            return kf[0][1:]
        for a, b in zip(kf, kf[1:]):
            if lt <= b[0]:
                p = smooth(clamp((lt - a[0]) / (b[0] - a[0])))
                return tuple(a[i] + (b[i] - a[i]) * p for i in range(1, 5))
        return kf[-1][1:]

    def render_window(self, ww, wh, t, scene, frame_i, zoom_mul=1.0):
        cx, cy, zoom, rot = self.camera_at(scene, t - scene.t0)
        amp, dx, dy = self.shake_punch(t)
        iw, ih = self.work.size
        zoom = max(zoom, 1.06) * (1 + amp) * (1 + 0.02 * self.env[min(frame_i, len(self.env) - 1)]) * zoom_mul
        k = max(ww / iw, wh / ih) * zoom            # output px per working-image px
        half_w, half_h = ww / (2 * k) * 1.04, wh / (2 * k) * 1.04
        px = min(max(cx * iw, half_w), iw - half_w) if half_w < iw / 2 else iw / 2
        py = min(max(cy * ih, half_h), ih - half_h) if half_h < ih / 2 else ih / 2
        px, py = px - dx / k, py - dy / k
        a = math.radians(rot)
        ca, sa = math.cos(a) / k, math.sin(a) / k
        coeffs = (ca, -sa, px - ca * ww / 2 + sa * wh / 2, sa, ca, py - sa * ww / 2 - ca * wh / 2)
        return self.work.transform((ww, wh), Image.AFFINE, coeffs, Image.BICUBIC)

    def render_window_blur(self, ww, wh, t, scene, frame_i, blur, zoom_mul=1.0):
        if not blur:
            return self.render_window(ww, wh, t, scene, frame_i, zoom_mul)
        acc = sum(np.asarray(self.render_window(ww, wh, max(scene.t0, t - dt), scene, frame_i, zoom_mul)).astype(np.float32)
                  for dt in (0, 0.014, 0.028))
        return Image.fromarray((acc / 3).astype(np.uint8))

    # ---------- compositing ----------
    def shadow(self, w, h):
        if (w, h) not in self._shadows:
            m = Image.new("L", (w + 160, h + 160), 0)
            ImageDraw.Draw(m).rounded_rectangle((80, 90, w + 80, h + 90), 40, fill=170)
            self._shadows[(w, h)] = m.filter(ImageFilter.GaussianBlur(26))
        return self._shadows[(w, h)]

    def round_mask(self, w, h, r):
        if r == 0:
            return Image.new("L", (w, h), 255)
        if (w, h, r) not in self._masks:
            m = Image.new("L", (w * 2, h * 2), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * 2 - 1, h * 2 - 1), r * 2, fill=255)
            self._masks[(w, h, r)] = m.resize((w, h), Image.LANCZOS)
        return self._masks[(w, h, r)]

    def put_window(self, canvas, rect, img, radius, alpha=1.0, clip=None):
        x, y, ww, wh = rect
        full = rect == FULL
        if full and clip is None:
            canvas.paste(img, (int(x), int(y)))
            return
        mask = self.round_mask(ww, wh, radius)
        if clip is not None:
            band = Image.new("L", (ww, wh), 0)
            ImageDraw.Draw(band).rectangle((clip[0], 0, clip[1], wh), fill=255)
            mask = Image.fromarray(np.minimum(np.asarray(mask), np.asarray(band)))
        if radius:
            canvas.paste((0, 0, 0), (int(x) - 80, int(y) - 80), self.shadow(ww, wh).point(lambda v: int(v * alpha)))
            border = self.round_mask(ww + 12, wh + 12, radius + 6).point(lambda v: int(v * alpha))
            if clip is None:
                canvas.paste((255, 255, 255), (int(x) - 6, int(y) - 6), border)
        canvas.paste(img, (int(x), int(y)), mask.point(lambda v: int(v * alpha)) if alpha < 1 else mask)

    @staticmethod
    def tween(kind, q, ww):
        """Incoming-window state: (dx, dy, alpha, zoom_mul, clip)."""
        e = ease_out(q)
        table = {
            "slide_y": (0, (1 - e) * 1300, 1, 1, None),
            "slide_y2": (0, -(1 - e) * 1300, 1, 1, None),
            "slide_x": ((1 - e) * W, 0, 1, 1, None),
            "slide_x2": (-(1 - e) * W, 0, 1, 1, None),
            "scale": (0, 0, clamp(q * 3), 1 + 0.9 * (1 - e), None),
            "punch": (0, 0, 1, 1 + 1.4 * (1 - e) ** 2, None),
            "intro": (0, 0, 1, 1 + 0.9 * (1 - e) ** 2, None),
            "wipe": (0, 0, 1, 1 + 0.25 * (1 - e), (ww / 2 - ww * e / 2, ww / 2 + ww * e / 2)),
        }
        return table.get(kind, (0, 0, 1, 1, None))

    def scene_index(self, t):
        for i, sc in enumerate(self.scenes):
            if t < sc.t1:
                return i
        return len(self.scenes) - 1

    def render(self, fi) -> Image.Image:
        t = fi / FPS
        si = self.scene_index(t)
        sc = self.scenes[si]
        lt = t - sc.t0
        bh, bw = self.bg.shape[:2]
        ox = int((bw - W) / 2 + math.sin(t * 0.45) * min(160, (bw - W) / 2))
        oy = int((bh - H) / 2 + math.cos(t * 0.3) * min(90, (bh - H) / 2))
        canvas = Image.fromarray(self.bg[oy:oy + H, ox:ox + W].copy())

        x, y, ww, wh = sc.rect
        full = sc.rect == FULL
        p = clamp(lt / TRANS_D)
        in_trans = lt < TRANS_D
        blur_now = in_trans or any(0 <= t - te < 0.3 for te in self.emphasis)

        if si > 0 and in_trans:
            pv = self.scenes[si - 1]
            e = ease_out(p)
            off = {"slide_y": (0, -e * 1300), "slide_y2": (0, e * 1300),
                   "slide_x": (-e * W, 0), "slide_x2": (e * W, 0)}.get(sc.trans, (0, 0))
            pimg = self.render_window(pv.rect[2], pv.rect[3], pv.t1 - 1e-3, pv, fi)
            prect = (pv.rect[0] + off[0], pv.rect[1] + off[1], pv.rect[2], pv.rect[3])
            self.put_window(canvas, prect, pimg, pv.radius, 1 - p if sc.trans == "scale" else 1.0)

        dx, dy, alpha, zoom_mul, clip = self.tween(sc.trans, p, ww) if in_trans else (0, 0, 1, 1, None)
        img = self.render_window_blur(ww, wh, t, sc, fi, blur_now, zoom_mul)
        self.put_window(canvas, (x + dx, y + dy, ww, wh), img, sc.radius, alpha, clip)

        arr = np.asarray(canvas).astype(np.float32) * (self.scrim_full if full else self.scrim_card)
        arr += self.noise[(fi * 7) % 40:(fi * 7) % 40 + H, (fi * 13) % 40:(fi * 13) % 40 + W]
        if si > 0 and lt < 0.14:
            flash = 0.35 * (1 - lt / 0.14)
            arr = arr + (255 - arr) * flash
        out = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
        self.draw_overlays(out, t)
        self.draw_texts(out, t)
        return out.convert("RGB")

    def draw_overlays(self, out, t):
        d = ImageDraw.Draw(out)
        tx = 60 - (1 - ease_out(clamp((t - 0.15) / 0.35))) * 400
        d.rounded_rectangle((tx, 250, tx + 74, 308), 8, fill=RED)
        d.text((tx + 37, 279), "NEWS", font=self.font(30), fill="white", anchor="mm")
        d.rounded_rectangle((tx + 80, 250, tx + 470, 308), 8, fill=(255, 255, 255))
        d.text((tx + 275, 280), "BREAKING", font=self.font(36), fill=(15, 15, 15), anchor="mm")
        d.rectangle((0, 0, W * (t / self.duration), 9), fill=YEL)
