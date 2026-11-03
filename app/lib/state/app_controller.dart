import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';

import '../models/history_event.dart';
import '../models/robot_state.dart';
import '../protocol/envelope.dart';
import '../services/robot_link.dart';
import '../services/storage.dart';

/// What the UI should believe about the robot link. Richer than the socket
/// state: a socket can be open while the robot has gone silent.
enum Connectivity { connecting, online, noSignal, offline }

/// Single source of truth for the UI (plain ChangeNotifier, no extra
/// state-management package).
class AppController extends ChangeNotifier {
  AppController({
    required this.link,
    required this.storage,
    DateTime Function()? clock,
    void Function()? alertFeedback,
    this.staleAfter = const Duration(seconds: 5),
  })  : _clock = clock ?? DateTime.now,
        _alertFeedback = alertFeedback ?? _defaultAlertFeedback {
    _events = storage.loadEvents();
    _lastSeen = storage.loadLastSeen();
    _msgSub = link.messages.listen(_onMessage);
    _statusSub = link.status.listen(_onLinkStatus);
    // 1 s tick: refreshes "hace X s" labels and detects a silent robot.
    _ticker = Timer.periodic(const Duration(seconds: 1), (_) => _tick());
  }

  /// With no message for this long the socket is considered "alive but
  /// silent". The gateway forwards `sys.heartbeat` every 1 s (protocol §3.1),
  /// so 5 s means several were missed.
  final Duration staleAfter;

  final RobotLink link;
  final AppStorage storage;
  final DateTime Function() _clock;
  final void Function() _alertFeedback;
  late final StreamSubscription<Envelope> _msgSub;
  late final StreamSubscription<LinkStatus> _statusSub;
  late final Timer _ticker;

  List<HistoryEvent> _events = [];
  RobotState? _state;
  LastSeen? _lastSeen;
  DateTime? _lastMessageAt;
  DateTime? _lastStateAt;
  String? _gatewayHealth;
  bool _batteryWarned = false;
  DateTime _lastSeenPersisted = DateTime.fromMillisecondsSinceEpoch(0);
  Connectivity _connectivity = Connectivity.offline;

  // ---- read API for the UI ----
  List<HistoryEvent> get events => List.unmodifiable(_events);
  Iterable<HistoryEvent> get openFalls => _events.where((e) => e.isOpenFall);
  Iterable<HistoryEvent> get medications =>
      _events.where((e) => e.kind == EventKind.medication);
  RobotState? get state => _state;
  LastSeen? get lastSeen => _lastSeen;
  DateTime? get lastStateAt => _lastStateAt;
  DateTime? get lastMessageAt => _lastMessageAt;
  String? get gatewayHealth => _gatewayHealth;
  Connectivity get connectivity => _connectivity;
  bool get isLive => _connectivity == Connectivity.online;
  DateTime get now => _clock();
  String get url => storage.url;
  String get familyId => storage.familyId;

  // ---- actions ----
  void start() => link.connect(Uri.parse(storage.url));

  Future<void> updateSettings({required String url, required String familyId}) async {
    await storage.saveSettings(url: url, familyId: familyId);
    link.connect(Uri.parse(url));
    notifyListeners();
  }

  /// Acknowledges a fall alert. Only marks it handled locally if the message
  /// actually left the phone; otherwise the robot would keep nagging while the
  /// UI claims it is dealt with. Returns false when offline.
  bool acknowledge(HistoryEvent alert) {
    final alertId = alert.key.replaceFirst('alert:', '');
    final sent = link.send('alert.ack', {'alert_id': alertId, 'by': familyId});
    if (sent) {
      _upsert(alert.copyWith(status: 'acknowledged'));
      notifyListeners();
    }
    return sent;
  }

  // ---- internals ----
  void _onLinkStatus(LinkStatus s) {
    switch (s) {
      case LinkStatus.connecting:
        if (_connectivity != Connectivity.online) {
          _connectivity = Connectivity.connecting;
        }
      case LinkStatus.connected:
        _lastMessageAt = _clock(); // grace period until the first heartbeat
        _connectivity = Connectivity.online;
        _log('conn:up:${_clock().millisecondsSinceEpoch}', EventKind.connection,
            'Conectado al robot');
      case LinkStatus.disconnected:
        if (_connectivity == Connectivity.online ||
            _connectivity == Connectivity.noSignal) {
          _log('conn:down:${_clock().millisecondsSinceEpoch}', EventKind.connection,
              'Conexión con el robot perdida');
        }
        _connectivity = Connectivity.offline;
    }
    notifyListeners();
  }

  void _tick() {
    if (link.current == LinkStatus.connected && _lastMessageAt != null) {
      final silent = _clock().difference(_lastMessageAt!) > staleAfter;
      final next = silent ? Connectivity.noSignal : Connectivity.online;
      if (next != _connectivity) {
        _connectivity = next;
        if (silent) {
          _log('conn:silent:${_clock().millisecondsSinceEpoch}',
              EventKind.connection, 'El robot dejó de enviar datos');
        }
      }
    }
    notifyListeners();
  }

  void _onMessage(Envelope e) {
    final nowMs = _clock().millisecondsSinceEpoch;
    _lastMessageAt = _clock();
    if (_connectivity == Connectivity.noSignal) {
      _connectivity = Connectivity.online;
    }
    final d = e.data;
    switch (e.type) {
      case 'sys.heartbeat':
        _gatewayHealth = d['status'] as String?;
      case 'sys.error':
        final sev = (d['severity'] as String?) ?? 'warning';
        _log('err:${e.src}:${e.seq}', EventKind.system,
            (d['code'] as String?) ?? 'Error del sistema',
            detail: (d['message'] as String?) ?? '', status: sev);
      case 'behavior.state':
        _onBehaviorState(d);
      case 'vision.persons':
        _onPersons(d, nowMs);
      case 'alert.fall':
        _onFall(d, nowMs);
      case 'reminder.medication':
        _onMedication(d, nowMs);
      default:
        // Includes behavior.ack, vision.fall_detected (the app consumes
        // alert.fall instead) and anything new: ignore, per protocol §2.
        debugPrint('controller: ignoring ${e.type}');
    }
    notifyListeners();
  }

  void _onBehaviorState(Map<String, dynamic> d) {
    final s = RobotState.fromData(d);
    if (s == null) return;
    final prevMode = _state?.mode;
    _state = s;
    _lastStateAt = _clock();
    // Battery-low notice, re-armed only after recovering above 30 % so a
    // reading hovering around 20 % does not spam the history.
    if (s.batteryLow && !_batteryWarned) {
      _batteryWarned = true;
      _log('battery:${_clock().millisecondsSinceEpoch}', EventKind.system,
          'Batería baja (${s.batteryPct}%)', status: 'warning');
    } else if ((s.batteryPct ?? 0) > 30) {
      _batteryWarned = false;
    }
    if (s.mode == RobotMode.error && prevMode != RobotMode.error) {
      _log('mode:error:${_clock().millisecondsSinceEpoch}', EventKind.system,
          'El robot entró en modo de falla', status: 'critical');
    }
  }

  void _onPersons(Map<String, dynamic> d, int nowMs) {
    final persons = d['persons'];
    if (persons is! List || persons.isEmpty) return;
    final first = persons.whereType<Map<dynamic, dynamic>>().firstOrNull;
    if (first == null) return;
    _lastSeen = LastSeen(
      at: nowMs,
      identity: first['identity'] as String?,
      posture: first['posture'] as String?,
    );
    // vision.persons arrives at ~10 Hz; do not write to disk that often.
    if (_clock().difference(_lastSeenPersisted) > const Duration(seconds: 10)) {
      _lastSeenPersisted = _clock();
      unawaited(storage.saveLastSeen(_lastSeen!));
    }
  }

  void _onFall(Map<String, dynamic> d, int nowMs) {
    final id = d['alert_id'];
    if (id is! String) return;
    final key = 'alert:$id';
    final who = (d['identity'] as String?) ?? 'Una persona';
    final conf = d['conf'] is num ? ((d['conf'] as num) * 100).round() : null;
    final robotAcked = d['acknowledged'] == true;
    final existing = _events.where((e) => e.key == key).firstOrNull;
    if (existing != null) {
      // Robot re-sends unacknowledged alerts every 30 s. Never reopen one we
      // already acknowledged; do close one another family member acknowledged.
      if (robotAcked && existing.status == 'open') {
        _upsert(existing.copyWith(status: 'acknowledged'));
      }
      return;
    }
    _upsert(HistoryEvent(
      key: key,
      kind: EventKind.fall,
      ts: nowMs,
      title: 'Posible caída de $who',
      detail: conf == null ? '' : 'Confianza del detector: $conf%',
      status: robotAcked ? 'acknowledged' : 'open',
    ));
    if (!robotAcked) _alertFeedback();
  }

  void _onMedication(Map<String, dynamic> d, int nowMs) {
    final id = d['reminder_id'];
    if (id is! String) return;
    final key = 'med:$id';
    final result = (d['result'] as String?) ?? 'pending';
    final name = (d['medication'] as String?) ?? 'Medicamento';
    final scheduled = d['scheduled_at'] is int ? d['scheduled_at'] as int : null;
    final existing = _events.where((e) => e.key == key).firstOrNull;
    if (existing != null) {
      _upsert(existing.copyWith(status: result, title: name));
      return;
    }
    _upsert(HistoryEvent(
      key: key,
      kind: EventKind.medication,
      ts: nowMs,
      title: name,
      status: result,
      scheduledAt: scheduled,
    ));
  }

  void _log(String key, EventKind kind, String title,
      {String detail = '', String status = 'info'}) {
    _upsert(HistoryEvent(
      key: key,
      kind: kind,
      ts: _clock().millisecondsSinceEpoch,
      title: title,
      detail: detail,
      status: status,
    ));
  }

  /// Insert-or-replace by key, keeping the list newest-first and bounded.
  void _upsert(HistoryEvent e) {
    final i = _events.indexWhere((x) => x.key == e.key);
    if (i >= 0) {
      _events[i] = e;
    } else {
      _events.insert(0, e);
      _events.sort((a, b) => b.ts.compareTo(a.ts));
      if (_events.length > AppStorage.maxEvents) {
        _events = _events.sublist(0, AppStorage.maxEvents);
      }
    }
    unawaited(storage.saveEvents(_events));
  }

  static void _defaultAlertFeedback() {
    HapticFeedback.heavyImpact();
    SystemSound.play(SystemSoundType.alert);
  }

  @override
  void dispose() {
    _ticker.cancel();
    _msgSub.cancel();
    _statusSub.cancel();
    link.dispose();
    super.dispose();
  }
}
