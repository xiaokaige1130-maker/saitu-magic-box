from __future__ import annotations

import socket
import threading
import time
import webbrowser

import uvicorn

from app.main import app


def find_port(start: int = 18130) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no available local port")


def open_browser(url: str) -> None:
    time.sleep(1.2)
    webbrowser.open(url)


def main() -> None:
    port = find_port()
    url = f"http://127.0.0.1:{port}"
    print(f"ImageCube running at {url}", flush=True)
    threading.Thread(target=open_browser, args=(url,), daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
