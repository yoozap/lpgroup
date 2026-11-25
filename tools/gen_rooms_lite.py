#!/usr/bin/env python3
"""The few room facts the page needs from blender/plans/rooms.json, which is
1.9 MB and not served: for every room of every flat (and office), its label
point (pole of inaccessibility), its camera stance (eye at 1.6 m and the
point it looks at, both above the level's floor) and its Georgian name.

    python3 tools/gen_rooms_lite.py        ->  web/rooms_lite.json

Keyed by the flat's own number and the room's `id` - the same `rooms_id`
plan_meta.json carries on each room - so the page joins the two by name and
nothing positional. If plan_meta.json ever carries `label` / `stance` /
`name_ka` itself, the page prefers those and this file is not needed.
"""
import json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = os.path.join(ROOT, 'blender', 'plans', 'rooms.json')
out = os.path.join(ROOT, 'web', 'rooms_lite.json')
R = json.load(open(src))
r2 = lambda v: round(float(v), 2)
lite = {}
for group in ('flats', 'offices'):
    for n, f in (R.get(group) or {}).items():
        rooms = {}
        for r in f.get('rooms', []):
            st = r.get('stance') or {}
            eye, look = st.get('eye'), st.get('look')
            lab = r.get('label')
            rooms[r['id']] = [
                *( [r2(lab[0]), r2(lab[1])] if lab else [None, None] ),
                *( [r2(eye[0]), r2(eye[1]), r2(eye[2])] if eye else [None, None, None] ),
                *( [r2(look[0]), r2(look[1]), r2(look[2])] if look else [None, None, None] ),
                r.get('name_ka') or None,
            ]
        lite[('o' + n) if group == 'offices' and not str(n).startswith('o') else str(n)] = rooms
json.dump({'about': 'per flat number, per rooms.json room id: [label x, label y, eye x, eye y, eye z, look x, look y, look z, name_ka]; z above the level floor. From blender/plans/rooms.json by tools/gen_rooms_lite.py.',
           'rooms': lite}, open(out, 'w'), ensure_ascii=False, separators=(',', ':'))
print(out, os.path.getsize(out), 'bytes,', sum(len(v) for v in lite.values()), 'rooms in', len(lite), 'units')
