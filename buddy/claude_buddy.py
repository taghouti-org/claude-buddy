#!/usr/bin/python3
"""Claude Buddy - an animated desktop avatar for Claude Code.

- Floats on the desktop, follows the cursor with its eyes, blinks, sleeps.
- Reacts to Claude Code hook events from every session (thinking, needs you, done).
- Click it to chat with Claude (headless `claude -p`, conversation is kept).
- Drag to move, right-click for the menu.
"""
import json
import math
import os
import random
import socket
import subprocess
import sys
import threading
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402
import cairo  # noqa: E402

try:
    gi.require_version("WebKit2", "4.1")
    from gi.repository import WebKit2
except (ValueError, ImportError):
    WebKit2 = None
import http.server  # noqa: E402

try:
    import numpy as np
except ImportError:
    np = None

HOME = os.path.expanduser("~")
CLAUDE = os.path.join(HOME, ".local/bin/claude")
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "claude-buddy.sock")
CONF_DIR = os.path.join(HOME, ".config/claude-buddy")
CONF = os.path.join(CONF_DIR, "config.json")
W, H = 170, 184
CX, CY, RX, RY = 85, 108, 44, 40
SKIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "skin")
SKIN_H = 200
HAS_SKIN = os.path.exists(os.path.join(SKIN_DIR, "idle.png"))
if HAS_SKIN:  # image skin: taller window, feet at CY + RY
    W, H = 200, 264
    CX, CY, RX, RY = 100, 142, 60, 100
WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
VRM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "avatar.vrm")
HAS_VRM = bool(WebKit2) and os.path.exists(VRM_PATH) and "--2d" not in sys.argv
if HAS_VRM:  # live 3D model in a transparent web view
    W, H = 280, 330
FEET = H - 17            # where her soles are, in window pixels from the top (3D avatar)
SLEEP_AFTER = 300  # seconds without any activity
STALE_AFTER = 900  # forget a busy session that went silent
ASSISTANT_PROMPT = (
    "You are being used as the user's desktop assistant through a small chat "
    "popup next to an on-screen avatar. Answer concisely in plain text (no "
    "markdown tables or headings); the popup is narrow. You cannot ask for "
    "permission interactively here, so if an action is blocked, say what the "
    "user should run or approve in a terminal session instead."
)

CSS = b"""
.buddy-card { background: #1f1e1d; border-radius: 16px; border: 1px solid #3a3835; }
.buddy-card textview, .buddy-card textview text { background: transparent; color: #ece8e1; }
.buddy-card scrolledwindow { background: transparent; }
.buddy-card entry { background: #2b2a28; color: #ece8e1; border-radius: 10px;
                    border: 1px solid #45423e; padding: 8px; caret-color: #d97757; }
.buddy-title { color: #d97757; font-weight: bold; }
.buddy-status { color: #8f8a83; }
.buddy-bubble { background: #fffaf5; color: #2b1d17; border-radius: 14px;
                padding: 8px 12px; border: 1px solid #e0c9bb; }
"""


def load_conf():
    try:
        with open(CONF) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_conf(conf):
    os.makedirs(CONF_DIR, exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        json.dump(conf, f)
    os.replace(tmp, CONF)


def star(cr, x, y, r, rot=0.0):
    """Four-point sparkle path."""
    for i in range(8):
        a = rot + i * math.pi / 4
        rr = r if i % 2 == 0 else r * 0.36
        px, py = x + math.cos(a) * rr, y + math.sin(a) * rr
        cr.line_to(px, py) if i else cr.move_to(px, py)
    cr.close_path()


def find_platforms(img, exclude=()):
    """Long horizontal edges in a screen capture (H x W x 3 uint8): things she can stand on.

    Returns [(x0, x1, y)] in image pixels, strongest first. `exclude` are (x, y, w, h) boxes to ignore.
    """
    lum = img[::2, ::2].astype(np.float32) @ np.array([0.30, 0.59, 0.11], np.float32)
    gy = np.abs(lum[2:, 1:-1] - lum[:-2, 1:-1])
    gx = np.abs(lum[1:-1, 2:] - lum[1:-1, :-2])
    mask = (gy > 14) & (gy > 1.6 * gx)
    for x, y, w, h in exclude:
        mask[max(y // 2 - 4, 0):(y + h) // 2 + 4, max(x // 2 - 4, 0):(x + w) // 2 + 4] = False
    runs = []
    for r in np.where(mask.sum(1) >= 55)[0]:
        d = np.diff(np.concatenate(([0], mask[r].view(np.int8), [0])))
        starts, ends = np.where(d == 1)[0], np.where(d == -1)[0]
        i = 0
        while i < len(starts):
            a, b = starts[i], ends[i]
            while i + 1 < len(starts) and starts[i + 1] - b <= 4:   # bridge small gaps
                i += 1
                b = ends[i]
            if b - a >= 55:
                runs.append((float(gy[r, a:b].mean()) * (b - a), int(a), int(b), int(r)))
            i += 1
    runs.sort(reverse=True)
    kept = []
    for _score, a, b, r in runs:
        if all(abs(r - kr) > 12 or min(b, kb) - max(a, ka) < 0.4 * (b - a) for ka, kb, kr in kept):
            kept.append((a, b, r))
            if len(kept) >= 60:
                break
    return [(a * 2 + 2, b * 2 + 2, r * 2 + 2) for a, b, r in kept]


class AvatarHandler(http.server.SimpleHTTPRequestHandler):
    """Loopback-only server for the 3D avatar page, its libraries and the model."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/model":
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(os.path.getsize(VRM_PATH)))
            self.end_headers()
            with open(VRM_PATH, "rb") as f:
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)
            return
        super().do_GET()

    def log_message(self, *_):
        pass


def load_skin():
    """Per-mood PNGs (idle required; busy/attention/happy/sleep optional)."""
    skin = {}
    if not HAS_SKIN:
        return skin
    for mood in ("idle", "busy", "attention", "happy", "sleep"):
        path = os.path.join(SKIN_DIR, mood + ".png")
        if not os.path.exists(path):
            continue
        try:
            src = cairo.ImageSurface.create_from_png(path)
        except (cairo.Error, OSError):
            continue
        k = SKIN_H / src.get_height()
        dst = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(src.get_width() * k) + 1, SKIN_H)
        c = cairo.Context(dst)
        c.scale(k, k)
        c.set_source_surface(src, 0, 0)
        c.get_source().set_filter(cairo.FILTER_BEST)
        c.paint()
        skin[mood] = dst
    return skin


def transparent(win):
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    win.set_app_paintable(True)


class Buddy(Gtk.Window):
    def __init__(self):
        super().__init__(title="Claude Buddy")
        self.conf = load_conf()
        self.skin = load_skin()
        self.sessions = {}  # session id -> {"state", "project", "ts"}
        self.own_busy = False
        self.proc = None
        self.sid = self.conf.get("sid")
        self.happy_t0 = -1e9
        self.last_activity = time.monotonic()
        self.gaze = [0.0, 0.0]
        self.next_blink = time.monotonic() + 3
        self.dragging = False
        self.press = None
        self.save_timer = 0
        self.bubble_timer = 0

        transparent(self)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_size_request(W, H)
        self.set_keep_above(True)
        self.stick()
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_accept_focus(False)
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.BUTTON1_MOTION_MASK
        )
        self.connect("draw", self.on_draw)
        self.web = None
        self.web_mood = None
        self.web_look = (0, 0)
        self.walk_to = None      # (x, y, speed px/s) while walking
        self.fly = None          # (x0, y0, x1, y1, t0, duration, arc height) during an ODM dash or a jump
        self.platform = None     # (x0, x1, y) screen ledge she is standing on, if any
        self.fly_platform = None
        self.walk_pos = None
        self.walk_dir = None
        self.next_walk = time.monotonic() + random.uniform(15, 30)
        self.last_tick = time.monotonic()
        target = self
        if HAS_VRM:
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AvatarHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.web = target = WebKit2.WebView()
            self.web.set_background_color(Gdk.RGBA(0, 0, 0, 0))
            settings = self.web.get_settings()
            settings.set_enable_webgl(True)
            settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
            self.web.connect("context-menu", lambda *_: True)
            self.add(self.web)
            self.web.load_uri("http://127.0.0.1:%d/avatar.html" % server.server_address[1])
        target.connect("button-press-event", self.on_press)
        target.connect("button-release-event", self.on_release)
        target.connect("motion-notify-event", self.on_motion)
        self.connect("configure-event", self.on_configure)
        self.connect("realize", self.on_realize)
        self.connect("destroy", self.quit)

        self.build_bubble()
        self.build_chat()
        self.build_menu()

        area = Gdk.Display.get_default().get_primary_monitor().get_workarea()
        x = self.conf.get("x", area.x + area.width - W - 30)
        y = self.conf.get("y", area.y + area.height - H - 30)
        self.move(x, y)
        self.show_all()
        GLib.timeout_add(40, self.tick)
        threading.Thread(target=self.serve, daemon=True).start()

    # ---------------------------------------------------------------- windows
    def on_realize(self, *_):
        # Only the character itself catches clicks; the rest is click-through.
        if HAS_VRM:
            region = cairo.Region(cairo.RectangleInt(60, 70, W - 120, H - 76))
        else:
            region = cairo.Region(cairo.RectangleInt(CX - RX - 4, CY - RY - 26, 2 * RX + 8, 2 * RY + 36))
        self.input_shape_combine_region(region)

    def build_bubble(self):
        self.bubble = Gtk.Window(type=Gtk.WindowType.POPUP)
        transparent(self.bubble)
        self.bubble_label = Gtk.Label(xalign=0)
        self.bubble_label.set_line_wrap(True)
        self.bubble_label.set_line_wrap_mode(Pango.WrapMode.WORD_CHAR)
        self.bubble_label.set_max_width_chars(34)
        box = Gtk.Box()
        box.get_style_context().add_class("buddy-bubble")
        box.add(self.bubble_label)
        self.bubble.add(box)

    def build_chat(self):
        self.chat = Gtk.Window(title="Claude")
        transparent(self.chat)
        self.chat.set_decorated(False)
        self.chat.set_keep_above(True)
        self.chat.stick()
        self.chat.set_skip_taskbar_hint(True)
        self.chat.set_skip_pager_hint(True)
        self.chat.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.chat.set_default_size(400, 480)
        self.chat.connect("delete-event", lambda *_: self.chat.hide() or True)
        self.chat.connect("key-press-event", self.on_chat_key)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("buddy-card")
        card.set_border_width(0)
        for side in ("top", "bottom", "start", "end"):
            getattr(card, "set_margin_" + side)(0)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        inner.set_border_width(14)
        card.pack_start(inner, True, True, 0)

        head = Gtk.Box(spacing=8)
        title = Gtk.Label(label="Claude", xalign=0)
        title.get_style_context().add_class("buddy-title")
        self.status = Gtk.Label(label="", xalign=1)
        self.status.get_style_context().add_class("buddy-status")
        head.pack_start(title, False, False, 0)
        head.pack_end(self.status, False, False, 0)
        inner.pack_start(head, False, False, 0)

        self.view = Gtk.TextView(editable=False, cursor_visible=False)
        self.view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.view.set_left_margin(2)
        self.view.set_right_margin(6)
        self.buf = self.view.get_buffer()
        self.buf.create_tag("you", foreground="#d97757", weight=Pango.Weight.BOLD)
        self.buf.create_tag("err", foreground="#e06c5a")
        self.buf.create_tag("dim", foreground="#8f8a83")
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.view)
        inner.pack_start(scroll, True, True, 0)

        self.entry = Gtk.Entry()
        self.entry.set_placeholder_text("Ask Claude…   Enter to send · Esc to hide")
        self.entry.connect("activate", self.on_send)
        inner.pack_start(self.entry, False, False, 0)
        self.chat.add(card)
        self.say_dim("Hi! Type below and press Enter. Esc hides this, right-click me for more.\n")

    def build_menu(self):
        self.menu = Gtk.Menu()
        for label, cb in (
            ("Chat", lambda *_: self.toggle_chat(True)),
            ("Open Claude in a terminal", self.open_terminal),
            ("New conversation", self.new_conversation),
            (None, None),
            ("Come here (ODM dash)", self.come_here),
            ("Stop current answer", self.stop_answer),
            (None, None),
            ("Quit", self.quit),
        ):
            item = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
            if cb:
                item.connect("activate", cb)
            self.menu.append(item)
        if HAS_VRM:
            walk = Gtk.CheckMenuItem(label="Walk around")
            walk.set_active(self.conf.get("walk", True))
            walk.connect("toggled", self.on_walk_toggled)
            self.menu.insert(walk, 5)
            climb = Gtk.CheckMenuItem(label="Jump onto things on screen")
            climb.set_active(self.conf.get("climb", True))
            climb.connect("toggled", self.on_climb_toggled)
            self.menu.insert(climb, 6)
            jump = Gtk.MenuItem(label="Jump somewhere now")
            jump.connect("activate", lambda *_: (self.wake(), self.jump_somewhere()))
            self.menu.insert(jump, 7)
            acts = Gtk.MenuItem(label="Actions")
            sub = Gtk.Menu()
            for label, name in (("Set blades down / pick them up", "blades"), (None, None),
                                ("Punches", "punch"), ("High kick", "kick"), ("Squats", "squats"),
                                ("Cross arms", "crossarms"), ("Wave", "wave"), (None, None),
                                ("Salute (dedicate your heart)", "salute"), ("Adjust scarf", "scarf"),
                                ("Nape cut (spinning slash)", "napecut"), ("Slash", "slash"),
                                ("Blade check", "bladecheck"), ("Guard stance", "guard"),
                                ("Sword flourish", "flourish"), ("Look around", "lookaround"), (None, None),
                                ("Hop", "hop"), ("Spin", "spin"), ("Jump spin", "jumpspin"), ("Stretch", "stretch"),
                                ("Nod", "nod"), ("Bow", "bow"), ("Victory", "victory"), ("Dance", "dance"),
                                ("Sway", "sway")):
                item = Gtk.SeparatorMenuItem() if label is None else Gtk.MenuItem(label=label)
                if name:
                    item.connect("activate", lambda _i, n=name: self.do_action(n))
                sub.append(item)
            acts.set_submenu(sub)
            self.menu.insert(acts, 8)
        self.menu.show_all()

    # ------------------------------------------------------------------ input
    def on_press(self, _w, ev):
        self.wake()
        self.stop_walk()
        if ev.button == 3:
            self.menu.popup_at_pointer(ev)
        elif ev.button == 1:
            self.press = (ev.x_root, ev.y_root)
            self.dragging = False
        return True

    def on_motion(self, _w, ev):
        if self.press and not self.dragging:
            if math.hypot(ev.x_root - self.press[0], ev.y_root - self.press[1]) > 6:
                self.dragging = True
                self.platform = None
                self.bubble.hide()
                self.begin_move_drag(1, int(ev.x_root), int(ev.y_root), ev.time)
        return True

    def on_release(self, _w, ev):
        if ev.button == 1 and self.press and not self.dragging:
            self.js("B.poke()")
            self.toggle_chat()
        self.press = None
        return True

    def on_configure(self, _w, ev):
        if (ev.x, ev.y) != (self.conf.get("x"), self.conf.get("y")):
            self.conf["x"], self.conf["y"] = ev.x, ev.y
            if self.save_timer:
                GLib.source_remove(self.save_timer)
            self.save_timer = GLib.timeout_add(800, self.save)
            if self.chat.get_visible():
                self.place_chat()
        return False

    def save(self):
        self.save_timer = 0
        self.conf["sid"] = self.sid
        save_conf(self.conf)
        return False

    def on_chat_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.chat.hide()
            return True
        return False

    # ------------------------------------------------------------------- chat
    def workarea(self):
        x, y = self.get_position()
        mon = Gdk.Display.get_default().get_monitor_at_point(x + W // 2, y + H // 2)
        return mon.get_workarea()

    def place_chat(self):
        x, y = self.get_position()
        cw, ch = self.chat.get_size()
        area = self.workarea()
        cx = x - cw - 6
        if cx < area.x:
            cx = x + W + 6
        cy = min(max(y + H - ch, area.y + 8), area.y + area.height - ch - 8)
        self.chat.move(cx, cy)

    def toggle_chat(self, force=None):
        show = (not self.chat.get_visible()) if force is None else force
        if show:
            self.bubble.hide()
            self.chat.show_all()
            self.place_chat()
            self.chat.present()
            self.entry.grab_focus()
        else:
            self.chat.hide()

    def append(self, text, tag=None):
        end = self.buf.get_end_iter()
        if tag:
            self.buf.insert_with_tags_by_name(end, text, tag)
        else:
            self.buf.insert(end, text)
        GLib.idle_add(self.scroll_end)

    def scroll_end(self):
        self.view.scroll_to_iter(self.buf.get_end_iter(), 0, False, 0, 1)
        return False

    def say_dim(self, text):
        self.append(text, "dim")

    def on_send(self, *_):
        prompt = self.entry.get_text().strip()
        if not prompt or self.own_busy:
            return
        self.entry.set_text("")
        self.append("\nYou  ", "you")
        self.append(prompt + "\n")
        self.own_busy = True
        self.status.set_text("thinking…")
        self.wake()
        threading.Thread(target=self.ask, args=(prompt, self.sid), daemon=True).start()

    def ask(self, prompt, sid):
        cmd = [CLAUDE, "-p", prompt, "--output-format", "json",
               "--append-system-prompt", ASSISTANT_PROMPT]
        if sid:
            cmd += ["--resume", sid]
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("CLAUDECODE", "CLAUDE_CODE", "CLAUDE_AUTO_RETRY"))}
        text, new_sid, err = "", sid, False
        try:
            self.proc = subprocess.Popen(cmd, cwd=HOME, env=env, stdin=subprocess.DEVNULL,
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            out, errout = self.proc.communicate()
            try:
                data = json.loads(out)
                text = (data.get("result") or "").strip()
                new_sid = data.get("session_id") or sid
                err = bool(data.get("is_error"))
            except ValueError:
                text, err = (out or errout or "No answer (stopped).").strip(), True
            if self.proc.returncode and not text:
                text, err = (errout or "claude exited with an error").strip(), True
        except OSError as e:
            text, err = "Could not run claude: %s" % e, True
        self.proc = None
        GLib.idle_add(self.answered, text, new_sid, err, sid)

    def answered(self, text, new_sid, err, old_sid):
        self.own_busy = False
        self.status.set_text("")
        if err and old_sid and "No conversation found" in text:
            new_sid = None  # stale session id; next message starts fresh
            text += "\n(The saved conversation was gone - send again to start a new one.)"
        self.sid = new_sid
        self.save()
        self.append("Claude  ", "you")
        self.append((text or "(empty answer)") + "\n", "err" if err else None)
        if not err:
            self.happy_t0 = time.monotonic()
        if not self.chat.get_visible():
            self.say(text if len(text) < 180 else text[:177] + "…")
        return False

    def stop_answer(self, *_):
        if self.proc:
            self.proc.terminate()

    def new_conversation(self, *_):
        self.sid = None
        self.save()
        self.buf.set_text("")
        self.say_dim("New conversation.\n")
        self.toggle_chat(True)

    def open_terminal(self, *_):
        try:
            subprocess.Popen(["gnome-terminal", "--", CLAUDE], cwd=HOME, start_new_session=True)
        except OSError as e:
            self.say("Could not open a terminal: %s" % e)

    # ----------------------------------------------------------------- bubble
    def say(self, text, seconds=7):
        if not text:
            return
        self.bubble_label.set_width_chars(min(34, max(len(line) for line in text.split("\n"))))
        self.bubble_label.set_text(text)
        self.bubble.show_all()
        _min, nat = self.bubble.get_preferred_size()
        self.bubble.resize(nat.width, nat.height)
        x, y = self.get_position()
        area = self.workarea()
        bx = min(max(x + W // 2 - nat.width // 2, area.x + 4), area.x + area.width - nat.width - 4)
        by = y + 14 - nat.height
        if by < area.y:
            by = y + H
        self.bubble.move(bx, by)
        if self.bubble_timer:
            GLib.source_remove(self.bubble_timer)
        self.bubble_timer = GLib.timeout_add_seconds(seconds, self.hide_bubble)

    def hide_bubble(self):
        self.bubble_timer = 0
        self.bubble.hide()
        return False

    # ------------------------------------------------------------ hook events
    def serve(self):
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        if os.path.exists(SOCK):
            os.unlink(SOCK)
        srv.bind(SOCK)
        os.chmod(SOCK, 0o600)
        srv.listen(16)
        while True:
            conn, _ = srv.accept()
            try:
                conn.settimeout(1)
                chunks, size = [], 0
                while size < 8 << 20:
                    data = conn.recv(65536)
                    if not data:
                        break
                    chunks.append(data)
                    size += len(data)
                event = json.loads(b"".join(chunks).decode("utf-8", "replace"))
                if isinstance(event, dict):
                    GLib.idle_add(self.on_event, event)
            except (OSError, ValueError):
                pass
            finally:
                conn.close()

    def on_event(self, ev):
        name = ev.get("hook_event_name", "")
        if name == "_toggle":
            self.toggle_chat()
            return False
        if name == "_act":
            action = str(ev.get("action", "hop"))
            if action == "come":
                self.come_here()
            elif action == "jump":
                self.wake()
                self.jump_somewhere()
            elif action == "walk":
                x, y = self.get_position()
                area = self.workarea()
                tx = x + (220 if x + 220 <= area.x + area.width - W else -220)
                self.wake()
                self.start_walk(tx, y, 85)
            else:
                self.do_action(action)
            return False
        if name == "_ask":
            self.toggle_chat(True)
            self.entry.set_text(str(ev.get("prompt", "")))
            self.on_send()
            return False
        sid = ev.get("session_id") or "?"
        project = os.path.basename(ev.get("cwd") or "") or "Claude"
        own = sid == self.sid or (self.own_busy and ev.get("cwd") == HOME and sid not in self.sessions)
        now = time.monotonic()
        self.wake()
        if name == "SessionEnd":
            self.sessions.pop(sid, None)
            return False
        s = self.sessions.setdefault(sid, {"state": "idle", "project": project, "own": own})
        s["ts"] = now
        if name in ("UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure"):
            s["state"] = "busy"
        elif name == "Notification":
            s["state"] = "attention"
            if not s["own"]:
                self.say("%s: %s" % (project, ev.get("message") or "needs you"), 12)
        elif name == "Stop":
            was_busy = s["state"] != "idle"
            s["state"] = "idle"
            if was_busy and not s["own"]:
                self.happy_t0 = now
                self.say("Done · %s" % project, 5)
        return False

    def wake(self):
        self.last_activity = time.monotonic()

    def mood(self, now):
        for sid in [k for k, s in self.sessions.items() if now - s.get("ts", now) > STALE_AFTER]:
            del self.sessions[sid]
        states = [s["state"] for s in self.sessions.values()]
        if "attention" in states:
            return "attention"
        if self.own_busy or "busy" in states:
            return "busy"
        if now - self.happy_t0 < 2.5:
            return "happy"
        if now - self.last_activity > SLEEP_AFTER:
            return "sleep"
        return "idle"

    # ---------------------------------------------------------------- drawing
    # ---------------------------------------------------------------- walking
    def on_walk_toggled(self, item):
        self.conf["walk"] = item.get_active()
        self.save()
        if not item.get_active():
            self.stop_walk()

    def on_climb_toggled(self, item):
        self.conf["climb"] = item.get_active()
        self.save()

    # ------------------------------------------------- seeing the screen
    def platforms(self):
        """Ledges on her current monitor, in screen coordinates (the monitor floor is always one)."""
        area = self.workarea()
        floor = (area.x, area.x + area.width, area.y + area.height - 2)
        if np is None:
            return [floor]
        try:
            pb = Gdk.pixbuf_get_from_window(Gdk.get_default_root_window(), area.x, area.y, area.width, area.height)
            w, h, rs, nc = pb.get_width(), pb.get_height(), pb.get_rowstride(), pb.get_n_channels()
            raw = np.frombuffer(pb.get_pixels(), np.uint8)
            raw = np.concatenate([raw, np.zeros(max(0, rs * h - len(raw)), np.uint8)])
            img = raw[:rs * h].reshape(h, rs)[:, :w * nc].reshape(h, w, nc)[:, :, :3]
        except Exception:  # capture not available: only the floor
            return [floor]
        mine = []
        for win, ww, wh in ((self, W, H), (self.chat, *self.chat.get_size()), (self.bubble, *self.bubble.get_size())):
            if win.get_visible():
                x, y = win.get_position()
                mine.append((x - area.x, y - area.y, ww, wh))
        found = [(a + area.x, b + area.x, y + area.y) for a, b, y in find_platforms(img, mine)]
        return [p for p in found if p[2] - FEET >= area.y - 40] + [floor]

    def jump_somewhere(self):
        if not self.web or self.fly:
            return False
        x, y = self.get_position()
        fx, fy = x + W // 2, y + FEET
        options = []
        for a, b, py in self.platforms():
            if b - a < 100 or (abs(py - fy) < 14 and a <= fx <= b):
                continue                                  # too narrow, or the one she is on
            lx = min(max(fx + random.uniform(-80, 80), a + 35), b - 35)
            dist = math.hypot(lx - fx, py - fy)
            if 80 < dist < 1400:
                options.append((1.0 / (1 + (dist / 450.0) ** 2), lx, a, b, py))
        if not options:
            return False
        pick = random.uniform(0, sum(o[0] for o in options))
        for wgt, lx, a, b, py in options:
            pick -= wgt
            if pick <= 0:
                break
        self.start_fly(int(lx - W // 2), int(py - FEET), kind="jump", platform=(a, b, py))
        return True

    def do_action(self, name):
        self.stop_walk()
        self.wake()
        self.js("B.act(%s)" % json.dumps(name))

    def come_here(self, *_):
        if not self.web:
            return
        _s, px, py = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
        area = Gdk.Display.get_default().get_monitor_at_point(px, py).get_workarea()
        x, _y = self.get_position()
        side = -1 if x < px else 1                       # stop beside the cursor, on the side she came from
        tx = min(max(px + side * 120 - W // 2, area.x), area.x + area.width - W)
        ty = min(max(py - H + 90, area.y), area.y + area.height - H)
        self.wake()
        self.platform = None
        self.start_fly(tx, ty)

    def start_walk(self, tx, ty, speed):
        self.bubble.hide()
        self.walk_pos = [float(v) for v in self.get_position()]
        self.walk_to = (tx, ty, speed)
        self.walk_dir = None

    def start_fly(self, tx, ty, kind="odm", platform=None):
        if self.walk_to:
            self.stop_walk()
        self.bubble.hide()
        x0, y0 = self.get_position()
        dist = math.hypot(tx - x0, ty - y0)
        if dist < 40:
            return
        if kind == "jump":
            dur = min(max(0.5 + dist / 1500.0, 0.6), 1.2)
            arc = 60 + 0.2 * dist + max(0, y0 - ty) * 0.15
        else:
            dur = min(max(dist / 900.0, 0.55), 1.5)
            arc = min(170.0, dist * 0.3)
        self.fly = (x0, y0, tx, ty, time.monotonic(), dur, arc)
        self.fly_platform = platform
        self.js("B.%s(%d,%.2f)" % ("jump" if kind == "jump" else "fly", (tx > x0 + 4) - (tx < x0 - 4), dur))

    def stop_walk(self):
        if self.fly:
            self.fly = None
            self.js("B.fly(0,0)")
        if self.walk_to:
            self.walk_to = None
            self.walk_dir = None
            self.js("B.walk(0,0)")
            self.next_walk = time.monotonic() + random.uniform(25, 60)

    def update_walk(self, mood, now, dt):
        if self.fly:
            x0, y0, x1, y1, t0, dur, arc = self.fly
            p = (now - t0) / dur
            if mood != "idle" or p >= 1:
                self.move(int(x1), int(y1))
                self.fly = None
                self.platform = self.fly_platform
                self.next_walk = now + random.uniform(25, 60)
                return
            e = p * p * (3 - 2 * p)
            self.move(int(x0 + (x1 - x0) * e), int(y0 + (y1 - y0) * e - math.sin(math.pi * p) * arc))
            return
        if self.walk_to:
            if mood != "idle" or self.chat.get_visible() or self.press:
                self.stop_walk()
                return
            tx, ty, speed = self.walk_to
            dx, dy = tx - self.walk_pos[0], ty - self.walk_pos[1]
            dist = math.hypot(dx, dy)
            step = speed * dt
            if dist <= step:
                self.move(int(tx), int(ty))
                self.stop_walk()
                return
            self.walk_pos[0] += dx / dist * step
            self.walk_pos[1] += dy / dist * step
            self.move(int(self.walk_pos[0]), int(self.walk_pos[1]))
            direction = (dx > 4) - (dx < -4)
            if direction != self.walk_dir:
                self.walk_dir = direction
                self.js("B.walk(%d,%.2f)" % (direction, 1.0 if speed > 120 else 0.4))
        elif (self.conf.get("walk", True) and mood == "idle" and now > self.next_walk
              and not self.chat.get_visible() and not self.press and not self.bubble.get_visible()):
            if now - self.last_activity > SLEEP_AFTER - 30:   # let her doze off instead
                return
            climb = self.conf.get("climb", True)
            if climb and random.random() < 0.45 and self.jump_somewhere():
                return
            x, y = self.get_position()
            area = self.workarea()
            lo, hi = area.x, area.x + area.width - W
            if self.platform:                           # stay on the ledge she is standing on
                lo, hi = max(lo, self.platform[0] + 25 - W // 2), min(hi, self.platform[1] - 25 - W // 2)
                if hi - lo < 120:
                    if not (climb and self.jump_somewhere()):
                        self.next_walk = now + 15
                    return
            for _ in range(8):
                tx = x + random.choice((-1, 1)) * random.uniform(100, 520)
                if lo <= tx <= hi:
                    if random.random() < 0.25:         # sometimes she takes the gear instead of walking
                        self.start_fly(int(tx), y, platform=self.platform)
                    else:
                        self.start_walk(int(tx), y, 85)
                    return
            self.next_walk = now + 10

    def js(self, code):
        if self.web and self.web.get_title() == "ready":
            code = "window.B&&" + code
            try:
                self.web.evaluate_javascript(code, -1, None, None, None, None, None)
            except (AttributeError, TypeError):
                self.web.run_javascript(code, None, None, None)

    def tick(self):
        if not self.web:
            self.queue_draw()
            return True
        now = time.monotonic()
        dt, self.last_tick = min(now - self.last_tick, 0.2), now
        mood = self.mood(now)
        if self.web.get_title() != "ready":
            self.web_mood = None
            return True
        self.update_walk(mood, now, dt)
        if mood != self.web_mood:
            self.web_mood = mood
            self.js("B.mood(%s)" % json.dumps(mood))
        _s, px, py = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
        wx, wy = self.get_position()
        look = (px - (wx + W // 2), py - (wy + 120))
        if abs(look[0] - self.web_look[0]) + abs(look[1] - self.web_look[1]) > 3:
            self.web_look = look
            self.js("B.look(%.3f,%.3f)" % (look[0] / 420.0, look[1] / 340.0))
        return True

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if self.web:
            return False  # the web view paints the 3D avatar on top
        now = time.monotonic()
        mood = self.mood(now)

        # motion
        breathe = math.sin(now * (1.2 if mood == "sleep" else 2.2)) * 0.022
        lift = 0.0
        if mood == "happy":
            k = 1 - (now - self.happy_t0) / 2.5
            lift = abs(math.sin((now - self.happy_t0) * 7)) * 14 * k
        elif mood == "attention":
            lift = abs(math.sin(now * 5)) * 7
        elif mood == "busy":
            lift = math.sin(now * 4) * 2 + 2

        # gaze follows the pointer
        tx = ty = 0.0
        if mood in ("idle", "attention", "happy"):
            _s, px, py = Gdk.Display.get_default().get_default_seat().get_pointer().get_position()
            wx, wy = self.get_position()
            dx, dy = px - (wx + CX), py - (wy + CY)
            d = math.hypot(dx, dy) or 1
            f = min(d / 260, 1.0)
            tx, ty = dx / d * f, dy / d * f
        elif mood == "busy":
            tx, ty = math.sin(now * 1.6) * 0.6, -0.8
        self.gaze[0] += (tx - self.gaze[0]) * 0.2
        self.gaze[1] += (ty - self.gaze[1]) * 0.2
        gx, gy = self.gaze[0] * 5, self.gaze[1] * 4

        # ground shadow
        cr.save()
        cr.translate(CX, CY + RY + 9)
        cr.scale(1, 0.22)
        shade = cairo.RadialGradient(0, 0, 2, 0, 0, RX * (1 - lift / 60))
        shade.add_color_stop_rgba(0, 0, 0, 0, 0.30)
        shade.add_color_stop_rgba(1, 0, 0, 0, 0)
        cr.set_source(shade)
        cr.arc(0, 0, RX, 0, 2 * math.pi)
        cr.fill()
        cr.restore()

        base = {"sleep": (0.74, 0.52, 0.44), "attention": (0.93, 0.50, 0.33)}.get(mood, (0.85, 0.47, 0.34))
        dark = tuple(c * 0.72 for c in base)
        cy = CY - lift
        sy = 1 + breathe
        top = cy - RY * sy

        if self.skin:
            img = self.skin.get(mood) or self.skin["idle"]
            iw, ih = img.get_width(), img.get_height()
            tilt = math.sin(now * 1.3) * 0.012
            if mood == "busy":
                tilt += math.sin(now * 3.2) * 0.022
            elif mood == "attention":
                tilt += math.sin(now * 10) * 0.018
            cr.save()
            cr.translate(CX, CY + RY - lift)
            cr.rotate(tilt)
            cr.scale(1 - breathe * 0.5, 1 + breathe)
            cr.set_source_surface(img, -iw / 2, -ih)
            cr.paint_with_alpha(0.72 if mood == "sleep" else 1.0)
            cr.restore()
            top = CY + RY - lift - ih * (1 + breathe)
            ax, ay = CX, top - 10
            if mood == "busy":
                glow = cairo.RadialGradient(ax, ay, 1, ax, ay, 17)
                glow.add_color_stop_rgba(0, 1, 0.85, 0.55, 0.55)
                glow.add_color_stop_rgba(1, 1, 0.85, 0.55, 0)
                cr.set_source(glow)
                cr.arc(ax, ay, 17, 0, 2 * math.pi)
                cr.fill()
                star(cr, ax, ay, 8 * (1 + 0.25 * math.sin(now * 8)), now * 3)
                cr.set_source_rgb(1.0, 0.86, 0.55)
                cr.fill()
        else:
            # feet
            cr.set_source_rgb(*dark)
            for side in (-1, 1):
                cr.save()
                cr.translate(CX + side * 19, CY + RY - 1 - lift * 0.35)
                cr.scale(1, 0.55)
                cr.arc(0, 0, 11, 0, 2 * math.pi)
                cr.fill()
                cr.restore()

            # antenna + spark
            sway = math.sin(now * 2.0) * 3
            ax, ay = CX + sway, top - 15
            cr.set_source_rgb(*dark)
            cr.set_line_width(3)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            cr.move_to(CX, top + 4)
            cr.curve_to(CX, top - 6, ax, ay + 10, ax, ay)
            cr.stroke()
            spin = now * 3 if mood == "busy" else math.sin(now) * 0.25
            pulse = 1 + (0.25 * math.sin(now * 8) if mood == "busy" else 0.06 * math.sin(now * 2))
            if mood != "sleep":
                glow = cairo.RadialGradient(ax, ay, 1, ax, ay, 17)
                glow.add_color_stop_rgba(0, 1, 0.85, 0.55, 0.55 if mood == "busy" else 0.25)
                glow.add_color_stop_rgba(1, 1, 0.85, 0.55, 0)
                cr.set_source(glow)
                cr.arc(ax, ay, 17, 0, 2 * math.pi)
                cr.fill()
            star(cr, ax, ay, 9 * pulse, spin)
            cr.set_source_rgb(*((0.80, 0.70, 0.62) if mood == "sleep" else (1.0, 0.86, 0.55)))
            cr.fill()

            # body
            cr.save()
            cr.translate(CX, cy)
            cr.scale(RX * (1 - breathe * 0.6), RY * sy)
            grad = cairo.RadialGradient(-0.35, -0.45, 0.1, 0, 0, 1.05)
            grad.add_color_stop_rgb(0, *(min(c * 1.16, 1) for c in base))
            grad.add_color_stop_rgb(0.75, *base)
            grad.add_color_stop_rgb(1, *(c * 0.86 for c in base))
            cr.set_source(grad)
            cr.arc(0, 0, 1, 0, 2 * math.pi)
            cr.fill()
            cr.restore()

            # cheeks
            cr.set_source_rgba(1, 0.62, 0.60, 0.45)
            for side in (-1, 1):
                cr.arc(CX + side * 26 + gx * 0.4, cy + 9 + gy * 0.4, 6, 0, 2 * math.pi)
                cr.fill()

            # eyes
            if now > self.next_blink + 0.14:
                self.next_blink = now + random.uniform(2.5, 6)
            blinking = self.next_blink <= now <= self.next_blink + 0.14
            ink = (0.17, 0.11, 0.09)
            cr.set_source_rgb(*ink)
            cr.set_line_width(3)
            for side in (-1, 1):
                ex, ey = CX + side * 15 + gx, cy - 5 + gy
                if mood == "sleep" or blinking:
                    cr.arc(ex, ey - 2, 6, 0.15 * math.pi, 0.85 * math.pi)
                    cr.stroke()
                elif mood == "happy":
                    cr.arc(ex, ey + 3, 6, 1.15 * math.pi, 1.85 * math.pi)
                    cr.stroke()
                else:
                    cr.save()
                    cr.translate(ex, ey)
                    cr.scale(5.5, 8.0 if mood == "attention" else 7.4)
                    cr.arc(0, 0, 1, 0, 2 * math.pi)
                    cr.restore()
                    cr.fill()
                    cr.set_source_rgba(1, 1, 1, 0.9)
                    cr.arc(ex - 1.6, ey - 2.6, 1.9, 0, 2 * math.pi)
                    cr.fill()
                    cr.set_source_rgb(*ink)

            # mouth
            mx, my = CX + gx * 0.7, cy + 12 + gy * 0.7
            cr.set_line_width(2.6)
            if mood == "attention":
                cr.arc(mx, my + 2, 3.6, 0, 2 * math.pi)
                cr.fill()
            elif mood == "sleep":
                cr.arc(mx, my + 1, 2.4, 0, 2 * math.pi)
                cr.stroke()
            else:
                r = 8 if mood == "happy" else 5.5
                cr.arc(mx, my - 2, r, 0.18 * math.pi, 0.82 * math.pi)
                cr.stroke()

        # mood extras
        if mood == "busy":
            for i in range(3):
                a = now * 2.6 + i * 2.1
                cr.set_source_rgba(1, 0.86, 0.55, 0.9 - i * 0.22)
                cr.arc(ax + math.cos(a) * 20, ay + math.sin(a) * 8, 3.2 - i * 0.6, 0, 2 * math.pi)
                cr.fill()
        elif mood == "attention":
            bx, by = CX + RX - 2, top + 2 + math.sin(now * 5) * 2
            cr.set_source_rgb(0.90, 0.22, 0.20)
            cr.arc(bx, by, 12, 0, 2 * math.pi)
            cr.fill()
            cr.set_source_rgb(1, 1, 1)
            cr.set_line_width(3.4)
            cr.move_to(bx, by - 6.5)
            cr.line_to(bx, by + 1.5)
            cr.stroke()
            cr.arc(bx, by + 6.3, 1.9, 0, 2 * math.pi)
            cr.fill()
        elif mood == "happy":
            age = now - self.happy_t0
            for i in range(5):
                a = i * 1.26 + 0.4
                dist = RX + 6 + age * 14
                cr.set_source_rgba(1, 0.86, 0.55, max(0.0, 1 - age / 2.5))
                star(cr, CX + math.cos(a) * dist, cy - 6 - abs(math.sin(a)) * dist * 0.75, 5, age * 2 + i)
                cr.fill()
        elif mood == "sleep":
            cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
            for i in range(3):
                p = (now * 0.35 + i / 3) % 1
                cr.set_font_size(9 + p * 9)
                cr.set_source_rgba(0.95, 0.90, 0.85, math.sin(p * math.pi) * 0.9)
                cr.move_to(CX + 30 + p * 22, top + 6 - p * 34)
                cr.show_text("z")
        return False

    def quit(self, *_):
        self.stop_answer()
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        Gtk.main_quit()


def already_running():
    if not os.path.exists(SOCK):
        return False
    msg = {"hook_event_name": "_toggle"}
    if "--act" in sys.argv[1:-1]:
        msg = {"hook_event_name": "_act", "action": sys.argv[sys.argv.index("--act") + 1]}
    if "--ask" in sys.argv[1:-1]:
        msg = {"hook_event_name": "_ask", "prompt": sys.argv[sys.argv.index("--ask") + 1]}
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(1)
            c.connect(SOCK)
            c.sendall(json.dumps(msg).encode())
        return True
    except OSError:
        return False


def main():
    if already_running():  # second launch (or --toggle) just toggles the chat
        return 0
    if "--toggle" in sys.argv or "--ask" in sys.argv or "--act" in sys.argv:
        print("claude-buddy is not running", file=sys.stderr)
        return 1
    provider = Gtk.CssProvider()
    provider.load_from_data(CSS)
    Gtk.StyleContext.add_provider_for_screen(
        Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    Buddy()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
