import json

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import f1_score, precision_score, recall_score

from evaluation.url.source_audit import FEATURES, align_reference, check_protocol, metrics, paired_bootstrap, sha, thresholds, training_masks


def frame():
    return pd.DataFrame([
        {'id':'n1','split':'train','labels':0,'tier':'gold','source':'trusted'},
        {'id':'n2','split':'train','labels':0,'tier':'silver','source':'tranco'},
        {'id':'p1','split':'train','labels':1,'tier':'gold','source':'ncsc'},
        {'id':'b1','split':'train','labels':1,'tier':'bronze','source':'community'},
        {'id':'b2','split':'train','labels':1,'tier':'bronze','source':'feed'},
        {'id':'v1','split':'val','labels':1,'tier':'bronze','source':'community'},
        {'id':'t1','split':'test','labels':1,'tier':'gold','source':'ncsc'},
    ])


def test_feature_metadata_join_handles_encoding_and_order_but_rejects_wrong_labels():
    meta=pd.DataFrame({'url':['Example.VN','https://second.vn'],'id':['a','b'],
                       'labels':[1,0],'split':['train','test'],'tier':['gold','silver']})
    ref=pd.DataFrame({'url':['http://second.vn','https://example.vn'],
                     'label':[0,1],'split':['test','train'],'tier':['silver','gold']})
    normalize=lambda url:url.replace('https://','').replace('http://','')
    assert align_reference(meta,ref,normalize).id.tolist()==['b','a']
    wrong=ref.copy();wrong.loc[0,'label']=1
    with pytest.raises(ValueError,match='labels'):align_reference(meta,wrong,normalize)


def test_training_scope_never_uses_validation_test_or_their_class_composition():
    data=frame();original=training_masks(data)
    other=data.copy();other.loc[other.split!='train',['labels','tier','source']]=[0,'silver','different']
    changed=training_masks(other)
    for name,mask in original.items():
        assert np.array_equal(mask,changed[name])
        assert not mask[data.split!='train'].any()
    assert data[original['verified_core']].labels.value_counts().to_dict()==data[original['bronze_matched']].labels.value_counts().to_dict()
    for mask in original.values():assert set(data[mask & data.labels.eq(0)].id)=={'n1','n2'}
    assert set(data[original['bronze_matched'] & data.labels.eq(1)].source)<={'community','feed'}
    assert not {'source','tier','label','id','is_https'} & set(FEATURES)


def test_single_class_source_groups_do_not_advertise_perfect_precision_or_f1():
    positive=metrics([1,1],[.9,.4]);negative=metrics([0,0],[.8,.1])
    assert positive['precision'] is positive['f1'] is positive['false_positive_rate'] is None
    assert positive['recall']==.5
    assert negative['precision'] is negative['f1'] is negative['recall'] is None
    assert negative['false_positive_rate']==.5
    y=[1,0,1,0];s=[.8,.6,.2,.1];m=metrics(y,s);p=np.asarray(s)>=.5
    assert m['precision']==precision_score(y,p)
    assert m['recall']==recall_score(y,p)
    assert m['f1']==f1_score(y,p)


def test_small_core_validation_cannot_meet_high_precision_and_minimum_count():
    r=thresholds([1]*24+[0]*100,[.9]*24+[.1]*100)
    assert r['warning_precision_met'] and r['warning']==.9
    assert r['high'] is None and not r['high_count_precision_possible']
    r=thresholds([1]*40+[0]*100,[.9]*40+[.1]*100)
    assert r['high']==.9 and r['high_count_precision_possible']


def test_registered_source_mismatch_is_rejected_before_any_checkpoint_write(tmp_path):
    source=tmp_path/'source.py';source.write_text('original')
    index=tmp_path/'data_index.csv.gz';index.write_bytes(b'locked data')
    cfg={'source_hashes':{str(source):sha(source)},'index_sha256':sha(index)}
    path=tmp_path/'execution.json';path.write_text(json.dumps(cfg));before=path.read_bytes()
    source.write_text('different')
    with pytest.raises(ValueError,match='Registered source/input changed'):check_protocol(tmp_path)
    assert path.read_bytes()==before
    assert not (tmp_path/'predictions').exists()


def test_domain_bootstrap_keeps_paired_rows_and_excludes_undefined_samples():
    index=pd.DataFrame({'id':['a1','a2','b1','b2'],'split':['test']*4,'domain_group':['a','a','b','b'],'labels':[1,1,0,0]})
    rows=index[['id','split','labels']].copy();rows['score']=[.8,.6,.3,.2]
    predictions={name+'--LogReg--s0':({}, {}, rows.copy()) for name in ['verified_core','all']}
    cfg={'stochastic_seeds':[0],'bootstrap':{'seed':5,'draws':100}}
    ci=paired_bootstrap(index,predictions,'LogReg','verified_core','all',np.ones(4,dtype=bool),cfg)
    assert ci['domains']==2 and 0<ci['valid_draws']<100
    assert ci['f1_delta_95']==ci['fpr_delta_95']==[0.,0.]
