#!/usr/bin/env python3
"""The sales inventory, generated from the architect's drawing.

    python3 tools/gen_flats.py            # plan.json (+ rooms.json) -> web/flats.js + web/flatplans.json
    python3 tools/gen_flats.py --check    # ...and print the counts it checks itself against

Inputs
  blender/plans/plan.json   tools/plan_extract.py's reading of plans.pdf (plan metres)
  blender/plans/rooms.json  OPTIONAL, tools/plan_rooms.py: room types per flat. Without it
                            the bedroom count is estimated from the flat's inner area and
                            every record says so (`typeFrom: 'size'`).

Outputs
  web/flats.js        ES module: FLATS (191 real flats), OFFICES (12, +4.8), ISSUES (every
                      place the architect's table and drawing disagree and what was done
                      about it), BUILDING (the counts the page quotes), PLAN_SRC.
                      Prices and availability are NOT here - they are not in the plans.
                      content.js adds them, marked as placeholders.
  web/flatplans.json  per flat, a light drawing of it for the flat's card: outline, rooms,
                      balconies and the entrance, in plan metres, rounded to the centimetre.
                      Fetched by the page only when a flat is opened.

The rule for an area, applied to every flat the same way
  inner    the printed figure (in-plan label first, then the table) that agrees with the
           drawn polygon to 0.15 m2. If neither does, the drawing wins: the polygon,
           rounded to 0.1, and an ISSUES record.
  balcony  the printed balcony figure. Where it disagrees with the drawn balcony fills the
           printed figure is kept (it is the architect's saleable number) and the drawn
           sum goes into ISSUES. Where the label and the table disagree, the one closer
           to the drawn fills is taken.
  total    inner + balcony. Where that is not the printed total, ISSUES says so.
A table row with nothing drawn is not a flat: it is not emitted, and ISSUES says so.
"""
import json, math, os, re, sys, hashlib
from shapely.geometry import Polygon

ROOT = os.path.dirname( os.path.dirname( os.path.abspath( __file__ ) ) )
PLAN = os.path.join( ROOT, 'blender', 'plans', 'plan.json' )
ROOMS = os.path.join( ROOT, 'blender', 'plans', 'rooms.json' )
OUT_JS = os.path.join( ROOT, 'web', 'flats.js' )
OUT_PLANS = os.path.join( ROOT, 'web', 'flatplans.json' )

TOL = 0.15                      # m2: what "agrees with the drawing" means
JOINT_X = 44.4                  # CONTRACT.md: block A is x < 44.4, block B the rest (wing included)

# bedrooms from inner area, used only while rooms.json is missing. Read off the
# drawing's furniture on floor 2 (p5): the 22-27 m2 units are studios, the
# 48-59 m2 ones have one bed, 69-97 m2 two, 110 m2 and over three.
SIZE_BEDROOMS = [ ( 35.0, 0 ), ( 64.0, 1 ), ( 100.0, 2 ), ( 1e9, 3 ) ]
TYPE_KEY = { 0: 'studio', 1: 'one', 2: 'two', 3: 'three', 4: 'four' }

# the compass. North is not drawn on any sheet; the renders put the main street
# (the shopfronts, the wing's end) to the south, which is plan +y. So: -y north,
# +y south, -x west, +x east. One constant to turn if the site plan says otherwise.
SIDE = { '-y': 'N', '+y': 'S', '-x': 'W', '+x': 'E' }


def r1( v ):
	return None if v is None else round( v + 1e-9, 1 )


def num_key( n ):
	"""'47-a' -> 47.5, '47' -> 47: sorts the split right after its parent."""
	m = re.match( r'^(\d+)(-a)?$', n )
	return int( m.group( 1 ) ) + ( 0.5 if m.group( 2 ) else 0 )


def centroid( pts ):
	a = cx = cy = 0.0
	for i in range( len( pts ) ):
		x0, y0 = pts[ i ]; x1, y1 = pts[ ( i + 1 ) % len( pts ) ]
		c = x0 * y1 - x1 * y0
		a += c; cx += ( x0 + x1 ) * c; cy += ( y0 + y1 ) * c
	if abs( a ) < 1e-9:
		return [ sum( p[ 0 ] for p in pts ) / len( pts ), sum( p[ 1 ] for p in pts ) / len( pts ) ]
	return [ cx / ( 3 * a ), cy / ( 3 * a ) ]


def sides_of( f ):
	"""Which way the flat looks. A window in an outside wall faces away from the flat; a
	balcony door faces its balcony, whose side of the flat is where the balcony stands -
	the little windows in a loggia's side walls look along the facade, not out of it."""
	o = f[ 'polygon' ][ 'outline' ]
	c = centroid( o )
	w_ = max( p[ 0 ] for p in o ) - min( p[ 0 ] for p in o ) or 1
	h_ = max( p[ 1 ] for p in o ) - min( p[ 1 ] for p in o ) or 1
	bal = {}
	for i, b in enumerate( f.get( 'balconies' ) or [] ):
		bal[ i ] = centroid( b[ 'polygon' ][ 'outline' ] )
	got = set()
	for w in f.get( 'windows' ) or []:
		x, y = w[ 'centre' ]
		if w[ 'kind' ] != 'window':
			pts = [ centroid( b[ 'polygon' ][ 'outline' ] ) for b in f.get( 'balconies' ) or [] ]
			if pts:                                      # the balcony nearest this door
				x, y = min( pts, key=lambda p: ( p[ 0 ] - w[ 'centre' ][ 0 ] ) ** 2 + ( p[ 1 ] - w[ 'centre' ][ 1 ] ) ** 2 )
			dx, dy = ( x - c[ 0 ] ) / w_, ( y - c[ 1 ] ) / h_
			if abs( dy ) >= abs( dx ):
				got.add( SIDE[ '+y' if dy > 0 else '-y' ] )
			else:
				got.add( SIDE[ '+x' if dx > 0 else '-x' ] )
			continue
		if w[ 'axis' ] == 'x':           # wall runs along x, so it faces +-y
			got.add( SIDE[ '+y' if y > c[ 1 ] else '-y' ] )
		else:
			got.add( SIDE[ '+x' if x > c[ 0 ] else '-x' ] )
	return ''.join( s for s in 'NSEW' if s in got )


WORD = { 'N': 'north', 'E': 'east', 'S': 'south', 'W': 'west' }


def aspect_en( s ):
	w = [ WORD[ c ] for c in s ]
	if not w:
		return ''
	if len( w ) == 1:
		t = w[ 0 ]
	elif len( w ) == 2:
		t = w[ 0 ] + ' and ' + w[ 1 ]
	else:
		t = ', '.join( w[ :-1 ] ) + ' and ' + w[ -1 ]
	return t[ 0 ].upper() + t[ 1: ]


def ident( f ):
	return f[ 'number' ] if f.get( 'floor' ) else 'office ' + f[ 'number' ]


def pick_inner( f, issues ):
	poly = f[ 'area_polygon' ]
	lab = f.get( 'label' ) or {}
	tab = f.get( 'table' ) or {}
	for src, v in ( ( 'label', lab.get( 'inner' ) ), ( 'table', tab.get( 'inner' ) ) ):
		if v is not None and abs( v - poly ) <= TOL:
			other = tab.get( 'inner' ) if src == 'label' else lab.get( 'inner' )
			if other is not None and abs( other - v ) > TOL:
				issues.append( dict( n=ident( f ), kind='%s_inner_disagrees' % ( 'table' if src == 'label' else 'label' ),
					drawn=round( poly, 2 ), label=lab.get( 'inner' ), table=tab.get( 'inner' ), used=v,
					note='The %s prints %s m2 inner; the drawn flat is %.1f, as the %s says, so %s is used.'
						% ( 'table' if src == 'label' else 'in-plan label', other, poly, 'in-plan label' if src == 'label' else 'table', v ) ) )
			return v, src
	issues.append( dict( n=ident( f ), kind='inner_from_drawing',
		drawn=round( poly, 2 ), label=lab.get( 'inner' ), table=tab.get( 'inner' ),
		used=r1( poly ),
		note='Neither printed inner area matches the drawn flat; the drawing is used.' ) )
	return r1( poly ), 'drawing'


def pick_balcony( f, issues ):
	drawn = f.get( 'balcony_area_polygons' ) or 0.0
	lab = ( f.get( 'label' ) or {} ).get( 'balcony' )
	tab = ( f.get( 'table' ) or {} ).get( 'balcony' )
	cands = [ ( s, v ) for s, v in ( ( 'label', lab ), ( 'table', tab ) ) if v is not None ]
	if not cands:
		issues.append( dict( n=ident( f ), kind='balcony_from_drawing', drawn=round( drawn, 2 ),
			used=r1( drawn ), note='No balcony area is printed; the drawn balcony fills are used.' ) )
		return r1( drawn ), 'drawing'
	src, v = min( cands, key=lambda c: abs( c[ 1 ] - drawn ) )
	if lab is not None and tab is not None and abs( lab - tab ) > TOL:
		issues.append( dict( n=ident( f ), kind='balcony_label_vs_table', drawn=round( drawn, 2 ), label=lab, table=tab, used=v,
			note='Label and table print different balcony areas (%s vs %s); the one nearer the drawn fills (%.1f) is used.' % ( lab, tab, drawn ) ) )
	if abs( v - drawn ) > TOL:
		issues.append( dict( n=ident( f ), kind='balcony_printed_vs_drawn',
			drawn=round( drawn, 2 ), label=lab, table=tab, used=v,
			note='The printed balcony area is kept; the balcony fills drawn against the flat add up to %.1f m2.' % drawn ) )
	return v, src


def simplify( pts, nd=2 ):
	out = []
	for x, y in pts:
		p = [ round( x, nd ), round( y, nd ) ]
		if not out or p != out[ -1 ]:
			out.append( p )
	# drop collinear points: a light drawing, not a survey
	keep = []
	n = len( out )
	for i in range( n ):
		a, b, c = out[ i - 1 ], out[ i ], out[ ( i + 1 ) % n ]
		cross = ( b[ 0 ] - a[ 0 ] ) * ( c[ 1 ] - b[ 1 ] ) - ( b[ 1 ] - a[ 1 ] ) * ( c[ 0 ] - b[ 0 ] )
		if abs( cross ) > 1e-4:
			keep.append( b )
	return keep if len( keep ) >= 3 else out


def load_rooms():
	"""rooms.json, whatever shape it settles into: {flats:{n:{...}}}, {n:{...}} or [{n|number,...}]."""
	if not os.path.exists( ROOMS ):
		return None
	try:
		d = json.load( open( ROOMS ) )
	except Exception as e:                                  # half-written by its own tool
		print( 'rooms.json unreadable (%s), falling back to size' % e, file=sys.stderr )
		return None
	if isinstance( d, dict ) and isinstance( d.get( 'flats' ), ( dict, list ) ):
		d = d[ 'flats' ]
	out = {}
	if isinstance( d, list ):
		for r in d:
			k = str( r.get( 'n', r.get( 'number', '' ) ) )
			if k:
				out[ k ] = r
	elif isinstance( d, dict ):
		out = { str( k ): v for k, v in d.items() if isinstance( v, dict ) }
	return out or None


def bedrooms_from_rooms( r ):
	"""Bedrooms from rooms.json, cross-checked against the beds the plan draws.

	rooms.json names each room, but on some sheets a walled bedroom comes out as
	a 19 m2 "bathroom" (flats 64, 85, 148 against 1, 22, 43 - the same layout),
	so its own `bedrooms` is not taken on trust: the count is the larger of the
	rooms named bedroom and the double beds drawn, and a flat with no separate
	living room is a studio whatever its one room is called (108, 47-a).
	Returns (bedrooms, what rooms.json itself said)."""
	if r is None:
		return None, None
	said = r.get( 'bedrooms' ) if isinstance( r.get( 'bedrooms' ), int ) else None
	rooms = r.get( 'rooms' )
	if not isinstance( rooms, list ) or not rooms:
		return said, said
	kind = lambda x: str( x.get( 'kind', x.get( 'type', '' ) ) if isinstance( x, dict ) else x ).lower()
	named = sum( 1 for x in rooms if kind( x ) == 'bedroom' )
	beds = sum( 1 for x in r.get( 'furniture' ) or [] if str( x.get( 'kind', '' ) ).startswith( 'bed' ) )
	n = max( named, beds )
	if not any( kind( x ) in ( 'living', 'living_kitchen', 'living_room' ) for x in rooms ):
		n = max( 0, n - 1 )                         # its one room is where you live AND sleep
	return n, said


def main():
	check = '--check' in sys.argv
	P = json.load( open( PLAN ) )
	R = load_rooms()
	issues = []

	# ------------------------------------------------ global decisions, said once
	issues.append( dict( n=None, kind='compass',
		note='North is not marked on any sheet. Aspects assume the main street (plan +y, the shopfronts) is south.' ) )
	issues.append( dict( n=None, kind='blocks',
		note='Block A = west of the expansion joint (x < 44.4 m), block B = east of it including the wing (CONTRACT.md).' ) )

	# the anomalies the extractor recorded that decide whether a flat exists at all
	for a in P[ 'anomalies' ]:
		if a[ 'kind' ] == 'table_row_not_drawn':
			t = a.get( 'table' ) or {}
			issues.append( dict( n=a[ 'unit' ], kind='not_drawn', page=a[ 'page' ], table=t,
				note='Listed in the area table%s but no flat is drawn; not listed for sale.'
					% ( ' (%s / %s / %s)' % ( t.get( 'inner' ), t.get( 'balcony' ), t.get( 'total' ) ) if t.get( 'inner' ) else ' with empty cells' ) ) )
		elif a[ 'kind' ] == 'label_fixed':
			issues.append( dict( n=a[ 'used' ], kind='label_fixed', page=a[ 'page' ],
				note='Printed "%s" on the sheet, which has no row %s; it stands where %s does and is numbered %s.'
					% ( a[ 'drawn' ], a[ 'drawn' ], a[ 'used' ], a[ 'used' ] ) ) )
		elif a[ 'kind' ] == 'no_entrance_door_found':
			issues.append( dict( n=a[ 'unit' ], kind='no_entrance_drawn', page=a[ 'page' ],
				note='No entrance door is drawn to this flat; its entrance is assumed on the wall it shares with the corridor.' ) )

	flats, plans, missing_rooms = [], {}, []
	for f in P[ 'flats' ]:
		n = f[ 'number' ]
		inner, isrc = pick_inner( f, issues )
		bal, bsrc = pick_balcony( f, issues )
		total = r1( inner + bal )
		pt = []
		for src in ( f.get( 'label' ) or {}, f.get( 'table' ) or {} ):
			if src.get( 'total' ) is not None:
				pt.append( src[ 'total' ] )
		if pt and all( abs( total - v ) > 0.051 for v in pt ):
			issues.append( dict( n=n, kind='total_recomputed', printed=sorted( set( pt ) ), used=total,
				note='The printed total is not inner + balcony; the page shows %.1f + %.1f = %.1f.' % ( inner, bal, total ) ) )
		# the split pairs whose label and table swap inner and total
		lab, tab = f.get( 'label' ) or {}, f.get( 'table' ) or {}
		if lab.get( 'inner' ) is not None and tab.get( 'total' ) is not None and lab.get( 'total' ) is not None \
				and abs( lab[ 'inner' ] - tab[ 'total' ] ) < 0.05 and abs( lab[ 'total' ] - tab[ 'inner' ] ) < 0.05 \
				and abs( lab[ 'inner' ] - lab[ 'total' ] ) > 0.5:
			issues[ : ] = [ i for i in issues if not ( i.get( 'n' ) == n and i[ 'kind' ] in ( 'table_inner_disagrees', 'total_recomputed' ) ) ]
			issues.append( dict( n=n, kind='inner_total_swapped', label=lab, table=tab, used=dict( inner=inner, balcony=bal, total=total ),
				note='Label (%s / %s / %s) and table (%s / %s / %s) swap inner and total. The drawn flat is %.1f m2, so that is the inner area: %.1f + %.1f = %.1f.'
					% ( lab[ 'inner' ], lab[ 'balcony' ], lab[ 'total' ], tab[ 'inner' ], tab[ 'balcony' ], tab[ 'total' ], f[ 'area_polygon' ], inner, bal, total ) ) )

		x0 = min( p[ 0 ] for p in f[ 'polygon' ][ 'outline' ] )
		block = 'A' if x0 < JOINT_X else 'B'
		if block != f[ 'block' ]:
			issues.append( dict( n=n, kind='block_disagrees', plan=f[ 'block' ], used=f[ 'block' ] ) )
			block = f[ 'block' ]

		rr = R.get( n ) if R else None
		beds, said = bedrooms_from_rooms( rr )
		tfrom = 'rooms.json'
		if beds is not None and said is not None and beds != said:
			issues.append( dict( n=n, kind='bedrooms_rooms_json_overridden', rooms_json=said, used=beds,
				note='rooms.json says %d bedroom(s); the plan draws %d bed(s) in %d room(s) named bedroom%s, so %d is used.'
					% ( said, sum( 1 for x in rr.get( 'furniture' ) or [] if str( x.get( 'kind', '' ) ).startswith( 'bed' ) ),
						sum( 1 for x in rr.get( 'rooms' ) or [] if x.get( 'kind' ) == 'bedroom' ),
						'' if any( x.get( 'kind' ) in ( 'living', 'living_kitchen' ) for x in rr.get( 'rooms' ) or [] ) else ' and no living room', beds ) ) )
		if beds is None:
			tfrom = 'size'
			beds = next( b for lim, b in SIZE_BEDROOMS if inner < lim )
			missing_rooms.append( n )
		sides = sides_of( f )
		core = f[ 'core' ]
		if rr:
			# rooms.json looks at the rooms themselves: its aspect wins over the window count here
			ra = ''.join( s for s in 'NSEW' if s in { str( a )[ :1 ].upper() for a in rr.get( 'aspect' ) or [] if a in ( 'north', 'south', 'east', 'west' ) } )
			if ra:
				sides = ra
			# ...and its entrance is the nearest core by WALKING, which is what an entrance is
			if rr.get( 'core' ) in ( 'C1', 'C2', 'C3' ) and rr[ 'core' ] != core:
				issues.append( dict( n=n, kind='core_by_walk', straight=core, used=rr[ 'core' ],
					note='Nearest core in a straight line is %s, by walking %s; the walk is used.' % ( core, rr[ 'core' ] ) ) )
				core = rr[ 'core' ]
		lab_at = ( f.get( 'label' ) or {} ).get( 'at' ) or centroid( f[ 'polygon' ][ 'outline' ] )
		kinds = sorted( set( b[ 'kind' ] for b in f.get( 'balconies' ) or [] ) )
		rec = dict(
			n=n, num=num_key( n ),
			block=block, core=core, part=f[ 'part' ],
			level=f[ 'level' ], floor=f[ 'floor' ], z=f[ 'z' ],
			bedrooms=beds, type=TYPE_KEY[ min( beds, 4 ) ], typeFrom=tfrom,
			rooms=len( f.get( 'rooms' ) or [] ),
			bathrooms=( rr or {} ).get( 'bathrooms' ),
			area=dict( inner=inner, balcony=bal, total=total ),
			src=dict( inner=isrc, balcony=bsrc ),
			outdoor=kinds,                                 # balcony / loggia
			aspect=sides, aspectEn=aspect_en( sides ),
			poly='%s-u%s' % ( f[ 'level' ], n ),
			at=[ round( lab_at[ 0 ], 2 ), round( lab_at[ 1 ], 2 ) ],
			noDoor=not f.get( 'entrance' ),
		)
		flats.append( rec )

		ent = ( f.get( 'entrance' ) or [ None ] )[ 0 ]
		plans[ n ] = dict(
			o=simplify( f[ 'polygon' ][ 'outline' ] ),
			r=[ simplify( r[ 'polygon' ][ 'outline' ] ) for r in f.get( 'rooms' ) or [] ],
			b=[ simplify( b[ 'polygon' ][ 'outline' ] ) for b in f.get( 'balconies' ) or [] ],
			d=[ [ round( v, 2 ) for v in ent[ 'hinge' ] ], [ round( v, 2 ) for v in ent[ 'closed_end' ] ] ] if ent else None,
			w=[ [ [ round( v, 2 ) for v in w[ 'a' ] ], [ round( v, 2 ) for v in w[ 'b' ] ] ] for w in f.get( 'windows' ) or [] ],
		)

	flats.sort( key=lambda r: r[ 'num' ] )
	if missing_rooms:
		issues.insert( 2, dict( n=None, kind='bedrooms_estimated', flats=len( missing_rooms ),
			note='%s: bedroom counts of %d of %d flats are estimated from the inner area '
				'(< 35 m2 studio, < 64 one, < 100 two, else three). Re-run when rooms.json covers them.'
				% ( 'blender/plans/rooms.json has no record for them' if R else 'blender/plans/rooms.json was not there', len( missing_rooms ), len( flats ) ) ) )

	offices = []
	for o in P[ 'offices' ]:
		inner, _ = pick_inner( o, issues )
		bal, _ = pick_balcony( o, issues )
		la = ( o.get( 'label' ) or {} ).get( 'at' ) or centroid( o[ 'polygon' ][ 'outline' ] )
		offices.append( dict( n=o[ 'number' ], level=o[ 'level' ], z=o[ 'z' ], block=o[ 'block' ], core=o[ 'core' ],
			area=dict( inner=inner, balcony=bal, total=r1( inner + bal ) ),
			poly='%s-o%s' % ( o[ 'level' ], o[ 'number' ] ), at=[ round( la[ 0 ], 2 ), round( la[ 1 ], 2 ) ] ) )
	offices.sort( key=lambda r: int( r[ 'n' ] ) )

	L = { l[ 'level' ]: l for l in P[ 'levels' ] }
	building = dict(
		levels=[ dict( id=l[ 'level' ], z=l[ 'z' ], kind=l[ 'kind' ] ) for l in P[ 'levels' ] ],
		residentialFloors=sum( 1 for l in P[ 'levels' ] if l[ 'kind' ] == 'residential' ),
		storeysAboveGround=sum( 1 for l in P[ 'levels' ] if l[ 'kind' ] in ( 'commercial', 'offices', 'residential' ) ),
		flats=len( flats ),
		perFloor={ str( k ): sum( 1 for f in flats if f[ 'floor' ] == k ) for k in range( 1, 10 ) },
		perBlock={ b: sum( 1 for f in flats if f[ 'block' ] == b ) for b in 'AB' },
		perCore={ c: sum( 1 for f in flats if f[ 'core' ] == c ) for c in ( 'C1', 'C2', 'C3' ) },
		offices=len( offices ),
		officeArea=r1( sum( o[ 'area' ][ 'inner' ] for o in offices ) ),
		commercialArea=L[ 'L00' ][ 'floor_area_m2' ],
		terraceArea=r1( sum( Polygon( t[ 'outline' ], t.get( 'holes' ) or [] ).area for t in L[ 'L01' ].get( 'terraces' ) or [] ) ),
		parkingUnderground=len( L[ 'P-1' ][ 'parking_spaces' ] ),
		parkingOutdoor=len( L[ 'L00' ][ 'parking_spaces' ] ),
		residentialArea=dict(
			inner=r1( sum( f[ 'area' ][ 'inner' ] for f in flats ) ),
			balcony=r1( sum( f[ 'area' ][ 'balcony' ] for f in flats ) ),
			total=r1( sum( f[ 'area' ][ 'total' ] for f in flats ) ) ),
		blocks=2, entrances=3,
		roomsSource='rooms.json' if R and not missing_rooms else ( 'partial' if R else 'size' ),
		bedroomsEstimated=len( missing_rooms ),
	)

	src = json.dumps( P[ 'meta' ].get( 'source', 'plan.json' ) )
	digest = hashlib.sha1( open( PLAN, 'rb' ).read() ).hexdigest()[ :10 ]
	js = []
	js.append( '/* GENERATED by tools/gen_flats.py from blender/plans/plan.json - do not edit by hand.\n'
		' * Re-run: python3 tools/gen_flats.py\n'
		' * One record per flat DRAWN on the architect\'s plans (%d), numbered as the plans number them.\n'
		' * Areas are the printed ones where they agree with the drawing; every place they do not is in ISSUES.\n'
		' * Bedrooms: %s. Prices and availability are not in the plans and are not here. */\n'
		% ( len( flats ), 'from blender/plans/rooms.json' if R and not missing_rooms else 'ESTIMATED from inner area for %d flats (rooms.json %s)' % ( len( missing_rooms ), 'partial' if R else 'absent' ) ) )
	js.append( 'export const PLAN_SRC = %s;\n' % json.dumps( dict( source=P[ 'meta' ].get( 'source' ), plan_sha1=digest ) ) )
	js.append( 'export const BUILDING = %s;\n' % json.dumps( building ) )
	js.append( 'export const FLATS = [\n' + ',\n'.join( '\t' + json.dumps( f, ensure_ascii=False, separators=( ',', ':' ) ) for f in flats ) + '\n];\n' )
	js.append( 'export const OFFICES = [\n' + ',\n'.join( '\t' + json.dumps( o, separators=( ',', ':' ) ) for o in offices ) + '\n];\n' )
	js.append( '/* Every decision taken where the table and the drawing disagree - for the owner, not the buyer. */\n' )
	js.append( 'export const ISSUES = [\n' + ',\n'.join( '\t' + json.dumps( i, ensure_ascii=False, separators=( ',', ':' ) ) for i in issues ) + '\n];\n' )
	open( OUT_JS, 'w' ).write( ''.join( js ) )
	json.dump( plans, open( OUT_PLANS, 'w' ), separators=( ',', ':' ) )

	print( 'wrote %s (%d flats, %d offices, %d issues, %.0f KB) and %s (%.0f KB)' % (
		os.path.relpath( OUT_JS, ROOT ), len( flats ), len( offices ), len( issues ), os.path.getsize( OUT_JS ) / 1024,
		os.path.relpath( OUT_PLANS, ROOT ), os.path.getsize( OUT_PLANS ) / 1024 ) )
	if check:
		print( json.dumps( { k: building[ k ] for k in ( 'flats', 'perFloor', 'perBlock', 'perCore', 'residentialArea' ) } ) )
		dup = len( flats ) - len( { f[ 'n' ] for f in flats } )
		print( 'duplicate numbers:', dup )
		from collections import Counter
		print( 'types:', Counter( f[ 'type' ] for f in flats ) )
		print( 'aspects:', Counter( f[ 'aspectEn' ] for f in flats ) )
		for i in issues:
			print( ' ', i[ 'kind' ], i.get( 'n' ), '-', i.get( 'note', '' )[ :110 ] )


if __name__ == '__main__':
	main()
