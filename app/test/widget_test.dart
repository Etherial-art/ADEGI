import 'package:adegi_app/main.dart';
import 'package:adegi_app/services/robot_link.dart';
import 'package:adegi_app/services/storage.dart';
import 'package:adegi_app/state/app_controller.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'app_controller_test.dart' show FakeLink;

void main() {
  testWidgets('shows disconnected state, then live data and a fall banner', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final link = FakeLink();
    final c = AppController(
      link: link,
      storage: AppStorage(await SharedPreferences.getInstance()),
      alertFeedback: () {},
    );
    await tester.pumpWidget(AdegiApp(controller: c));
    expect(find.text('Desconectado'), findsOneWidget);
    expect(find.text('Aún no hay datos del robot'), findsOneWidget);

    await tester.runAsync(() => link.setStatus(LinkStatus.connected));
    await tester.runAsync(() => link.emit('behavior.state', {'mode': 'follow', 'battery_pct': 72, 'docked': false}));
    await tester.pump();
    expect(find.text('Conectado'), findsOneWidget);
    expect(find.text('72%'), findsOneWidget);
    expect(find.text('Siguiendo'), findsOneWidget);

    await tester.runAsync(() => link.emit('alert.fall', {'alert_id': 'a-1', 'identity': 'maria', 'acknowledged': false}));
    await tester.pump();
    expect(find.text('Posible caída de maria'), findsOneWidget);
    await tester.tap(find.text('Reconocer'));
    await tester.pump();
    expect(find.text('Posible caída de maria'), findsNothing);
    expect(link.sent.single.type, 'alert.ack');

    await tester.tap(find.text('Historial'));
    await tester.pump();
    expect(find.textContaining('Reconocida'), findsOneWidget);

    // Dispose inside the test: testWidgets checks for pending timers before
    // tearDown callbacks run.
    await tester.pumpWidget(const SizedBox());
    c.dispose();
  });
}
