import 'dart:convert';

/// Protocol version this app understands (docs/protocol.md §2).
const int kProtocolVersion = 1;

/// Common JSON envelope shared by every message (docs/protocol.md §2).
class Envelope {
  const Envelope({
    required this.type,
    required this.src,
    required this.seq,
    required this.ts,
    required this.data,
    this.v = kProtocolVersion,
    this.replyTo,
  });

  final int v;
  final String type;
  final String src;
  final int seq;
  final int ts;
  final Map<String, dynamic> data;
  final int? replyTo;

  /// Parses a raw WebSocket frame. Returns null (never throws) for anything
  /// malformed or from an incompatible protocol version: the protocol says
  /// receivers must ignore what they do not understand instead of crashing.
  static Envelope? tryParse(Object? raw) {
    if (raw is! String) return null;
    try {
      final json = jsonDecode(raw);
      if (json is! Map<String, dynamic>) return null;
      final v = json['v'];
      final type = json['type'];
      if (v != kProtocolVersion || type is! String) return null;
      final data = json['data'];
      return Envelope(
        v: v as int,
        type: type,
        src: json['src'] is String ? json['src'] as String : '',
        seq: json['seq'] is int ? json['seq'] as int : 0,
        ts: json['ts'] is int ? json['ts'] as int : 0,
        data: data is Map<String, dynamic> ? data : const {},
        replyTo: json['reply_to'] is int ? json['reply_to'] as int : null,
      );
    } on FormatException {
      return null;
    }
  }

  String encode() => jsonEncode({
        'v': v,
        'type': type,
        'src': src,
        'seq': seq,
        'ts': ts,
        'data': data,
        if (replyTo != null) 'reply_to': replyTo,
      });
}
