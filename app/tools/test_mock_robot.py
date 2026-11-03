"""Smoke test for the mock robot: python -m unittest test_mock_robot -v"""
import asyncio
import json
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from mock_robot import MockRobot, reject_other_paths


async def recv_until(ws, type_, timeout=5):
    async def loop():
        while True:
            msg = json.loads(await ws.recv())
            if msg["type"] == type_:
                return msg
    return await asyncio.wait_for(loop(), timeout)


class MockRobotTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.robot = MockRobot(resend_s=0.2)
        self.server = await serve(self.robot.handler, "127.0.0.1", 0, process_request=reject_other_paths)
        self.port = self.server.sockets[0].getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/app"
        self.bg = [asyncio.create_task(self.robot.resend_loop())]

    async def asyncTearDown(self):
        for t in self.bg:
            t.cancel()
        self.server.close()
        await self.server.wait_closed()

    async def test_state_on_connect_and_envelope(self):
        async with connect(self.url) as ws:
            msg = await recv_until(ws, "behavior.state")
            self.assertEqual(msg["v"], 1)
            self.assertEqual(msg["src"], "behavior")
            self.assertIn("battery_pct", msg["data"])

    async def test_alert_queued_resent_and_acked(self):
        alert_id = await self.robot.fall()  # nobody connected: stays queued
        async with connect(self.url) as ws:
            first = await recv_until(ws, "alert.fall")
            self.assertEqual(first["data"]["alert_id"], alert_id)
            await recv_until(ws, "alert.fall")  # re-sent while unacknowledged
            await ws.send(json.dumps({"v": 1, "type": "alert.ack", "src": "app", "seq": 1,
                                      "ts": 0, "data": {"alert_id": alert_id, "by": "familiar_1"}}))
            await asyncio.sleep(0.1)
            self.assertNotIn(alert_id, self.robot.pending_alerts)

    async def test_set_mode_ack_and_junk_ignored(self):
        async with connect(self.url) as ws:
            await ws.send("not json")
            await ws.send(json.dumps({"v": 1, "type": "behavior.set_mode", "src": "app",
                                      "seq": 7, "ts": 0, "data": {"mode": "follow"}}))
            ack = await recv_until(ws, "behavior.ack")
            self.assertEqual(ack["reply_to"], 7)
            self.assertTrue(ack["data"]["ok"])

    async def test_wrong_path_rejected(self):
        with self.assertRaises(Exception):
            async with connect(f"ws://127.0.0.1:{self.port}/other"):
                pass


if __name__ == "__main__":
    unittest.main()
