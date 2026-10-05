"""Entry point: python -m app.main"""
from __future__ import annotations

import os

from .server import create_server


def main():
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    server = create_server(host, port)
    print(f"toolpath-audit listening on {host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
