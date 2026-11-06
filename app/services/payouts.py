def compute_payouts(participants:list[dict], entry_fee_minor: int)->dict[str,int]:
    """
    Compute the payouts for a list of participants based on their status in the challenge and the entry fee.
    """
    if entry_fee_minor<=0:
        raise ValueError("Entry fee must be greater than zero.")
    if not participants:
        return {}
    payouts={}
    completers=[]
    forfeiters=[]
    for p in participants:
        if p['outcome']=='verified':
            completers.append(p)
            payouts[p['user_id']]=entry_fee_minor
        else:
            forfeiters.append(p)
            payouts[p['user_id']]=0

    bonus_pool=entry_fee_minor*len(forfeiters)//len(completers) if len(completers)>0 else 0
    if len(completers)==0:
        payouts={p['user_id']:entry_fee_minor for p in participants}
        return payouts
    for p in completers:
        payouts[p['user_id']]=payouts[p['user_id']]+bonus_pool
    return payouts