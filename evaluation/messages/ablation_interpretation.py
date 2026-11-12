"""Separate reduced false alarms from lost decisions when interpreting ablations."""
import argparse
from collections import Counter
from pathlib import Path

from evaluation.common.metrics import prediction
from evaluation.data.sms import read_jsonl, sha, write_json
from evaluation.messages import fresh_ablation


def transitions(rows, arm):
    """Count mutually exclusive outcomes on reference-negative SMS only."""
    lookup = {(r['id'], r['arm']): r for r in rows if r['dataset'] == 'sms' and r['label'] == 0}
    baseline = [r for r in lookup.values() if r['arm'] == 'llm_only']
    counts = Counter(reference_negatives=len(baseline), alarm_to_low=0, alarm_to_unknown=0,
                     alarm_to_unknown_technical=0, low_to_unknown=0, unknown_to_low=0)
    matrix = Counter()
    def state(row):
        value = prediction(row['level'])
        return 'UNKNOWN' if value is None else 'alarm' if value else 'LOW'
    for left in baseline:
        right = lookup[(left['id'], arm)]
        a, b = state(left), state(right)
        matrix[a + ' -> ' + b] += 1
        name = {( 'alarm', 'LOW'): 'alarm_to_low', ('alarm', 'UNKNOWN'): 'alarm_to_unknown',
                ('LOW', 'UNKNOWN'): 'low_to_unknown', ('UNKNOWN', 'LOW'): 'unknown_to_low'}.get((a, b))
        if name: counts[name] += 1
        if a == 'alarm' and b == 'UNKNOWN' and right['status'] != 'ok':
            counts['alarm_to_unknown_technical'] += 1
    return {**counts, 'matrix': dict(matrix)}


def report(out):
    out = Path(out)
    # Recompute from sealed raw results rather than trusting edited metrics/decisions.
    metrics = fresh_ablation.results(out)
    rows = read_jsonl(out / 'decisions.jsonl')
    result = {arm: transitions(rows, arm) for arm in fresh_ablation.ARMS[1:]}
    lines = ['# Diễn giải F1 cùng Accuracy và coverage', '',
        'Reference AI sơ bộ, không phải gold. UNKNOWN dự đoán/lỗi tính là sai khi tính Accuracy toàn tập nhị phân. '
        'F1 dương không phạt UNKNOWN trên âm như một false positive; vì vậy F1 tăng do mất quyết định không chứng minh phát hiện tốt hơn.', '',
        '| Cấu hình | Đúng / n SMS nhị phân | Accuracy | F1 | Coverage | UNKNOWN trên âm |',
        '|---|---:|---:|---:|---:|---:|']
    for arm in fresh_ablation.ARMS:
        m = metrics['groups']['sms'][arm]
        pct = lambda v: 'N/A' if v is None else f'{v:.2%}'
        lines.append(f"| {arm} | {m['tp'] + m['tn']}/{m['n']} | {pct(m['accuracy'])} | {pct(m['f1'])} | {pct(m['coverage'])} | {m['unknown_negative']} |")
    lines += ['', 'So với LLM, chỉ xét các SMS tham chiếu âm:', '',
        '| Cấu hình | Báo nhầm → LOW đúng | Báo nhầm → UNKNOWN | Trong đó lỗi kỹ thuật | LOW đúng → UNKNOWN | UNKNOWN → LOW đúng |',
        '|---|---:|---:|---:|---:|---:|']
    for arm, counts in result.items():
        lines.append('| ' + arm + ' | ' + ' | '.join(str(counts[k]) for k in
            ('alarm_to_low', 'alarm_to_unknown', 'alarm_to_unknown_technical', 'low_to_unknown', 'unknown_to_low')) + ' |')
    lines += ['', 'Các chuyển alarm → UNKNOWN vẫn là chưa xử lý đúng mẫu âm, dù không còn tính là FP trong F1 dương. '
        'Không chọn cấu hình chỉ vì F1 cao hoặc FPR thấp hơn; đọc cùng Accuracy, coverage, lỗi và Recall.', '',
        'Kiểm tra số dương và âm trong nhóm thực sự nhận URL/RAG trước khi suy ra lợi ích thành phần. '
        'Stress tự soạn và injection được báo riêng trong report.md; không gộp vào SMS hoặc coi các biến thể là độc lập.']
    write_json(out / 'interpretation.json', result)
    (out / 'interpretation.md').write_text('\n'.join(lines) + '\n')
    with (out / 'report.md').open('a') as stream:
        stream.write('\n' + '\n'.join(lines[2:]) + '\n')
    write_json(out / 'interpretation_manifest.json', {'analysis_source': str(Path(__file__).resolve()),
        'analysis_sha256': sha(__file__), 'sealed_results_sha256': sha(out / 'result_hashes.json'),
        'metrics_sha256': sha(out / 'metrics.json'), 'decisions_sha256': sha(out / 'decisions.jsonl'),
        'inference_calls': 0, 'references_changed': False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    print(report(args.out))


if __name__ == '__main__':
    main()
