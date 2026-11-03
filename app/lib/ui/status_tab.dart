import 'package:flutter/material.dart';

import '../models/robot_state.dart';
import '../state/app_controller.dart';
import 'format.dart';

class StatusTab extends StatelessWidget {
  const StatusTab({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final c = controller;
    final live = c.isLive;
    final s = c.state;
    final scheme = Theme.of(context).colorScheme;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        _ConnectionCard(controller: c),
        const SizedBox(height: 12),
        // Stale data must never look current: dim everything and say so.
        Opacity(
          opacity: live ? 1 : 0.45,
          child: Column(children: [
            if (!live)
              Padding(
                padding: const EdgeInsets.only(bottom: 8),
                child: Text(
                  c.lastStateAt == null
                      ? 'Aún no hay datos del robot'
                      : 'Último dato recibido ${ago(c.now, c.lastStateAt!.millisecondsSinceEpoch)}',
                  style: TextStyle(color: scheme.error, fontWeight: FontWeight.w600),
                ),
              ),
            _BatteryCard(state: s),
            const SizedBox(height: 12),
            _ModeCard(state: s),
            const SizedBox(height: 12),
            _LastSeenCard(controller: c),
          ]),
        ),
      ],
    );
  }
}

class _ConnectionCard extends StatelessWidget {
  const _ConnectionCard({required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (label, icon, color) = switch (controller.connectivity) {
      Connectivity.online => ('Conectado', Icons.wifi, Colors.green.shade700),
      Connectivity.connecting => ('Conectando…', Icons.sync, Colors.orange.shade800),
      Connectivity.noSignal => ('Sin señal del robot', Icons.signal_wifi_statusbar_connected_no_internet_4, scheme.error),
      Connectivity.offline => ('Desconectado', Icons.wifi_off, scheme.error),
    };
    return Card(
      child: ListTile(
        leading: Icon(icon, color: color, size: 32),
        title: Text(label, style: TextStyle(color: color, fontWeight: FontWeight.bold)),
        subtitle: Text(controller.url),
        trailing: controller.gatewayHealth == null || !controller.isLive
            ? null
            : Chip(label: Text('Robot: ${controller.gatewayHealth}')),
      ),
    );
  }
}

class _BatteryCard extends StatelessWidget {
  const _BatteryCard({required this.state});
  final RobotState? state;

  @override
  Widget build(BuildContext context) {
    final pct = state?.batteryPct;
    final low = state?.batteryLow ?? false;
    final color = low ? Theme.of(context).colorScheme.error : Colors.green.shade700;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Row(children: [
            Icon(state?.docked == true ? Icons.battery_charging_full : Icons.battery_full, color: color),
            const SizedBox(width: 8),
            const Text('Batería', style: TextStyle(fontWeight: FontWeight.bold)),
            const Spacer(),
            Text(pct == null ? '—' : '$pct%',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(color: color)),
          ]),
          const SizedBox(height: 8),
          LinearProgressIndicator(value: pct == null ? null : pct / 100, color: color, minHeight: 8),
          if (state != null) ...[
            const SizedBox(height: 8),
            Text(state!.docked ? 'En la estación de carga' : 'Fuera de la estación'
                '${low ? ' · batería baja' : ''}'),
          ],
        ]),
      ),
    );
  }
}

class _ModeCard extends StatelessWidget {
  const _ModeCard({required this.state});
  final RobotState? state;

  static const _icons = {
    RobotMode.idle: Icons.pause_circle_outline,
    RobotMode.roam: Icons.explore_outlined,
    RobotMode.follow: Icons.directions_walk,
    RobotMode.docking: Icons.home_outlined,
    RobotMode.charging: Icons.bolt,
    RobotMode.alert: Icons.warning_amber,
    RobotMode.error: Icons.error_outline,
    RobotMode.unknown: Icons.help_outline,
  };

  @override
  Widget build(BuildContext context) {
    final mode = state?.mode;
    return Card(
      child: ListTile(
        leading: Icon(_icons[mode] ?? Icons.help_outline, size: 32),
        title: Text(mode?.label ?? 'Sin datos'),
        subtitle: Text(mode?.description ?? 'Esperando el estado del robot'),
        trailing: const Text('Modo'),
      ),
    );
  }
}

class _LastSeenCard extends StatelessWidget {
  const _LastSeenCard({required this.controller});
  final AppController controller;

  static const _posture = {
    'standing': 'de pie',
    'sitting': 'sentada/o',
    'lying': 'acostada/o',
  };

  @override
  Widget build(BuildContext context) {
    final seen = controller.lastSeen;
    final who = seen?.identity ?? 'Una persona';
    final posture = _posture[seen?.posture];
    return Card(
      child: ListTile(
        leading: const Icon(Icons.visibility_outlined, size: 32),
        title: Text(seen == null ? 'Sin avistamientos' : '$who · ${ago(controller.now, seen.at)}'),
        subtitle: Text(seen == null
            ? 'El robot aún no ha visto a nadie'
            : 'Visto a las ${clock(seen.at)}${posture == null ? '' : ' · $posture'}'),
        trailing: const Text('Visto por última vez'),
      ),
    );
  }
}
