enum EventKind { fall, medication, system, connection }

/// One entry of the event history. Falls and reminders are *upserted* by
/// [key] (alert_id / reminder_id) because the robot re-sends the same alert
/// every 30 s until acknowledged and updates a reminder's result later.
class HistoryEvent {
  const HistoryEvent({
    required this.key,
    required this.kind,
    required this.ts,
    required this.title,
    this.detail = '',
    this.status = '',
    this.scheduledAt,
  });

  final String key;
  final EventKind kind;

  /// Local time (ms since epoch) when the event was first seen.
  final int ts;
  final String title;
  final String detail;

  /// fall: open|acknowledged · medication: pending|confirmed|declined|
  /// no_response · system: info|warning|critical.
  final String status;

  /// Medication only: scheduled time (robot clock, ms since epoch).
  final int? scheduledAt;

  bool get isOpenFall => kind == EventKind.fall && status == 'open';
  bool get isMissedMedication =>
      kind == EventKind.medication &&
      (status == 'declined' || status == 'no_response');

  HistoryEvent copyWith({String? title, String? detail, String? status}) =>
      HistoryEvent(
        key: key,
        kind: kind,
        ts: ts,
        title: title ?? this.title,
        detail: detail ?? this.detail,
        status: status ?? this.status,
        scheduledAt: scheduledAt,
      );

  Map<String, dynamic> toJson() => {
        'key': key,
        'kind': kind.name,
        'ts': ts,
        'title': title,
        'detail': detail,
        'status': status,
        if (scheduledAt != null) 'scheduled_at': scheduledAt,
      };

  static HistoryEvent? fromJson(Object? j) {
    if (j is! Map) return null;
    final kind = EventKind.values.where((k) => k.name == j['kind']);
    if (kind.isEmpty || j['key'] is! String || j['ts'] is! int) return null;
    return HistoryEvent(
      key: j['key'] as String,
      kind: kind.first,
      ts: j['ts'] as int,
      title: (j['title'] as String?) ?? '',
      detail: (j['detail'] as String?) ?? '',
      status: (j['status'] as String?) ?? '',
      scheduledAt: j['scheduled_at'] as int?,
    );
  }
}
