import json,glob,os
files=sorted(glob.glob('eval/results/eval_run_*.jsonl'))
latest=files[-1]
print('latest', latest)
counts={'stall_clarification':0,'context_loss':0,'overpolite':0,'command_inconsistent':0,'flat_tone':0,'good_human_like':0}
with open(latest,encoding='utf-8') as f:
    for line in f:
        obj=json.loads(line)
        resp=obj.get('response','') or ''
        r=resp.lower()
        stall = ('clarify' in r) or r.strip().startswith('can you please clarify') or 'please clarify' in r
        context = ("i'm sorry" in r and 'not sure' in r) or ('i need more information' in r) or ("i'm sorry, i'm not sure" in r)
        over = ('please' in r) and stall
        if stall: counts['stall_clarification']+=1
        if context: counts['context_loss']+=1
        if over: counts['overpolite']+=1
        prompt=obj.get('prompt','')
        lp=prompt.lower().strip()
        is_cmd = lp in ('open chrome.','open chrome','open photoshop','stop.','stop','play music.','play music','next.','next')
        if is_cmd and not (r.startswith('opening') or r.startswith('ok') or r.startswith('done')):
            counts['command_inconsistent']+=1
        if not stall and not context and not over:
            if len(resp.split())<12:
                counts['flat_tone']+=1
            else:
                counts['good_human_like']+=1
print('counts for', os.path.basename(latest))
for k,v in counts.items():
    print(f'{k}: {v}')
