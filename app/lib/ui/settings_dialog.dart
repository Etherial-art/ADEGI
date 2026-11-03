import 'package:flutter/material.dart';

import '../state/app_controller.dart';

Future<void> showSettingsDialog(BuildContext context, AppController c) {
  final url = TextEditingController(text: c.url);
  final id = TextEditingController(text: c.familyId);
  String? error;
  return showDialog<void>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, setState) => AlertDialog(
        title: const Text('Conexión con el robot'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          TextField(
            controller: url,
            keyboardType: TextInputType.url,
            decoration: InputDecoration(
              labelText: 'Dirección WebSocket',
              helperText: 'Ej. ws://192.168.1.50:8765/app\n'
                  'Emulador Android: ws://10.0.2.2:8765/app',
              helperMaxLines: 3,
              errorText: error,
            ),
          ),
          TextField(
            controller: id,
            decoration: const InputDecoration(
              labelText: 'Tu identificador',
              helperText: 'Se envía al reconocer una alerta',
            ),
          ),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancelar')),
          FilledButton(
            onPressed: () {
              final uri = Uri.tryParse(url.text.trim());
              if (uri == null || !(uri.scheme == 'ws' || uri.scheme == 'wss') || uri.host.isEmpty) {
                setState(() => error = 'Debe empezar con ws:// o wss://');
                return;
              }
              c.updateSettings(
                url: uri.toString(),
                familyId: id.text.trim().isEmpty ? 'familiar_1' : id.text.trim(),
              );
              Navigator.pop(ctx);
            },
            child: const Text('Guardar'),
          ),
        ],
      ),
    ),
  );
}
