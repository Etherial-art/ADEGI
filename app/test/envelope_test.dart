import 'package:adegi_app/protocol/envelope.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  test('parses a valid envelope', () {
    final e = Envelope.tryParse(
        '{"v":1,"type":"behavior.state","src":"behavior","seq":4,"ts":10,'
        '"data":{"mode":"follow"},"reply_to":2,"extra":"ignored"}')!;
    expect(e.type, 'behavior.state');
    expect(e.data['mode'], 'follow');
    expect(e.replyTo, 2);
  });

  test('rejects junk, other versions and non-text frames without throwing', () {
    expect(Envelope.tryParse('not json'), isNull);
    expect(Envelope.tryParse('[1,2]'), isNull);
    expect(Envelope.tryParse('{"v":2,"type":"x"}'), isNull);
    expect(Envelope.tryParse('{"v":1}'), isNull);
    expect(Envelope.tryParse(<int>[1, 2]), isNull);
  });

  test('encode/parse round trip', () {
    const e = Envelope(type: 'alert.ack', src: 'app', seq: 1, ts: 5, data: {'alert_id': 'a'});
    final back = Envelope.tryParse(e.encode())!;
    expect(back.type, 'alert.ack');
    expect(back.data['alert_id'], 'a');
  });
}
