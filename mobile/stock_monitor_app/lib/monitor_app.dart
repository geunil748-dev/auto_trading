import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import 'monitor_utils.dart';
import 'monitor_widgets.dart';

const defaultMonitorApiUrl = String.fromEnvironment(
  'MONITOR_API_URL',
  defaultValue: 'http://10.0.2.2:4174/api/state',
);

class MonitorApp extends StatelessWidget {
  const MonitorApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '자동매매 모니터',
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: const Color(0xFF0B1117),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF58C7D5),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const MonitorHome(),
    );
  }
}

class MonitorHome extends StatefulWidget {
  const MonitorHome({super.key});

  @override
  State<MonitorHome> createState() => _MonitorHomeState();
}

class _MonitorHomeState extends State<MonitorHome> {
  final TextEditingController _server = TextEditingController(
    text: defaultMonitorApiUrl,
  );
  final TextEditingController _token = TextEditingController();

  Timer? _timer;
  bool _loading = false;
  String _active = 'mock';
  String _error = '';
  Map<String, dynamic> _state = const {};

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 20), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    _server.dispose();
    _token.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    if (_loading) return;
    setState(() {
      _loading = true;
      _error = '';
    });

    try {
      final uri = Uri.parse(_server.text.trim());
      final client = HttpClient();
      final request = await client.getUrl(uri);
      final token = _token.text.trim();
      if (token.isNotEmpty) {
        request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      }
      final response = await request.close();
      final text = await response.transform(utf8.decoder).join();
      client.close();
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw HttpException('HTTP ${response.statusCode}', uri: uri);
      }
      setState(() => _state = jsonDecode(text) as Map<String, dynamic>);
    } catch (error) {
      setState(() => _error = error.toString());
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final account = _selectedAccount();
    final summary = mapValue(account['account']);
    final holdings = listValue(account['holdings']);
    final targets = listValue(account['targets']);
    final logs = listValue(account['logs']);

    return Scaffold(
      appBar: AppBar(
        title: const Text('자동매매 모니터'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: StatusChip(connected: account['connected'] == true),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          children: [
            ServerBar(controller: _server, onRefresh: _load, loading: _loading),
            const SizedBox(height: 8),
            TextField(
              controller: _token,
              decoration: const InputDecoration(
                labelText: '모니터 토큰',
                border: OutlineInputBorder(),
                isDense: true,
              ),
              obscureText: true,
              onSubmitted: (_) => _load(),
            ),
            const SizedBox(height: 12),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'mock', label: Text('모의투자')),
                ButtonSegment(value: 'real', label: Text('실투자')),
              ],
              selected: {_active},
              onSelectionChanged: (value) => setState(() => _active = value.first),
            ),
            if (_error.isNotEmpty) ErrorBox(message: _error),
            const SizedBox(height: 12),
            SummaryGrid(active: _active, summary: summary),
            const SizedBox(height: 14),
            Section(title: '보유 종목', child: HoldingsList(rows: holdings)),
            const SizedBox(height: 14),
            Section(title: '리스트업 종목', child: TargetsList(rows: targets)),
            const SizedBox(height: 14),
            Section(title: '체결 시도 로그', child: LogsList(rows: logs)),
          ],
        ),
      ),
    );
  }

  Map<String, dynamic> _selectedAccount() {
    final accounts = mapValue(_state['accounts']);
    return mapValue(accounts[_active]);
  }
}
