import sys
from functools import lru_cache


def main() -> None:
    sys.setrecursionlimit(100000)
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n_s, k_s = input_data[0], input_data[1]
    digits = list(map(int, n_s))
    k = int(k_s)
    n = len(digits)

    @lru_cache(None)
    def dp(i: int, tight: bool, lead: bool, prod: int) -> int:
        if i == n:
            return 0 if lead else (1 if prod <= k else 0)
        lim = digits[i] if tight else 9
        ans = 0
        for d in range(lim + 1):
            nt = tight and (d == lim)
            if lead and d == 0:
                ans += dp(i + 1, nt, True, 1)
            else:
                np = prod * d
                if np > k:
                    np = k + 1
                ans += dp(i + 1, nt, False, np)
        return ans

    print(dp(0, True, True, 1))


if __name__ == "__main__":
    main()
