"""Explicit synthetic disclosure evidence, never derived by the application."""
def portfolio(tags=('测试行业',), weights=(8, 2), report_date='2026-09-30'):
    return {'status': 'ok', 'report_date': report_date, 'source_id': 'holdings:synthetic',
            'source_url': 'https://example.test/disclosure', 'rows': [
                {'code': str(600001 + i), 'name': '合成证券' + str(i), 'instrument_type': 'stock',
                 'weight_pct': weight, 'tag_status': 'ok', 'tags': list(tags)}
                for i, weight in enumerate(weights)]}
