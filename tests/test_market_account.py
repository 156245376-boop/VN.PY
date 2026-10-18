from types import SimpleNamespace

from qf.market_account import account_snapshot, public_account


def test_local_account_snapshot_contains_only_business_fields():
    api = SimpleNamespace(
        get_account=lambda: {'balance': 1000000, 'available': float('nan'),
                             'token': 'private-token', 'account_id': 'private-account'},
        get_position=lambda: {'SHFE.rb2701': {'exchange_id': 'SHFE', 'instrument_id': 'rb2701',
                                              'pos_long': 2, 'pos_short': 0, 'token': 'private'}},
        get_order=lambda: {}, get_trade=lambda: {})
    snapshot = account_snapshot(api, connected=True, observed_at='2026-10-18 12:00:00')
    assert snapshot['kind'] == 'local_sim'
    assert snapshot['summary']['balance'] == 1000000
    assert snapshot['summary']['available'] is None
    assert snapshot['positions'][0]['symbol'] == 'SHFE.rb2701'
    assert 'private' not in str(snapshot)
    assert snapshot['orders'] == snapshot['trades'] == []
    assert public_account(snapshot | {'password': 'private-pass'}) == snapshot


def test_malformed_account_fields_are_not_trusted():
    result = public_account({'kind': 'local_sim', 'summary': [], 'truncated': None})
    assert result['summary']['balance'] is None
    assert result['orders'] == []
