"""50 original practice tasks, aligned to the publicly documented CKAD domains."""
from bank_helpers import DOMAINS
import bank_design, bank_deployment, bank_observability, bank_configuration, bank_networking, bank_focused

BANK_VERSION='2026-10-02'
CORE_IDS=('d01','d02','d03','d06','p01','p06','p09','p10','o01','o03','o06','c01','c04','c06','c09','c11','n01','n08','n09','n10')
SETS={
    'core': {'name':'Set 1 · Core 20','questions':20,'mock_tasks':20,'exam_minutes':120,'weighted':True},
    'focused': {'name':'Set 2 · Focused 16','questions':16,'mock_tasks':16,'exam_minutes':120,'weighted':False},
}

def load_bank():
    tasks=[]
    for module in (bank_design,bank_deployment,bank_observability,bank_configuration,bank_networking):
        tasks.extend(module.tasks())
    for value in tasks: value['set_id']='core'
    tasks.extend(bank_focused.tasks())
    return {t['id']:t for t in tasks}

BANK=load_bank()

def set_tasks(set_id='core'):
    if not isinstance(set_id,str) or set_id not in SETS: raise ValueError('Unknown question set.')
    return [task for task in BANK.values() if task['set_id']==set_id and (set_id!='core' or task['id'] in CORE_IDS)]

ACTIVE_BANK={task['id']:task for set_id in SETS for task in set_tasks(set_id)}
assert len(BANK)==66, 'The task registry must retain legacy task IDs'
assert len(ACTIVE_BANK)==36, 'The two visible sets must contain 36 tasks'
assert all(len(set_tasks(key))==value['questions'] for key,value in SETS.items())
assert sum(d['weight'] for d in DOMAINS.values())==100
