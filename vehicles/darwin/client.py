"""STOMP client for the Darwin Push Port.

Runs a listener thread that pushes decompressed Pport XML bytes onto a
queue for the importer command to drain.
"""

import gzip
import logging
import os
import queue
import threading

import stomp

logger = logging.getLogger(__name__)

HOST = os.environ.get("DARWIN_STOMP_HOST", "darwin-dist-44ae45.nationalrail.co.uk")
PORT = int(os.environ.get("DARWIN_STOMP_PORT", "61613"))
USERNAME = os.environ.get("DARWIN_STOMP_USER")
PASSWORD = os.environ.get("DARWIN_STOMP_PASSWORD")
# "/queue/<guid>" for the per-user queue, or a "/topic/..." name
DESTINATION = os.environ.get("DARWIN_STOMP_DESTINATION") or os.environ.get(
    "DARWIN_STOMP_QUEUE", "darwin.pushport-v16"
)


class DarwinListener:
    def __init__(self, message_queue: queue.Queue, on_status=None):
        self.queue = message_queue
        self.on_status = on_status
        self.conn = None
        self._stopped = threading.Event()

    # -- stomp.py listener callbacks (v8 passes the whole frame) -----------
    def on_connected(self, frame):
        logger.info("darwin: connected to %s:%s", HOST, PORT)
        if self.on_status:
            self.on_status("connected")
        dest = DESTINATION
        if not dest.startswith("/"):
            dest = f"/topic/{dest}"
        self.conn.subscribe(destination=dest, id=1, ack="auto")

    def on_send(self, frame):
        pass

    def on_message(self, frame):
        body = frame.body
        if isinstance(body, str):
            body = body.encode()
        try:
            data = gzip.decompress(body)
        except OSError:
            data = body
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            logger.warning("darwin: message queue full, dropping message")

    def on_receipt(self, frame):
        pass

    def on_error(self, frame):
        logger.error("darwin: stomp error %s", getattr(frame, "body", frame))
        if self.on_status:
            self.on_status("error", str(getattr(frame, "body", frame)))

    def on_disconnected(self):
        logger.warning("darwin: disconnected")
        if self.on_status:
            self.on_status("disconnected")

    # -- lifecycle --------------------------------------------------------
    def run(self):
        backoff = 5
        while not self._stopped.is_set():
            try:
                self.conn = stomp.Connection12(
                    [(HOST, PORT)],
                    heartbeats=(10000, 10000),
                    reconnect_attempts_max=10,
                    auto_decode=False,  # bodies are gzip'd XML - keep raw bytes
                )
                self.conn.set_listener("", self)
                self.conn.connect(USERNAME, PASSWORD, wait=True)
                backoff = 5
                # stomp.py runs its own receiver thread; block until stopped
                while not self._stopped.wait(1):
                    if not self.conn.is_connected():
                        break
            except Exception:
                logger.exception("darwin: connection failed, retrying in %ss", backoff)
                if self.on_status:
                    self.on_status("error", "connection failed")
            self._stopped.wait(backoff)
            backoff = min(backoff * 2, 300)

    def stop(self):
        self._stopped.set()
        if self.conn:
            try:
                self.conn.disconnect()
            except Exception:
                pass


def start_listener(message_queue: queue.Queue, on_status=None) -> DarwinListener:
    listener = DarwinListener(message_queue, on_status=on_status)
    thread = threading.Thread(target=listener.run, daemon=True, name="darwin-stomp")
    thread.start()
    return listener
