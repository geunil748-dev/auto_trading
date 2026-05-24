import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:stock_monitor_app/monitor_app.dart';

void main() {
  testWidgets('모니터 앱 첫 화면을 표시한다', (WidgetTester tester) async {
    await tester.pumpWidget(const MonitorApp());

    expect(find.byType(MaterialApp), findsOneWidget);
    expect(find.byType(TextField), findsWidgets);
  });
}
