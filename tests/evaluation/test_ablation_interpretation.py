from evaluation.messages.ablation_interpretation import transitions


def test_lost_false_alarms_are_distinct_from_correct_negative_decisions():
    rows = []
    def pair(key, left, right, label=0, status='ok'):
        for arm, level, state in [('llm_only', left, 'ok'), ('llm_url', right, status)]:
            rows.append({'id': key, 'dataset': 'sms', 'label': label, 'arm': arm, 'level': level, 'status': state})
    pair('lost_alarm', 'HIGH', 'UNKNOWN', status='error')
    pair('fixed_alarm', 'WARNING', 'LOW')
    pair('lost_correct', 'LOW', 'UNKNOWN', status='error')
    pair('recovered', 'UNKNOWN', 'LOW')
    pair('not_a_negative', 'HIGH', 'UNKNOWN', label=1, status='error')
    pair('not_labeled', 'HIGH', 'UNKNOWN', label=None, status='error')
    result = transitions(rows, 'llm_url')
    assert result['reference_negatives'] == 4
    assert result['alarm_to_low'] == 1
    assert result['alarm_to_unknown'] == result['alarm_to_unknown_technical'] == 1
    assert result['low_to_unknown'] == result['unknown_to_low'] == 1
    assert sum(result['matrix'].values()) == 4
