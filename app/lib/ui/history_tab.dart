import 'package:flutter/material.dart';

import '../models/history_event.dart';
import '../state/app_controller.dart';
import 'format.dart';

class HistoryTab extends StatefulWidget {
  const HistoryTab({super.key, required this.controller});
  final AppController controller;

  @override
  State<HistoryTab> createState() => _HistoryTabState();
}

class _HistoryTabState extends State<HistoryTab> {
  EventKind? _filter; // null = all

  static const _labels = {
    null: 'Todo',
    EventKind.fall: 'Caídas',
    EventKind.medication: 'Medicinas',
    EventKind.system: 'Sistema',
    EventKind.connection: 'Conexión',
  };

  @override
  Widget build(BuildContext context) {
    final events = widget.controller.events
        .where((e) => _filter == null || e.kind == _filter)
        .toList();
    return Column(children: [
      SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        child: Row(children: [
          for (final entry in _labels.entries)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                label: Text(entry.value),
                selected: _filter == entry.key,
                onSelected: (_) => setState(() => _filter = entry.key),
              ),
            ),
        ]),
      ),
      Expanded(
        child: events.isEmpty
            ? const Center(child: Text('Sin eventos todavía'))
            : ListView.separated(
                itemCount: events.length,
                separatorBuilder: (_, _) => const Divider(height: 1),
                itemBuilder: (_, i) => _EventTile(event: events[i]),
              ),
      ),
    ]);
  }
}

class _EventTile extends StatelessWidget {
  const _EventTile({required this.event});
  final HistoryEvent event;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (icon, color) = switch (event.kind) {
      EventKind.fall => (Icons.personal_injury_outlined, scheme.error),
      EventKind.medication => (Icons.medication_outlined, scheme.primary),
      EventKind.system => (
          Icons.build_circle_outlined,
          event.status == 'critical' ? scheme.error : Colors.orange.shade800
        ),
      EventKind.connection => (Icons.wifi_tethering, scheme.outline),
    };
    final extra = switch (event.kind) {
      EventKind.fall => event.status == 'open' ? 'SIN RECONOCER' : 'Reconocida',
      EventKind.medication => medicationStatusLabel(event.status),
      _ => '',
    };
    return ListTile(
      leading: Icon(icon, color: color),
      title: Text(event.title),
      subtitle: Text([
        dateTime(event.ts),
        if (extra.isNotEmpty) extra,
        if (event.detail.isNotEmpty) event.detail,
      ].join(' · ')),
    );
  }
}

String medicationStatusLabel(String status) => switch (status) {
      'confirmed' => 'Tomada',
      'declined' => 'Rechazada',
      'no_response' => 'Sin respuesta',
      _ => 'Pendiente',
    };
