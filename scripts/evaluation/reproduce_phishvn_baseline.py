"""Train LR/RF in the separately pinned PhishVN reference environment; no app imports."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform
import time
import warnings
import zipfile

import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score, roc_curve


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scores_metrics(y, score):
    pred = score >= .5
    fp, tn = int(((y == 0) & pred).sum()), int(((y == 0) & ~pred).sum())
    fpr, tpr, _ = roc_curve(y, score)
    return {"f1": float(f1_score(y, pred)), "precision": float(precision_score(y, pred)),
            "recall": float(recall_score(y, pred)), "false_positive_rate": fp / (fp + tn),
            "roc_auc": float(roc_auc_score(y, score)), "average_precision": float(average_precision_score(y, score)),
            "fpr_at_recall90": float(fpr[np.flatnonzero(tpr >= .9)[0]])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out
    cfg=json.loads((out/'execution.json').read_text())
    for path,digest in cfg['source_hashes'].items():
        if sha(path)!=digest:raise ValueError('Registered input/source changed: '+path)
    versions={'numpy':np.__version__,'pandas':pd.__version__,'sklearn':sklearn.__version__}
    if versions!={'numpy':'1.26.4','pandas':'2.2.2','sklearn':'1.4.2'}:
        raise ValueError('Use the separately pinned reference environment: '+str(versions))
    root=Path(__file__).resolve().parents[2]
    with zipfile.ZipFile(root/'data/raw/PhishVN_v3.1.0_open.zip') as z:
        df=pd.read_csv(io.BytesIO(z.read('data/vn_compphish.csv')),low_memory=False)
    index=pd.read_csv(out/'data_index.csv.gz',keep_default_na=False)
    if len(index)!=len(df):raise ValueError('Different input index.')
    core=df[df.tier.isin(['gold','silver'])]
    train,test=core[core.split=='train'],core[core.split=='test']
    ids=index[(index.split=='test')&index.tier.isin(['gold','silver'])].id.to_numpy()
    assert len(train)==13080 and len(test)==len(ids)==4332
    Xtrain=train[cfg['feature_names']].to_numpy(dtype=np.float64)
    Xtest=test[cfg['feature_names']].to_numpy(dtype=np.float64)
    y=test.label.to_numpy(dtype=int)
    destination=out/'reference_reproduction';destination.mkdir(exist_ok=True)
    records=[]
    with zipfile.ZipFile(root/'data/raw/PhishVN_v3.0.0_results_bundle.zip') as reference:
        manifest={line.split()[1]:line.split()[0] for line in reference.read('p1a_results_bundle/MANIFEST.txt').decode().splitlines() if line.strip()}
        for family in ['LogReg','RandomForest']:
            for seed in ([0] if family=='LogReg' else range(5)):
                name=f'{family}_seed{seed}'
                marker=destination/(name+'.json')
                if marker.exists():
                    records.append(json.loads(marker.read_text()));continue
                model=LogisticRegression(max_iter=1000,class_weight='balanced') if family=='LogReg' else RandomForestClassifier(n_estimators=300,class_weight='balanced',n_jobs=4,random_state=seed)
                start=time.perf_counter()
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter('always');model.fit(Xtrain,train.label.to_numpy(dtype=int))
                score=model.predict_proba(Xtest)[:,1]
                path='predictions/'+name+'.csv';raw=reference.read('p1a_results_bundle/'+path)
                assert hashlib.sha256(raw).hexdigest()==manifest[path]
                published=pd.read_csv(io.BytesIO(raw),float_precision='round_trip').set_index('id')
                assert set(published.index)==set(ids)
                published=published.loc[ids]
                label=next(k for k in ['y','label','labels','y_true'] if k in published)
                assert np.array_equal(published[label].to_numpy(dtype=int),y)
                expected=published.score.to_numpy()
                predictions=destination/(name+'.csv.gz')
                pd.DataFrame({'id':ids,'labels':y,'score':score}).to_csv(predictions,index=False,float_format='%.17g',compression={'method':'gzip','mtime':0})
                record={'family':family,'seed':seed,'n_train':len(train),'n_test':len(test),
                    'versions':versions,'python':platform.python_version(),'platform':platform.platform(),
                    'fit_seconds':time.perf_counter()-start,'metrics':scores_metrics(y,score),
                    'published_metrics_recomputed':scores_metrics(y,expected),'prediction_sha256':sha(predictions),
                    'max_abs_score_difference':float(np.abs(score-expected).max()),
                    'mean_abs_score_difference':float(np.abs(score-expected).mean()),
                    'decision_disagreements':int(((score>=.5)!=(expected>=.5)).sum()),
                    'warnings':[{'category':type(w.message).__name__,'message':str(w.message)} for w in caught]}
                marker.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
                records.append(record);print(json.dumps({'reference_fit':name,'f1':record['metrics']['f1'],'decision_disagreements':record['decision_disagreements']},ensure_ascii=False),flush=True)
    (destination/'summary.json').write_text(json.dumps(records,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


if __name__=='__main__':main()
