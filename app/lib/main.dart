import 'package:flutter/material.dart';

import 'services/robot_link.dart';
import 'services/storage.dart';
import 'state/app_controller.dart';
import 'ui/home_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final storage = await AppStorage.open();
  final controller = AppController(link: WebSocketRobotLink(), storage: storage)..start();
  runApp(AdegiApp(controller: controller));
}

class AdegiApp extends StatelessWidget {
  const AdegiApp({super.key, required this.controller});
  final AppController controller;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ADEGI',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: Colors.teal, useMaterial3: true),
      home: HomePage(controller: controller),
    );
  }
}
