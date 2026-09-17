import sys
from collections import deque


def main() -> None:
    input_data = sys.stdin.read().split()
    if not input_data:
        return
    n = int(input_data[0])
    m = int(input_data[1])

    edges = []
    adj = [[] for _ in range(n)]
    rev_adj = [[] for _ in range(n)]

    idx = 2
    for _ in range(m):
        u = int(input_data[idx]) - 1
        v = int(input_data[idx + 1]) - 1
        w = int(input_data[idx + 2])
        idx += 3
        edges.append((u, v, w))
        adj[u].append(v)
        rev_adj[v].append(u)

    # Reachable from 1
    reachable_from_1 = [False] * n
    q = deque([0])
    reachable_from_1[0] = True
    while q:
        u = q.popleft()
        for v in adj[u]:
            if not reachable_from_1[v]:
                reachable_from_1[v] = True
                q.append(v)

    # Can reach N
    can_reach_n = [False] * n
    q = deque([n - 1])
    can_reach_n[n - 1] = True
    while q:
        v = q.popleft()
        for u in rev_adj[v]:
            if not can_reach_n[u]:
                can_reach_n[u] = True
                q.append(u)

    valid_edges = [
        (u, v, w)
        for u, v, w in edges
        if reachable_from_1[u] and can_reach_n[u] and reachable_from_1[v] and can_reach_n[v]
    ]

    inf_neg = -(10**30)
    dist = [inf_neg] * n
    dist[0] = 0

    for _ in range(n - 1):
        for u, v, w in valid_edges:
            if dist[u] != inf_neg and dist[u] + w > dist[v]:
                dist[v] = dist[u] + w

    for u, v, w in valid_edges:
        if dist[u] != inf_neg and dist[u] + w > dist[v]:
            print("inf")
            return

    print(dist[n - 1])


if __name__ == "__main__":
    main()
