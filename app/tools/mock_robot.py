#!/usr/bin/env python3
"""Mock ADEGI robot gateway: a WebSocket server that speaks docs/protocol.md.

Lets you develop and test the Flutter app without the real robot.

    pip install -r requirements.txt
    python mock_robot.py            # interactive: type commands, see `help`
    python mock_robot.py --demo     # also runs a scripted scenario

The server accepts connections on ws://<host>:<port>/app, like the real
gateway (protocol §1). It emits heartbeats, behavior state, person sightings,
fall alerts (re-sent until acknowledged, queued while no app is connected) and
medication reminders.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import sys
import time
from dataclasses import dataclass, field

from websockets.asyncio.server import ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response

PROTOCOL_VERSION = 1
MODES = ("idle", "roam", "follow", "docking", "charging", "alert", "error")


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class MockRobot:
    resend_s: float = 30.0  # protocol §3.4: unacknowledged alerts re-sent every 30 s
    mode: str = "idle"
    battery_pct: int = 80
    docked: bool = False
    person_visible: bool = True
    identity: str = "maria"
    posture: str = "standing"
    clients: set[ServerConnection] = field(default_factory=set)
    pending_alerts: dict[str, dict] = field(default_factory=dict)
    _seq: dict[str, itertools.count] = field(default_factory=dict)
    _alert_n: int = 0
    _reminder_n: int = 0
    started: float = field(default_factory=time.time)

    # ---- message plumbing -------------------------------------------------
    def envelope(self, src: str, type_: str, data: dict, reply_to: int | None = None) -> str:
        seq = next(self._seq.setdefault(src, itertools.count(1)))
        msg = {"v": PROTOCOL_VERSION, "type": type_, "src": src, "seq": seq, "ts": now_ms(), "data": data}
        if reply_to is not None:
            msg["reply_to"] = reply_to
        return json.dumps(msg)

    async def broadcast(self, src: str, type_: str, data: dict) -> None:
        raw = self.envelope(src, type_, data)
        for ws in list(self.clients):
            await self._safe_send(ws, raw)

    @staticmethod
    async def _safe_send(ws: ServerConnection, raw: str) -> None:
        try:
            await ws.send(raw)
        except Exception:  # client went away; its handler will clean up
            pass

    # ---- state emitters ---------------------------------------------------
    async def send_state(self) -> None:
        await self.broadcast("behavior", "behavior.state", {
            "mode": self.mode,
            "target_track_id": 3 if self.mode == "follow" else None,
            "battery_pct": self.battery_pct,
            "docked": self.docked,
        })

    async def send_alert(self, alert: dict) -> None:
        await self.broadcast("gateway", "alert.fall", alert)

    def log(self, text: str) -> None:
        print(f"[mock] {text}", flush=True)

    # ---- scenario actions (used by CLI and demo) --------------------------
    async def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.docked = mode == "charging"
        await self.send_state()

    async def set_battery(self, pct: int) -> None:
        self.battery_pct = max(0, min(100, pct))
        await self.send_state()

    async def fall(self) -> str:
        self._alert_n += 1
        alert_id = f"a-{time.strftime('%Y%m%d')}-{self._alert_n:04d}"
        alert = {
            "alert_id": alert_id,
            "identity": self.identity,
            "conf": 0.88,
            "snapshot_available": False,
            "acknowledged": False,
        }
        self.pending_alerts[alert_id] = alert
        self.mode = "alert"
        self.posture = "lying"
        await self.send_state()
        await self.send_alert(alert)  # no clients -> stays queued (protocol §5)
        self.log(f"fall alert {alert_id} ({len(self.clients)} client(s))")
        return alert_id

    async def medication(self, name: str = "Losartán 50 mg", result_after_s: float = 8.0,
                         result: str = "confirmed") -> None:
        self._reminder_n += 1
        rid = f"r-{self._reminder_n:04d}"
        data = {"reminder_id": rid, "medication": name, "scheduled_at": now_ms(), "result": "pending"}
        await self.broadcast("behavior", "reminder.medication", data)
        self.log(f"reminder {rid} {name} -> pending (will become {result} in {result_after_s}s)")
        await asyncio.sleep(result_after_s)
        await self.broadcast("behavior", "reminder.medication", {**data, "result": result})
        self.log(f"reminder {rid} -> {result}")

    async def error(self) -> None:
        await self.broadcast("gateway", "sys.error", {
            "code": "camera_unavailable", "message": "No frames for 2 s", "severity": "warning"})

    # ---- incoming messages from the app ----------------------------------
    async def on_message(self, ws: ServerConnection, raw: str | bytes) -> None:
        try:
            msg = json.loads(raw)
            type_, data, seq = msg["type"], msg.get("data", {}), msg.get("seq")
        except (ValueError, KeyError, TypeError):
            self.log("ignored malformed frame")  # protocol §2: never crash on junk
            return
        if type_ == "alert.ack":
            alert = self.pending_alerts.pop(data.get("alert_id"), None)
            self.log(f"alert.ack {data.get('alert_id')} by {data.get('by')} "
                     f"({'ok' if alert else 'unknown/already acked'})")
            if alert and not self.pending_alerts and self.mode == "alert":
                self.posture = "sitting"
                await self.set_mode("idle")
        elif type_ == "behavior.set_mode":
            mode = data.get("mode")
            ok = mode in MODES
            if ok:
                await self.set_mode(mode)
            payload = {"ok": True} if ok else {"ok": False, "reason": "invalid mode"}
            await self._safe_send(ws, self.envelope("behavior", "behavior.ack", payload, reply_to=seq))
        else:
            self.log(f"ignored unknown type {type_!r}")

    # ---- connection handler ----------------------------------------------
    async def handler(self, ws: ServerConnection) -> None:
        self.clients.add(ws)
        self.log(f"app connected ({len(self.clients)} total)")
        try:
            await self._safe_send(ws, self.envelope("behavior", "behavior.state", {
                "mode": self.mode, "target_track_id": None,
                "battery_pct": self.battery_pct, "docked": self.docked}))
            for alert in list(self.pending_alerts.values()):  # replay queued alerts
                await self._safe_send(ws, self.envelope("gateway", "alert.fall", alert))
            async for raw in ws:
                await self.on_message(ws, raw)
        finally:
            self.clients.discard(ws)
            self.log(f"app disconnected ({len(self.clients)} total)")

    # ---- periodic loops --------------------------------------------------
    async def heartbeat_loop(self) -> None:
        while True:
            await self.broadcast("gateway", "sys.heartbeat",
                                 {"status": "ok", "uptime_s": int(time.time() - self.started)})
            await asyncio.sleep(1)

    async def state_loop(self) -> None:
        while True:
            await asyncio.sleep(5)
            await self.send_state()

    async def persons_loop(self) -> None:
        frame = 0
        while True:
            await asyncio.sleep(1)  # real robot is 10-15 Hz; 1 Hz is enough for the app
            frame += 1
            persons = []
            if self.person_visible:
                persons = [{
                    "track_id": 3, "identity": self.identity, "identity_conf": 0.81,
                    "bbox": [0.31, 0.12, 0.22, 0.75], "conf": 0.93, "posture": self.posture,
                    "bearing_rad": -0.12, "distance_m": 1.8}]
            await self.broadcast("vision", "vision.persons",
                                 {"frame_id": frame, "backend": "npu", "persons": persons})

    async def resend_loop(self) -> None:
        while True:
            await asyncio.sleep(self.resend_s)
            for alert in list(self.pending_alerts.values()):
                self.log(f"re-sending unacknowledged {alert['alert_id']}")
                await self.send_alert(alert)

    async def battery_loop(self) -> None:
        while True:  # slow drain / charge so the status screen visibly moves
            await asyncio.sleep(10)
            delta = 2 if self.docked else -1
            self.battery_pct = max(0, min(100, self.battery_pct + delta))

    # ---- scripted scenario -------------------------------------------------
    async def demo(self) -> None:
        self.log("demo: follow in 5s, medication in 10s, fall in 25s, low battery in 60s")
        await asyncio.sleep(5)
        await self.set_mode("follow")
        await asyncio.sleep(5)
        asyncio.create_task(self.medication())
        await asyncio.sleep(15)
        await self.fall()
        await asyncio.sleep(35)
        await self.set_battery(18)

HELP = """commands:
  fall                  emit alert.fall (re-sent until the app acknowledges it)
  med [name]            medication reminder: pending, then confirmed after 8 s
  med-miss [name]       medication reminder that ends as no_response
  mode <m>              idle|roam|follow|docking|charging|alert|error
  battery <0-100>
  person on|off         whether the camera currently sees someone
  error                 emit sys.error
  help | quit"""


async def cli(robot: MockRobot, stop: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    print(HELP, flush=True)
    while not stop.is_set():
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if line == "":  # stdin closed (e.g. running under nohup): keep serving
            return
        cmd, _, arg = line.strip().partition(" ")
        arg = arg.strip()
        if cmd == "fall":
            await robot.fall()
        elif cmd == "med":
            asyncio.create_task(robot.medication(*([arg] if arg else [])))
        elif cmd == "med-miss":
            asyncio.create_task(robot.medication(*([arg] if arg else ["Metformina 850 mg"]),
                                                 result="no_response"))
        elif cmd == "mode" and arg in MODES:
            await robot.set_mode(arg)
        elif cmd == "battery" and arg.isdigit():
            await robot.set_battery(int(arg))
        elif cmd == "person" and arg in ("on", "off"):
            robot.person_visible = arg == "on"
        elif cmd == "error":
            await robot.error()
        elif cmd in ("quit", "exit"):
            stop.set()
        elif cmd:
            print(HELP, flush=True)


def reject_other_paths(_conn: ServerConnection, request: Request) -> Response | None:
    if request.path.split("?")[0] != "/app":
        return Response(404, "Not Found", Headers([("Content-Type", "text/plain")]), b"Connect to /app\n")
    return None


async def main_async(args: argparse.Namespace) -> None:
    robot = MockRobot(resend_s=args.resend_s)
    stop = asyncio.Event()
    async with serve(robot.handler, args.host, args.port, process_request=reject_other_paths):
        robot.log(f"listening on ws://{args.host}:{args.port}/app")
        tasks = [asyncio.create_task(c) for c in (
            robot.heartbeat_loop(), robot.state_loop(), robot.persons_loop(),
            robot.resend_loop(), robot.battery_loop(), cli(robot, stop))]
        if args.demo:
            tasks.append(asyncio.create_task(robot.demo()))
        await stop.wait()
        for t in tasks:
            t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.gather(*tasks)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--resend-s", type=float, default=30.0,
                   help="seconds between re-sends of unacknowledged alerts (default 30)")
    p.add_argument("--demo", action="store_true", help="run a scripted scenario")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(main_async(p.parse_args()))


if __name__ == "__main__":
    main()
