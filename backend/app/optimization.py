def distance(a,b): return abs(a[0]-b[0])+abs(a[1]-b[1])

def length(points): return sum(distance(a,b) for a,b in zip(points,points[1:]))

def optimize(points, start=(0,0), strategy='Batch'):
    # Rectilinear travel follows open aisle coordinates; start/end are packing station.
    unique=list(dict.fromkeys(tuple(p) for p in points))
    original=[tuple(start)]+unique+[(0,0)]
    pending=unique[:]; route=[tuple(start)]
    if strategy=='Zone': pending.sort(key=lambda p:(p[0]//8,p[1]))
    while pending:
        p=min(pending,key=lambda p:distance(route[-1],p))
        route.append(p); pending.remove(p)
    route.append((0,0))
    # 2-opt improves the heuristic without ever reporting invented savings.
    changed=True
    while changed:
        changed=False
        for i in range(1,len(route)-2):
            for j in range(i+1,len(route)-1):
                candidate=route[:i]+route[i:j+1][::-1]+route[j+1:]
                if length(candidate)<length(route):route=candidate;changed=True
    if length(route)>length(original):route=original[:]
    before=length(original)*2;after=length(route)*2
    return {'original':original,'optimized':route,'original_distance':before,'optimized_distance':after,'saved':before-after,'percentage':round((before-after)/before*100,1) if before else 0,'estimated_minutes':round(after/70+len(unique)*0.6,1),'stops':len(unique),'strategy':strategy,'algorithm':'Manhattan nearest-neighbor + 2-opt','meters_per_grid_unit':2}
