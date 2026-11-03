import 'package:flutter/material.dart';

import '../models/history_event.dart';
import '../state/app_controller.dart';
import 'format.dart';
import 'history_tab.dart' show medicationStatusLabel;

class MedicationTab extends StatelessWidget {
  const MedicationTab({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final meds = controller.medications.toList()
      ..sort((a, b) => (b.scheduledAt ?? b.ts).compareTo(a.scheduledAt ?? a.ts));
    if (meds.isEmpty) {
      return const Center(
        child: Padding(
          padding: EdgeInsets.all(24),
          child: Text(
            'Aquí aparecerán los recordatorios de medicamento que el robot '
            'le haga a la persona y si los confirmó.',
            textAlign: TextAlign.center,
          ),
        ),
      );
    }
    final missed = meds.where((m) => m.isMissedMedication).length;
    return ListView(children: [
      if (missed > 0)
        Container(
          color: Theme.of(context).colorScheme.errorContainer,
          padding: const EdgeInsets.all(12),
          child: Text(
            '$missed recordatorio(s) sin confirmar. La confirmación es verbal: '
            '"sin respuesta" no significa que no se tomó el medicamento.',
            style: TextStyle(color: Theme.of(context).colorScheme.onErrorContainer),
          ),
        ),
      for (final m in meds) _MedTile(med: m),
    ]);
  }
}

class _MedTile extends StatelessWidget {
  const _MedTile({required this.med});
  final HistoryEvent med;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final (icon, color) = switch (med.status) {
      'confirmed' => (Icons.check_circle, Colors.green.shade700),
      'declined' || 'no_response' => (Icons.error, scheme.error),
      _ => (Icons.schedule, Colors.orange.shade800),
    };
    return ListTile(
      leading: Icon(icon, color: color),
      title: Text(med.title),
      subtitle: Text('Programado: ${dateTime(med.scheduledAt ?? med.ts)}'),
      trailing: Text(medicationStatusLabel(med.status),
          style: TextStyle(color: color, fontWeight: FontWeight.bold)),
    );
  }
}
