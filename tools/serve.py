#!/usr/bin/env python3
"""Local preview server for the site: ``python3 -m http.server`` plus HTTP Range support.

``http.server`` answers a Range request with the whole file (200, no ``Accept-Ranges``). A browser then treats every
clip as not seekable (``video.seekable`` is 0..0): setting ``currentTime`` snaps back to 0, so the position slider of
the comparison viewer jumps back when dragged. GitHub Pages honours Range, so the deployed site is not affected.

Usage:
  python3 tools/serve.py [PORT]     (default 8931; serves the repository root on 127.0.0.1)
"""
import os, re, sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def send_head(self):
        self.range_left = None
        m = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', '').strip())
        path = self.translate_path(self.path)
        if not m or m.groups() == ('', '') or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        a, b = m.groups()
        if a == '':  # suffix range: the last b bytes
            start, end = max(0, size - int(b)), size - 1
        else:
            start, end = int(a), min(int(b), size - 1) if b else size - 1
        if start > end or start >= size:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        f = open(path, 'rb')
        f.seek(start)
        self.range_left = end - start + 1
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(self.range_left))
        self.send_header('Last-Modified', self.date_time_string(os.path.getmtime(path)))
        self.end_headers()
        return f

    def end_headers(self):
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')  # always revalidate, so an edited page or clip shows on reload
        super().end_headers()

    def copyfile(self, source, outputfile):
        left = self.range_left
        if left is None:
            return super().copyfile(source, outputfile)
        while left > 0:
            buf = source.read(min(65536, left))
            if not buf:
                break
            outputfile.write(buf)
            left -= len(buf)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8931
    print(f'serving {ROOT} on http://127.0.0.1:{port}/')
    ThreadingHTTPServer(('127.0.0.1', port), partial(Handler, directory=ROOT)).serve_forever()
