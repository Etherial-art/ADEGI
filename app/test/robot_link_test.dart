import 'dart:async';
import 'dart:io';

import 'package:adegi_app/services/robot_link.dart';
import 'package:flutter_test/flutter_test.dart';

/// Real sockets (no mocks): checks connect, receive, send and reconnect.
void main() {
  test('connects, receives, sends, and reconnects after the server drops', () async {
    final received = <String>[];
    HttpServer? server;
    WebSocket? serverSocket;

    Future<HttpServer> startServer(int port) async {
      final s = await HttpServer.bind(InternetAddress.loopbackIPv4, port);
      s.listen((req) async {
        final ws = await WebSocketTransformer.upgrade(req);
        serverSocket = ws;
        ws.listen((m) => received.add(m as String));
        ws.add('{"v":1,"type":"sys.heartbeat","src":"gateway","seq":1,"ts":1,"data":{"status":"ok"}}');
        ws.add('garbage that must be ignored');
      });
      return s;
    }

    server = await startServer(0);
    final port = server.port;
    final link = WebSocketRobotLink(maxBackoff: const Duration(milliseconds: 200));
    addTearDown(link.dispose);

    final types = <String>[];
    link.messages.listen((e) => types.add(e.type));
    final statuses = <LinkStatus>[];
    link.status.listen(statuses.add);

    expect(link.send('alert.ack', {}), isFalse, reason: 'not connected yet');

    link.connect(Uri.parse('ws://127.0.0.1:$port/app'));
    await link.status.firstWhere((s) => s == LinkStatus.connected).timeout(const Duration(seconds: 5));
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(types, ['sys.heartbeat']); // garbage frame dropped silently

    expect(link.send('alert.ack', {'alert_id': 'a-1', 'by': 'familiar_1'}), isTrue);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    expect(received.single, contains('"type":"alert.ack"'));
    expect(received.single, contains('"src":"app"'));

    // Robot disappears -> app must report disconnected, then recover on its own.
    await serverSocket!.close();
    await server.close(force: true);
    await link.status.firstWhere((s) => s == LinkStatus.disconnected).timeout(const Duration(seconds: 5));
    expect(link.send('alert.ack', {}), isFalse);

    server = await startServer(port);
    addTearDown(() => server!.close(force: true));
    await link.status.firstWhere((s) => s == LinkStatus.connected).timeout(const Duration(seconds: 10));
    expect(statuses, contains(LinkStatus.disconnected));
  });
}
