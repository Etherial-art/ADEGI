"""Single-machine demo: simulated Jetson server + MP257 client in one process.

    python3 demo.py

Kills the "Jetson" after a few frames to show the fallback, then restarts it.
"""
from __future__ import annotations

import argparse
import logging
import time

from client import BridgeClient
from detectors import SimulatedDetector
from server import BridgeServer


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fps", type=float, default=10)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    server = BridgeServer(SimulatedDetector("sim-jetson", 0.02))
    server.start()
    client = BridgeClient("127.0.0.1", server.port, SimulatedDetector("sim-local-npu", 0.05),
                          heartbeat_interval=0.2, heartbeat_timeout=0.8)
    client.start()
    client.wait_connected(2)

    for i in range(60):
        if i == 20:
            print("--- Jetson goes down ---")
            server.stop()
        if i == 40:
            print("--- Jetson comes back ---")
            server = BridgeServer(SimulatedDetector("sim-jetson", 0.02), port=server.port)
            server.start()
        r = client.detect(b"fake-jpeg-%d" % i, 640, 480)
        print(f"frame {r.frame_id:3d} via {r.source:6s} ({r.model}) {r.latency_ms:6.1f} ms "
              f"{len(r.detections)} det")
        time.sleep(1 / args.fps)
    print(client.stats)
    client.stop()
    server.stop()


if __name__ == "__main__":
    main()
