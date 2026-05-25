import 'package:flutter/material.dart';

import 'monitor_utils.dart';

class ConnectionBar extends StatelessWidget {
  const ConnectionBar({
    required this.onRefresh,
    required this.loading,
    super.key,
  });

  final VoidCallback onRefresh;
  final bool loading;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: DecoratedBox(
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFF263544)),
              borderRadius: BorderRadius.circular(8),
              color: const Color(0xFF13202A),
            ),
            child: const Padding(
              padding: EdgeInsets.symmetric(horizontal: 12, vertical: 11),
              child: Text('PC 모니터에 자동 연결 중'),
            ),
          ),
        ),
        const SizedBox(width: 8),
        IconButton.filledTonal(
          onPressed: loading ? null : onRefresh,
          icon: loading
              ? const SizedBox.square(
                  dimension: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.refresh),
        ),
      ],
    );
  }
}

class StatusChip extends StatelessWidget {
  const StatusChip({required this.connected, super.key});

  final bool connected;

  @override
  Widget build(BuildContext context) {
    return Chip(
      label: Text(connected ? '연결됨' : '미연결'),
      side:
          BorderSide(color: connected ? Colors.greenAccent : Colors.redAccent),
      backgroundColor: connected
          ? Colors.greenAccent.withValues(alpha: 0.12)
          : Colors.redAccent.withValues(alpha: 0.12),
    );
  }
}

class SummaryGrid extends StatelessWidget {
  const SummaryGrid({required this.active, required this.summary, super.key});

  final String active;
  final Map<String, dynamic> summary;

  @override
  Widget build(BuildContext context) {
    final items = <(String, String)>[
      ('달러 현금', textValue(summary['cashUsd'])),
      ('달러 평가금액', textValue(summary['equityUsd'])),
      if (active == 'real') ('원화 예수금', textValue(summary['cashKrw'])),
      ('투자 금액', textValue(summary['investedUsd'])),
      ('보유 종목', textValue(summary['openPositions'])),
      ('수익률', textValue(summary['dailyProfitRate'])),
    ];

    return GridView.builder(
      itemCount: items.length,
      shrinkWrap: true,
      physics: const NeverScrollableScrollPhysics(),
      gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
        crossAxisCount: 2,
        childAspectRatio: 2.25,
        crossAxisSpacing: 10,
        mainAxisSpacing: 10,
      ),
      itemBuilder: (context, index) {
        final item = items[index];
        return MetricCard(label: item.$1, value: item.$2);
      },
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({required this.label, required this.value, super.key});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return DecoratedBox(
      decoration: BoxDecoration(
        border: Border.all(color: const Color(0xFF263544)),
        borderRadius: BorderRadius.circular(8),
        color: const Color(0xFF13202A),
      ),
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Text(label, style: Theme.of(context).textTheme.labelMedium),
            const SizedBox(height: 7),
            Text(value, style: Theme.of(context).textTheme.titleMedium),
          ],
        ),
      ),
    );
  }
}

class Section extends StatelessWidget {
  const Section({required this.title, required this.child, super.key});

  final String title;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Card(
      elevation: 0,
      color: const Color(0xFF101922),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 10),
            child,
          ],
        ),
      ),
    );
  }
}

class HoldingsList extends StatelessWidget {
  const HoldingsList({required this.rows, super.key});

  final List<dynamic> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const EmptyText('보유 종목이 없습니다');
    return Column(
      children: rows.map((row) {
        final item = mapValue(row);
        return ListTile(
          contentPadding: EdgeInsets.zero,
          title:
              Text('${textValue(item['name'])} (${textValue(item['ticker'])})'),
          subtitle: Text(
            '평단 ${textValue(item['averagePrice'])} / 총가격 ${textValue(item['totalPrice'])}',
          ),
          trailing: Text('${textValue(item['quantity'])}주'),
        );
      }).toList(),
    );
  }
}

class TargetsList extends StatelessWidget {
  const TargetsList({required this.rows, super.key});

  final List<dynamic> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const EmptyText('수집된 종목이 없습니다');
    return Column(
      children: rows.map((row) {
        final cells = listValue(row).map(textValue).toList();
        return ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(cells.isEmpty ? '-' : cells.first),
          subtitle: Text(cells.skip(1).join(' / ')),
        );
      }).toList(),
    );
  }
}

class LogsList extends StatelessWidget {
  const LogsList({required this.rows, super.key});

  final List<dynamic> rows;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) return const EmptyText('로그가 없습니다');
    return Column(
      children: rows.map((row) {
        final cells = listValue(row).map(textValue).toList();
        return ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(cells.length > 2 ? cells[2] : cells.join(' ')),
          subtitle: Text(cells.take(2).join(' / ')),
        );
      }).toList(),
    );
  }
}

class ErrorBox extends StatelessWidget {
  const ErrorBox({required this.message, super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(top: 12),
      child: DecoratedBox(
        decoration: BoxDecoration(
          border: Border.all(color: Colors.redAccent),
          borderRadius: BorderRadius.circular(8),
          color: Colors.redAccent.withValues(alpha: 0.1),
        ),
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Text(message),
        ),
      ),
    );
  }
}

class EmptyText extends StatelessWidget {
  const EmptyText(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(text, style: Theme.of(context).textTheme.bodyMedium);
  }
}
