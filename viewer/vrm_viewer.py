#!/usr/bin/python3
"""VRM Viewer - a small local viewer for .vrm / .glb files (three.js + three-vrm).

Everything is served from this folder over a loopback-only HTTP server on a
random port; nothing is fetched from the internet.
"""
import http.server
import os
import sys
import threading
import urllib.parse

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = {"model": None}


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=HERE, **kwargs)

    def do_GET(self):
        if self.path.split("?")[0] == "/model":
            path = STATE["model"]
            if not path or not os.path.isfile(path):
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "model/gltf-binary")
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            with open(path, "rb") as f:
                while chunk := f.read(1 << 20):
                    self.wfile.write(chunk)
            return
        super().do_GET()

    def log_message(self, *_):
        pass


class Viewer(Gtk.Window):
    def __init__(self, port, model):
        super().__init__(title="VRM Viewer")
        self.port = port
        self.set_default_size(900, 760)
        bar = Gtk.HeaderBar(title="VRM Viewer", show_close_button=True)
        button = Gtk.Button(label="Open…")
        button.connect("clicked", self.on_open)
        bar.pack_start(button)
        self.bar = bar
        self.set_titlebar(bar)

        self.web = WebKit2.WebView()
        settings = self.web.get_settings()
        settings.set_enable_webgl(True)
        settings.set_enable_write_console_messages_to_stdout(True)
        settings.set_hardware_acceleration_policy(WebKit2.HardwareAccelerationPolicy.ALWAYS)
        self.add(self.web)
        self.connect("destroy", Gtk.main_quit)
        self.open(model)

    def open(self, model):
        url = "http://127.0.0.1:%d/index.html" % self.port
        if model:
            STATE["model"] = os.path.abspath(model)
            self.bar.set_subtitle(STATE["model"])
            url += "?model=" + urllib.parse.quote(os.path.basename(model))
            if os.environ.get("VRM_VIEW"):
                url += "&hide=1&view=" + os.environ["VRM_VIEW"] + os.environ.get("VRM_EXTRA", "")
        self.web.load_uri(url)

    def on_open(self, *_):
        dialog = Gtk.FileChooserNative.new("Open a VRM or GLB file", self, Gtk.FileChooserAction.OPEN, None, None)
        flt = Gtk.FileFilter()
        flt.set_name("VRM / glTF binary")
        for pattern in ("*.vrm", "*.glb", "*.VRM", "*.GLB"):
            flt.add_pattern(pattern)
        dialog.add_filter(flt)
        if STATE["model"]:
            dialog.set_current_folder(os.path.dirname(STATE["model"]))
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            self.open(dialog.get_filename())
        dialog.destroy()


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else None
    if model and not os.path.isfile(model):
        print("vrm-viewer: no such file: %s" % model, file=sys.stderr)
        return 1
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    win = Viewer(server.server_address[1], model)
    win.show_all()
    if os.environ.get("VRM_POS"):                      # e.g. VRM_POS=100,400 to place the window
        win.move(*[int(v) for v in os.environ["VRM_POS"].split(",")])
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
