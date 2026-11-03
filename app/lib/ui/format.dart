String two(int n) => n.toString().padLeft(2, '0');

String clock(int ms) {
  final d = DateTime.fromMillisecondsSinceEpoch(ms);
  return '${two(d.hour)}:${two(d.minute)}';
}

String dateTime(int ms) {
  final d = DateTime.fromMillisecondsSinceEpoch(ms);
  return '${two(d.day)}/${two(d.month)} ${clock(ms)}';
}

/// "hace 5 min" style label, in Spanish.
String ago(DateTime now, int ms) {
  final s = now.difference(DateTime.fromMillisecondsSinceEpoch(ms)).inSeconds;
  if (s < 5) return 'ahora mismo';
  if (s < 60) return 'hace $s s';
  if (s < 3600) return 'hace ${s ~/ 60} min';
  if (s < 86400) return 'hace ${s ~/ 3600} h';
  return 'el ${dateTime(ms)}';
}
