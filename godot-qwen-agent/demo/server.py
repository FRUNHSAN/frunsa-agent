#!/usr/bin/env python3
"""HTTP API server — wraps Container in a minimal REST interface.

Usage:
    python demo/server.py [port]
    curl -X POST http://localhost:8765/chat -d '{"user":"frunhsan","message":"你好"}'
"""

from __future__ import annotations
import json, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv; load_dotenv()

from core.config import Config
from core.container import Container
from core.repl import Repl

# Shared across requests (simple, not production-grade)
containers: dict[str, Container] = {}
repls: dict[str, Repl] = {}


class ChatHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/chat":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        body = json.loads(raw.decode("utf-8"))
        user_id = body.get("user", "default")
        message = body.get("message", "")

        if user_id not in containers:
            cfg = Config.from_args([user_id])
            containers[user_id] = Container(cfg)
            repls[user_id] = Repl(containers[user_id])

        repl = repls[user_id]
        ctr = containers[user_id]

        # Process one round
        repl.round_count += 1
        if repl.round_count == 1:
            ctr.profile.start_session()

        system = repl._build_prompt()
        prompt = f"{system}\n\nUser: {message}"
        response = ctr.cloud_llm.generate(prompt)
        response, penalty = ctr.output_pipeline.process(response.strip())

        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        data = json.dumps({
            "response": response,
            "trust": round(repl.trust, 2),
            "round": repl.round_count,
            "verbose": ctr.bp.enforce("response_verbose_level"),
        }, ensure_ascii=False)
        self.wfile.write(data.encode("utf-8"))

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ok"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Silent


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    server = HTTPServer(("0.0.0.0", port), ChatHandler)
    print(f"[server] http://localhost:{port}/chat")
    print(f"[server] POST {{\"user\":\"frunhsan\",\"message\":\"你好\"}}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[server] stopped")


if __name__ == "__main__":
    main()
