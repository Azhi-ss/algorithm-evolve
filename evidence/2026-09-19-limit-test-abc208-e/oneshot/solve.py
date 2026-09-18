import sys
from collections import defaultdict

def solve():
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    N_str = input_data[0]
    K = int(input_data[1])
    
    digits = [int(c) for c in N_str]
    L = len(digits)
    
    # dp represents counts of (started, prod) for numbers strictly less than the prefix
    # started: bool (0 or 1)
    # prod: integer product, clamped at K + 1 for any product > K
    # Since prod > K can only become 0 (on digit 0) or stay > K (on digits 1-9),
    # clamping at K + 1 is exact.
    
    # dp only stores states for numbers that are already strictly less than prefix of N
    dp = defaultdict(int)
    
    # Tight prefix state:
    tight_started = False
    tight_prod = 1
    
    OVERFLOW = K + 1
    
    for i, d in enumerate(digits):
        next_dp = defaultdict(int)
        
        # 1. Transitions from dp (already less than prefix)
        # Case A: not started yet
        unstarted_count = dp.get((0, 1), 0)
        if i > 0 or unstarted_count > 0:
            # If we don't start, we place a leading 0
            next_dp[(0, 1)] += unstarted_count
            # If we start, we place digit d_cur in 1..9
            for d_cur in range(1, 10):
                p = min(d_cur, OVERFLOW)
                next_dp[(1, p)] += unstarted_count
        
        # Case B: already started
        # Precompute sum of all started counts to handle digit 0 in O(1)
        # Precompute count of OVERFLOW to handle digits 1..9 in O(1)
        total_started = 0
        overflow_count = dp.get((1, OVERFLOW), 0)
        
        for (started, prod), cnt in dp.items():
            if not started:
                continue
            total_started += cnt
            if prod == OVERFLOW:
                continue
            
            # Digit 1: product remains prod
            next_dp[(1, prod)] += cnt
            
            # Digits 2..9
            for d_cur in range(2, 10):
                p = min(prod * d_cur, OVERFLOW)
                next_dp[(1, p)] += cnt
        
        # Digit 0 resets any started product to 0
        if total_started > 0:
            next_dp[(1, 0)] += total_started
            
        # OVERFLOW multiplied by 1..9 stays OVERFLOW
        if overflow_count > 0:
            next_dp[(1, OVERFLOW)] += overflow_count * 9
        
        # 2. Transitions from the tight prefix
        for d_cur in range(d):
            if not tight_started:
                if d_cur == 0:
                    # Still leading zero
                    next_dp[(0, 1)] += 1
                else:
                    p = min(d_cur, OVERFLOW)
                    next_dp[(1, p)] += 1
            else:
                if d_cur == 0:
                    p = 0
                else:
                    p = min(tight_prod * d_cur, OVERFLOW)
                next_dp[(1, p)] += 1
        
        # Advance tight prefix
        if not tight_started:
            if d == 0:
                tight_started = False
                tight_prod = 1
            else:
                tight_started = True
                tight_prod = min(d, OVERFLOW)
        else:
            if d == 0:
                tight_prod = 0
            else:
                tight_prod = min(tight_prod * d, OVERFLOW)
        
        dp = next_dp
    
    # Count valid positive integers <= N
    ans = 0
    for (started, prod), cnt in dp.items():
        if started and prod <= K:
            ans += cnt
            
    # Don't forget to check if N itself satisfies the condition
    if tight_started and tight_prod <= K:
        ans += 1
        
    print(ans)

if __name__ == '__main__':
    solve()
