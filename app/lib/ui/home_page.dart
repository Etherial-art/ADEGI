import 'package:flutter/material.dart';

import '../models/history_event.dart';
import '../state/app_controller.dart';
import 'format.dart';
import 'history_tab.dart';
import 'medication_tab.dart';
import 'settings_dialog.dart';
import 'status_tab.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.controller});
  final AppController controller;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final c = widget.controller;
    return ListenableBuilder(
      listenable: c,
      builder: (context, _) {
        final scheme = Theme.of(context).colorScheme;
        final falls = c.openFalls.toList();
        final pages = [
          StatusTab(controller: c),
          HistoryTab(controller: c),
          MedicationTab(controller: c),
        ];
        return Scaffold(
          appBar: AppBar(
            title: const Text('ADEGI'),
            actions: [
              Icon(
                c.isLive ? Icons.circle : Icons.circle_outlined,
                size: 12,
                color: c.isLive ? Colors.green : scheme.error,
              ),
              IconButton(
                tooltip: 'Conexión',
                icon: const Icon(Icons.settings),
                onPressed: () => showSettingsDialog(context, c),
              ),
            ],
          ),
          body: Column(children: [
            for (final f in falls) _FallBanner(alert: f, controller: c),
            Expanded(child: pages[_tab]),
          ]),
          bottomNavigationBar: NavigationBar(
            selectedIndex: _tab,
            onDestinationSelected: (i) => setState(() => _tab = i),
            destinations: [
              const NavigationDestination(icon: Icon(Icons.smart_toy_outlined), label: 'Estado'),
              const NavigationDestination(icon: Icon(Icons.history), label: 'Historial'),
              NavigationDestination(
                icon: Badge(
                  isLabelVisible: c.medications.any((m) => m.isMissedMedication),
                  child: const Icon(Icons.medication_outlined),
                ),
                label: 'Medicinas',
              ),
            ],
          ),
        );
      },
    );
  }
}

/// Persistent red banner shown on every tab until the alert is acknowledged.
class _FallBanner extends StatelessWidget {
  const _FallBanner({required this.alert, required this.controller});
  final HistoryEvent alert;
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.error,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(children: [
          Icon(Icons.warning_amber_rounded, color: scheme.onError, size: 36),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(alert.title,
                  style: TextStyle(color: scheme.onError, fontWeight: FontWeight.bold, fontSize: 16)),
              Text('Detectada a las ${clock(alert.ts)}',
                  style: TextStyle(color: scheme.onError)),
            ]),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
                backgroundColor: scheme.onError, foregroundColor: scheme.error),
            onPressed: () {
              if (!controller.acknowledge(alert)) {
                ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                    content: Text('Sin conexión: no se pudo reconocer la alerta')));
              }
            },
            child: const Text('Reconocer'),
          ),
        ]),
      ),
    );
  }
}
