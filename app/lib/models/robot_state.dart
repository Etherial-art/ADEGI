/// Robot modes from `behavior.state` (docs/protocol.md §3.3).
enum RobotMode {
  idle('En reposo', 'Quieto, esperando'),
  roam('Explorando', 'Recorre la casa buscando a la persona'),
  follow('Siguiendo', 'Acompañando a la persona'),
  docking('Yendo a cargar', 'Regresando a la estación de carga'),
  charging('Cargando', 'Conectado a la estación de carga'),
  alert('En alerta', 'Atendiendo una posible emergencia'),
  error('Con falla', 'El robot reporta un error'),
  unknown('Desconocido', 'Modo no reconocido por esta versión de la app');

  const RobotMode(this.label, this.description);
  final String label;
  final String description;

  static RobotMode parse(Object? raw) {
    for (final m in RobotMode.values) {
      if (m.name == raw && m != RobotMode.unknown) return m;
    }
    return RobotMode.unknown;
  }
}

/// Latest `behavior.state` snapshot.
class RobotState {
  const RobotState({
    required this.mode,
    required this.batteryPct,
    required this.docked,
  });

  final RobotMode mode;

  /// 0–100, or null when the robot did not report it.
  final int? batteryPct;
  final bool docked;

  static const batteryLowPct = 20;
  bool get batteryLow => batteryPct != null && batteryPct! <= batteryLowPct;

  static RobotState? fromData(Map<String, dynamic> d) {
    final b = d['battery_pct'];
    return RobotState(
      mode: RobotMode.parse(d['mode']),
      batteryPct: b is num ? b.round().clamp(0, 100) : null,
      docked: d['docked'] == true,
    );
  }
}

/// Last time the robot's camera saw a person (derived from `vision.persons`).
class LastSeen {
  const LastSeen({required this.at, this.identity, this.posture});

  /// Local wall-clock time (ms since epoch) when the sighting was received.
  /// We use our own clock, not the robot's `ts`, so a skewed robot clock
  /// cannot produce "seen in the future".
  final int at;
  final String? identity;
  final String? posture;

  Map<String, dynamic> toJson() =>
      {'at': at, 'identity': identity, 'posture': posture};

  static LastSeen? fromJson(Object? j) {
    if (j is! Map || j['at'] is! int) return null;
    return LastSeen(
      at: j['at'] as int,
      identity: j['identity'] as String?,
      posture: j['posture'] as String?,
    );
  }
}
