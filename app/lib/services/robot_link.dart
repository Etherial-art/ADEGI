import 'dart:async';
import 'dart:math';

import 'package:flutter/foundation.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../protocol/envelope.dart';

enum LinkStatus { connecting, connected, disconnected }

/// Transport between the app and the robot gateway. Abstract so the
/// controller can be tested without a network.
abstract class RobotLink {
  Stream<Envelope> get messages;
  Stream<LinkStatus> get status;
  LinkStatus get current;

  void connect(Uri uri);
  Future<void> disconnect();

  /// Sends a message; returns false (and sends nothing) when not connected.
  bool send(String type, Map<String, dynamic> data, {int? replyTo});
  Future<void> dispose();
}

typedef ChannelFactory = WebSocketChannel Function(Uri uri);

/// WebSocket implementation with automatic reconnection (exponential backoff
/// 1 s → 15 s). Reconnecting matters: the protocol (§5) makes the robot queue
/// alerts while the app is away and resend them when it comes back.
class WebSocketRobotLink implements RobotLink {
  WebSocketRobotLink({
    ChannelFactory? channelFactory,
    this.src = 'app',
    this.connectTimeout = const Duration(seconds: 8),
    this.maxBackoff = const Duration(seconds: 15),
  }) : _factory = channelFactory ?? WebSocketChannel.connect;

  final ChannelFactory _factory;
  final String src;
  final Duration connectTimeout;
  final Duration maxBackoff;

  final _messages = StreamController<Envelope>.broadcast();
  final _status = StreamController<LinkStatus>.broadcast();
  LinkStatus _current = LinkStatus.disconnected;
  WebSocketChannel? _channel;
  int _generation = 0; // bumped on every connect()/disconnect() to cancel old loops
  int _seq = 0;

  @override
  Stream<Envelope> get messages => _messages.stream;
  @override
  Stream<LinkStatus> get status => _status.stream;
  @override
  LinkStatus get current => _current;

  void _set(LinkStatus s) {
    if (s == _current) return;
    _current = s;
    _status.add(s);
  }

  @override
  void connect(Uri uri) {
    final gen = ++_generation;
    _channel?.sink.close();
    _channel = null;
    unawaited(_run(uri, gen));
  }

  Future<void> _run(Uri uri, int gen) async {
    var backoff = const Duration(seconds: 1);
    while (gen == _generation) {
      _set(LinkStatus.connecting);
      WebSocketChannel? ch;
      try {
        ch = _factory(uri);
        await ch.ready.timeout(connectTimeout);
        if (gen != _generation) {
          unawaited(ch.sink.close());
          return;
        }
        _channel = ch;
        _set(LinkStatus.connected);
        backoff = const Duration(seconds: 1);
        await for (final raw in ch.stream) {
          final env = Envelope.tryParse(raw);
          if (env == null) {
            debugPrint('robot_link: ignored unparseable/unsupported frame');
            continue;
          }
          _messages.add(env);
        }
      } catch (e) {
        debugPrint('robot_link: $e');
        unawaited(ch?.sink.close());
      }
      if (gen != _generation) return;
      _channel = null;
      _set(LinkStatus.disconnected);
      await Future<void>.delayed(backoff);
      backoff = Duration(
          milliseconds: min(backoff.inMilliseconds * 2, maxBackoff.inMilliseconds));
    }
  }

  @override
  Future<void> disconnect() async {
    _generation++;
    final ch = _channel;
    _channel = null;
    _set(LinkStatus.disconnected);
    await ch?.sink.close();
  }

  @override
  bool send(String type, Map<String, dynamic> data, {int? replyTo}) {
    final ch = _channel;
    if (ch == null || _current != LinkStatus.connected) return false;
    ch.sink.add(Envelope(
      type: type,
      src: src,
      seq: ++_seq,
      ts: DateTime.now().millisecondsSinceEpoch,
      data: data,
      replyTo: replyTo,
    ).encode());
    return true;
  }

  @override
  Future<void> dispose() async {
    await disconnect();
    await _messages.close();
    await _status.close();
  }
}
