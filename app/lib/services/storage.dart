import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

import '../models/history_event.dart';
import '../models/robot_state.dart';

/// Thin wrapper over SharedPreferences so the rest of the app (and tests)
/// never touch the plugin directly.
class AppStorage {
  AppStorage(this._prefs);
  final SharedPreferences _prefs;

  /// 10.0.2.2 is the host machine as seen from the Android emulator, which
  /// is where the Python mock robot runs during development.
  static const defaultUrl = 'ws://10.0.2.2:8765/app';
  static const defaultFamilyId = 'familiar_1';
  static const maxEvents = 200;

  static Future<AppStorage> open() async =>
      AppStorage(await SharedPreferences.getInstance());

  String get url => _prefs.getString('url') ?? defaultUrl;
  String get familyId => _prefs.getString('family_id') ?? defaultFamilyId;

  Future<void> saveSettings({required String url, required String familyId}) async {
    await _prefs.setString('url', url);
    await _prefs.setString('family_id', familyId);
  }

  List<HistoryEvent> loadEvents() {
    final raw = _prefs.getString('events');
    if (raw == null) return [];
    try {
      final list = jsonDecode(raw);
      if (list is! List) return [];
      return list.map(HistoryEvent.fromJson).whereType<HistoryEvent>().toList();
    } on FormatException {
      return [];
    }
  }

  Future<void> saveEvents(List<HistoryEvent> events) => _prefs.setString(
      'events', jsonEncode(events.take(maxEvents).map((e) => e.toJson()).toList()));

  LastSeen? loadLastSeen() {
    final raw = _prefs.getString('last_seen');
    if (raw == null) return null;
    try {
      return LastSeen.fromJson(jsonDecode(raw));
    } on FormatException {
      return null;
    }
  }

  Future<void> saveLastSeen(LastSeen s) =>
      _prefs.setString('last_seen', jsonEncode(s.toJson()));
}
