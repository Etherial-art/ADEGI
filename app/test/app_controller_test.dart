import 'dart:async';

import 'package:adegi_app/models/history_event.dart';
import 'package:adegi_app/models/robot_state.dart';
import 'package:adegi_app/protocol/envelope.dart';
import 'package:adegi_app/services/robot_link.dart';
import 'package:adegi_app/services/storage.dart';
import 'package:adegi_app/state/app_controller.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

class FakeLink implements RobotLink {
  final _m = StreamController<Envelope>.broadcast();
  final _s = StreamController<LinkStatus>.broadcast();
  @override
  LinkStatus current = LinkStatus.disconnected;
  final sent = <Envelope>[];
  int _seq = 0;

  @override
  Stream<Envelope> get messages => _m.stream;
  @override
  Stream<LinkStatus> get status => _s.stream;
  @override
  void connect(Uri uri) {}
  @override
  Future<void> disconnect() async {}
  @override
  Future<void> dispose() async {}
  @override
  bool send(String type, Map<String, dynamic> data, {int? replyTo}) {
    if (current != LinkStatus.connected) return false;
    sent.add(Envelope(type: type, src: 'app', seq: ++_seq, ts: 0, data: data));
    return true;
  }

  Future<void> setStatus(LinkStatus s) async {
    current = s;
    _s.add(s);
    await pump();
  }

  Future<void> emit(String type, Map<String, dynamic> data) async {
    _m.add(Envelope(type: type, src: 'x', seq: 1, ts: 0, data: data));
    await pump();
  }

  static Future<void> pump() => Future<void>.delayed(Duration.zero);
}

void main() {
  late FakeLink link;
  late AppController c;
  late DateTime now;
  var feedback = 0;

  Future<AppController> make({Map<String, Object> prefs = const {}}) async {
    SharedPreferences.setMockInitialValues(prefs);
    link = FakeLink();
    now = DateTime(2026, 11, 3, 12);
    feedback = 0;
    return AppController(
      link: link,
      storage: await AppStorage.open(),
      clock: () => now,
      alertFeedback: () => feedback++,
    );
  }

  setUp(() async => c = await make());
  tearDown(() => c.dispose());

  test('behavior.state updates battery/mode and low battery logs once', () async {
    await link.setStatus(LinkStatus.connected);
    await link.emit('behavior.state', {'mode': 'follow', 'battery_pct': 72, 'docked': false});
    expect(c.state!.mode, RobotMode.follow);
    expect(c.state!.batteryPct, 72);

    await link.emit('behavior.state', {'mode': 'idle', 'battery_pct': 19});
    await link.emit('behavior.state', {'mode': 'idle', 'battery_pct': 18});
    expect(c.events.where((e) => e.title.startsWith('Batería baja')).length, 1);
  });

  test('unknown message types and modes are ignored, not fatal', () async {
    await link.emit('totally.new', {'a': 1});
    await link.emit('behavior.state', {'mode': 'moonwalk', 'battery_pct': 50});
    expect(c.state!.mode, RobotMode.unknown);
  });

  test('fall alert opens once, re-sends do not duplicate, ack sends alert.ack', () async {
    await link.setStatus(LinkStatus.connected);
    final alert = {'alert_id': 'a-1', 'identity': 'maria', 'conf': 0.88, 'acknowledged': false};
    await link.emit('alert.fall', alert);
    await link.emit('alert.fall', alert); // 30 s re-send
    expect(c.openFalls.length, 1);
    expect(feedback, 1);

    expect(c.acknowledge(c.openFalls.first), isTrue);
    expect(link.sent.single.type, 'alert.ack');
    expect(link.sent.single.data, {'alert_id': 'a-1', 'by': 'familiar_1'});
    expect(c.openFalls, isEmpty);

    await link.emit('alert.fall', alert); // late re-send must not reopen it
    expect(c.openFalls, isEmpty);
    expect(c.events.where((e) => e.kind == EventKind.fall).length, 1);
  });

  test('cannot acknowledge while offline; alert stays open', () async {
    await link.setStatus(LinkStatus.connected);
    await link.emit('alert.fall', {'alert_id': 'a-2', 'acknowledged': false});
    await link.setStatus(LinkStatus.disconnected);
    expect(c.acknowledge(c.openFalls.first), isFalse);
    expect(c.openFalls.length, 1);
  });

  test('medication reminder is updated in place when the result arrives', () async {
    final base = {'reminder_id': 'r-1', 'medication': 'Losartán 50 mg', 'scheduled_at': 1000};
    await link.emit('reminder.medication', {...base, 'result': 'pending'});
    await link.emit('reminder.medication', {...base, 'result': 'no_response'});
    final meds = c.medications.toList();
    expect(meds.length, 1);
    expect(meds.single.status, 'no_response');
    expect(meds.single.isMissedMedication, isTrue);
  });

  test('last seen only updates when someone is actually in frame', () async {
    await link.emit('vision.persons', {'persons': []});
    expect(c.lastSeen, isNull);
    await link.emit('vision.persons', {
      'persons': [{'identity': 'maria', 'posture': 'sitting'}]
    });
    expect(c.lastSeen!.identity, 'maria');
    expect(c.lastSeen!.at, now.millisecondsSinceEpoch);
  });

  test('connectivity: online -> noSignal when silent -> offline on disconnect', () async {
    await link.setStatus(LinkStatus.connected);
    expect(c.connectivity, Connectivity.online);
    now = now.add(const Duration(seconds: 6));
    await Future<void>.delayed(const Duration(milliseconds: 1100)); // let the 1 s ticker run
    expect(c.connectivity, Connectivity.noSignal);
    expect(c.isLive, isFalse);
    await link.emit('sys.heartbeat', {'status': 'ok'});
    expect(c.connectivity, Connectivity.online);
    await link.setStatus(LinkStatus.disconnected);
    expect(c.connectivity, Connectivity.offline);
  });

  test('history survives a restart', () async {
    await link.emit('alert.fall', {'alert_id': 'a-9', 'acknowledged': false});
    await link.emit('reminder.medication', {'reminder_id': 'r-9', 'medication': 'X', 'result': 'confirmed'});
    final prefs = await SharedPreferences.getInstance();
    final c2 = AppController(
      link: FakeLink(),
      storage: AppStorage(prefs),
      clock: () => now,
      alertFeedback: () {},
    );
    addTearDown(c2.dispose);
    expect(c2.events.map((e) => e.key), containsAll(['alert:a-9', 'med:r-9']));
    expect(c2.openFalls.length, 1);
  });
}
