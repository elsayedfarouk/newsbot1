"""Turn a Gemini plan + word timings into a timeline of scenes and on-screen text."""
import random
import re
from dataclasses import dataclass, field

FRAME_W, FRAME_H = 1080, 1920
FULL = (0, 0, FRAME_W, FRAME_H)

# Layout templates, cycled per scene: window rect, corner radius, transition, text slots (y, max font size).
TEMPLATES = [
    dict(rect=(0, 470, 1080, 900), radius=0, trans="intro", slots=[(400, 100), (1260, 150)]),
    dict(rect=(60, 640, 960, 640), radius=38, trans="slide_y", slots=[(430, 230), (1380, 90)]),
    dict(rect=(60, 820, 960, 520), radius=38, trans="scale", slots=[(450, 260), (1450, 90)]),
    dict(rect=FULL, radius=0, trans="slide_x", slots=[(460, 200), (1300, 110)]),
    dict(rect=(90, 610, 900, 650), radius=38, trans="wipe", slots=[(400, 150), (1370, 90)]),
    dict(rect=(60, 960, 960, 500), radius=38, trans="slide_x2", slots=[(520, 200), (790, 110)]),
    dict(rect=FULL, radius=0, trans="punch", slots=[(560, 200), (1250, 130)]),
    dict(rect=(60, 760, 960, 640), radius=38, trans="slide_y2", slots=[(420, 170), (1480, 90)]),
]
KIND_STYLE = {"number": ("yel", 240), "key": ("yel", 150), "fact": ("white", 100), "place": ("grn", 84)}
MIN_SCENE, MAX_SCENE, FIRST_SCENE_MIN, TAIL_MIN = 4.5, 10.0, 5.5, 3.0


@dataclass
class Scene:
    t0: float
    t1: float
    rect: tuple
    radius: int
    trans: str
    cam: list  # (t_rel, cx, cy, zoom, rot_deg), cx/cy normalised 0-1
    slots: list


@dataclass
class TextItem:
    text: str
    t_in: float
    t_out: float
    y: int
    size: int
    style: str


@dataclass
class Timeline:
    scenes: list
    texts: list = field(default_factory=list)
    emphasis: list = field(default_factory=list)


def norm(word: str) -> str:
    return re.sub(r"[^a-z0-9]", "", word.lower())


def split_scenes(words, duration: float) -> list:
    """Scene boundaries at sentence ends (or forced when a scene runs too long)."""
    bounds = [0.0]
    for cur, nxt in zip(words, words[1:]):
        last = bounds[-1]
        minimum = FIRST_SCENE_MIN if len(bounds) == 1 else MIN_SCENE
        cut = (cur.end + nxt.start) / 2
        sentence_end = cur.text.endswith((".", "!", "?"))
        if (cut - last >= minimum and sentence_end) or cut - last >= MAX_SCENE:
            if duration - cut >= TAIL_MIN:
                bounds.append(cut)
    bounds.append(duration)
    return list(zip(bounds, bounds[1:]))


def make_camera(length: float, focus: list, rng: random.Random, zoom_in: bool) -> list:
    """Four keyframes drifting between focus points, alternating push-in / pull-out."""
    zooms = [1.12, 1.55, 2.0, 1.6] if zoom_in else [1.9, 1.5, 1.2, 1.1]
    times = [0.0, 0.4 * length, 0.75 * length, length]
    frames = []
    for t, z in zip(times, zooms):
        fx, fy = rng.choice(focus)
        frames.append((t, fx, fy, z, rng.uniform(-1.1, 1.1)))
    frames[0] = frames[0][:4] + (0.0,)
    return frames


def clean_focus(points) -> list:
    pts = [(min(max(p.x, 0.12), 0.88), min(max(p.y, 0.12), 0.88)) for p in points]
    return pts or [(0.5, 0.5)]


def anchor_beats(beats, words) -> list:
    """Match each beat's anchor word to a spoken word, searching forward only."""
    matched, cursor = [], 0
    for beat in beats:
        target = norm(beat.anchor_word)
        for i in range(cursor, len(words)):
            if target and target in norm(words[i].text):
                matched.append((words[i].start, beat))
                cursor = i + 1
                break
    return matched


def place_texts(scene: Scene, items: list) -> list:
    """Assign beats inside one scene to alternating slots; each lasts until its slot is reused."""
    texts = []
    for n, (t_in, beat) in enumerate(items):
        y, cap = scene.slots[n % len(scene.slots)]
        style, size = KIND_STYLE.get(beat.kind, KIND_STYLE["fact"])
        texts.append(TextItem(beat.text.upper(), t_in, scene.t1 - 0.12, y, min(size, cap), style))
    last_in_slot = {}
    for n, item in enumerate(texts):
        slot = n % len(scene.slots)
        if slot in last_in_slot:
            last_in_slot[slot].t_out = min(last_in_slot[slot].t_out, item.t_in - 0.05)
        last_in_slot[slot] = item
    return [t for t in texts if t.t_out - t.t_in >= 0.6]


def build_timeline(plan, words, duration: float, seed: int) -> Timeline:
    rng = random.Random(seed)
    focus = clean_focus(plan.focus_points)
    spans = split_scenes(words, duration)
    scenes = []
    for i, (t0, t1) in enumerate(spans):
        tpl = TEMPLATES[i % len(TEMPLATES)]
        scenes.append(Scene(t0, t1, tpl["rect"], tpl["radius"], tpl["trans"],
                            make_camera(t1 - t0, focus, rng, zoom_in=i % 2 == 0), tpl["slots"]))
    hook = type("Hook", (), dict(text=plan.hook, kind="fact", anchor_word=""))
    anchored = [(0.3, hook)] + anchor_beats(plan.beats, words)
    timeline = Timeline(scenes=scenes)
    for scene in scenes:
        mine = [(t, b) for t, b in anchored if scene.t0 <= t < scene.t1 - 0.6]
        timeline.texts += place_texts(scene, mine)
        timeline.emphasis += [t for t, b in mine if b.kind in ("number", "key")]
    return timeline
