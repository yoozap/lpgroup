/* walk.js - a visitor on foot, anywhere in the building.
 *
 * An ES module with no DOM, no renderer and no fetch: the host (app.js, or
 * walktest.html on the bench) hands it the two JSON files it already has and
 * drives it one frame at a time. Everything it knows about the building is
 * read off web/plan_meta.json (written by blender/build_interior.py from the
 * architect's plan) - nothing here is a number about the building.
 *
 * ---------------------------------------------------------------- the API
 *
 *   import { createWalker } from './walk.js';
 *   const W = createWalker( { meta, planMeta, toWorld, on, worker } );
 *     meta      web/scene_meta.json (only `frame` is read, for the default
 *               toWorld)
 *     planMeta  web/plan_meta.json
 *     toWorld   optional (x, y, z) plan metres -> [X, Y, Z] browser world.
 *               Default: scene_meta.frame (world = origin + ex x + ey y + up z)
 *     on        optional (type, payload) callback. Types:
 *                 'level'   {level, prev}        the body's storey changed
 *                 'flat'    {flat, office, level} entered/left a unit
 *                 'room'    {room}               entered a room / loggia
 *                 'lift'    {id, core, stops:[levels], at}  stepped into a
 *                           car - offer the stops; call W.liftGo(level)
 *                 'liftExit' {id}
 *                 'arrive'  {id, level}          a ride ended, doors opening
 *                 'door'    {id, node, level}    a leaf started to open
 *     worker    optional: true -> build neighbour levels' collision fields in
 *               a module Worker started from this file (see FIELDS below).
 *
 *   W.enter( { portal: 'C1' } )                 on the street, outside the door
 *   W.enter( { level: 'L05', at: [x, y], heading } )   heading: plan radians
 *   W.enter( { flat: '37' } ) / W.enter( { flat: '37', room: 2 } )
 *   W.toFlat( n ), W.toRoom( n, i ), W.toPortal( core )   the same, by name
 *
 *   const s = W.step( dt, { forward, strafe, turn, run, look: { yaw, pitch } } )
 *     forward/strafe  -1..1 (strafe +1 = to the right)
 *     turn            -1..1 keys, +1 turns right at WALK.TURN rad/s
 *     run             bool, the brisk pace
 *     look            pointer deltas in radians this frame (+yaw = right,
 *                     +pitch = up); applied as given
 *   returns the state:
 *     pos      { plan: [x, y, z(feet)], world: [X, Y, Z] }
 *     eye      world [X, Y, Z]; target: world point 1 m along the view;
 *              roll: radians about the view axis (camera.lookAt(target) then
 *              camera.rotateZ(roll)); near: the near plane to use (WALK.NEAR)
 *     heading, pitch   plan radians (heading from +x toward +y = clockwise
 *              seen from above in the browser, because the plan is a mirror)
 *     level    'L05' ; onStair bool ; inLift null | {id, riding, stops, at}
 *     flat     '37' | null ; office '7' | null ; room null | {name, kind, i}
 *     doors    [{id, node, level, angle, rotY, t}] every leaf on a resident
 *              level that is not shut. angle = plan degrees; rotY = the
 *              node's three.js rotation.y in the interior GLB's own frame
 *              (= -angle in radians, CONTRACT "Door leaves"). Absent = shut.
 *     lifts    [{id, core, shaft, car, z, doorOpen 0..1, level|null,
 *              doorNode (the landing door at `level`), door [[x,y],[x,y]]}]
 *              z = the car floor in plan metres -> carNode.position.y = z in
 *              cores.glb's frame. Landing doors slide: doorOpen 0 shut.
 *     needLevels  level ids the host must have loaded and visible (the body's
 *              own, plus the next one up/down while on or near a stair, or
 *              both ends of a ride). cores.glb is needed whenever inside;
 *              'ROOF' has no file of its own (the stair heads are in
 *              cores.glb, in_<core>_head_*). It ASKS AHEAD: near a stair
 *              it includes what the next flight down would see, and in a
 *              car the stretch of shaft it is about to run into.
 *     seesLevels  of those, the ones the body can see from where it is
 *              now (a host's "is anything missing on screen" check).
 *   Options also: ready( id, why ) -> bool, the host's answer to "is this
 *     level's geometry on screen" (why 'shaft': a car passing needs its
 *     walls only); the body is never let onto a surface, a flight or a
 *     stretch of shaft whose levels are not (default: always ready).
 *   W.solids( level, polys ) -> {kept, dropped}   the host's solids (the
 *     furniture, see furnitureSolids), painted into the level's field;
 *     a footprint in a doorway is dropped. W.stopsOf( liftId ) the stops a
 *     car offers; W.deadStops() the ones the data leaves without a floor.
 *     moving   false => nothing changed this step and nothing is in motion:
 *              the host may stop drawing (the gait and the springs snap to
 *              rest, memory "render on demand").
 *   W.liftGo( level ) -> bool   ride the car the body is standing in
 *   W.state()                   the last state without stepping
 *   W.field( level )            the collision field {x0,y0,cell,nx,ny,d,q}
 *   W.nav( level )              surfaces/doors of a level (minimap, tests)
 *   W.stats()                   field build ms and bytes per level
 *
 * --------------------------------------------------------- how it works
 *
 * FLOORS. A level's floor is a set of SURFACES read off plan_meta: its walk
 * polygons (flat, loggia at +0.02, corridor, hall, terrace, door throats,
 * half landings at their own z), its stair flights (nav.ramps: z runs from
 * z0 to z1 along `axis`, so a flight is a ramp, not treads), its lift cabs
 * (at the car's z) and, at grade, a doorstep outside each street door. The
 * body stands on the HIGHEST surface under it that is no more than a riser
 * above or below its feet - which is all a stair is: walking up a flight is
 * standing on a surface whose z rises under you, and stepping off its top
 * end lands on the next level's landing because that is now the highest
 * floor within a riser. A step that would leave the feet with nothing within
 * a riser is refused (a stairwell's edge is a wall), and so is one under
 * something lower than WALK.HEAD (the soffit of a flight in the halls).
 *
 * WALLS. A level's collision is a distance field: walk polygons, its own
 * flights and the flights arriving from below, painted free; nav.solid
 * painted solid; the cabs and their door throats painted free again. 5 cm
 * cells over the level's extent, one byte a cell (5 mm steps, 1.27 m cap -
 * nothing looks further than a body's radius), so about 1.2 MB a level.
 * A step is legal if it ends a body's radius from anything solid, retried
 * on each axis alone so a body runs along a wall instead of stopping dead -
 * the old flat walk's model, extended from one flat to the building.
 *
 * DOORS are the one thing the field cannot hold, because they move: a leaf
 * is a segment from its hinge at whatever angle it has got to. A door opens
 * when the body walks AT it (its path crosses the opening within
 * DOOR_NEAR, or it is pressed against the leaf) - not merely when it passes
 * by, or a corridor of 22 flats would open every door down its length - and
 * then stays open, sprung exactly as the old doorRig (K 34, C 12, snapped at
 * the ends). A leaf that swings into the body pushes it aside.
 *
 * LIFTS. A car is called to the body's floor when it comes near a landing
 * door, opens there, and stepping into it raises 'lift'. W.liftGo(level)
 * shuts the doors, lifts the brake, runs a jerk-limited S-curve (`scurve`,
 * WALK.LIFT_V/A/J) carrying the body with no gait, levels, and opens them
 * at the stop. A call lights the landing's lamp (`lifts[].called`) until
 * the doors there start to part. Cars stay where they were left.
 *
 * FIELDS are built lazily, for the body's level and its neighbours only;
 * anything further away is dropped. See `stats()` for the cost.
 */

export const WALK = {
	// ---- the body, as tuned with the owner in the show flat (app.js WK)
	V: 1.35, RUN: 2.45,          // m/s, a walk and a brisk one
	TAU_UP: 0.19, TAU_DOWN: 0.13,   // how long the legs take to answer
	R: 0.24,                     // how much floor a body needs round it
	STEP: 0.76,                  // one pace
	BOB: 0.019, SWAY: 0.024,     // the head's rise and fall, and its sway
	ROLL: 0.012, NOD: 0.004,     // radians
	STILL: 0.02,                 // under this the body has STOPPED
	EYE: 1.60,                   // eye over the floor it stands on
	TURN: 1.9,                   // rad/s on the turn keys
	PITCH_MAX: 1.35,
	/* The near plane that goes with R. The old page drew at 0.25 against a
	 * 0.24 body, so a shoulder on the plaster put the wall inside the near
	 * plane. 0.10 puts the near plane's far corner (~1.5 x near at a 60-70
	 * degree view) at 0.15 m, inside the body's 0.24 even with the sway. */
	NEAR: 0.10,
	// ---- floors
	RISER: 0.20,                 // the most the feet rise or fall in a step
	PROBE_DZ: 0.45,              // round the body's rim, on a flight's slope
	HEAD: 2.30,                  // a surface lower than this over the feet is a soffit
	// ---- doors (app.js doorRig)
	DOOR_NEAR: 1.55, DOOR_K: 34, DOOR_C: 12, LEAF_HALF: 0.02,
	// ---- lifts
	/* A traction lift, as a passenger feels one: rated speed, acceleration
	 * and jerk (the rate the acceleration itself builds and dies away -
	 * what makes a start and a stop soft). A run is a jerk-limited S-curve
	 * (`scurve`). A fast residential car (user 2026-11-25: "the lift is too
	 * slow"), still inside passenger comfort - 1.5 m/s^2 and 2.5 m/s^3:
	 * one storey (3.3 m) peaks near 1.8 m/s and takes ~3.6 s, the whole
	 * height ~11.5 s at 4 m/s. Was 2.5 / 1.0 / 1.5: 4.4 s and 17 s. */
	LIFT_V: 4.0, LIFT_A: 1.5, LIFT_J: 2.5,   // m/s, m/s^2, m/s^3
	LIFT_DOOR_OPEN: 0.9,         // seconds to slide fully open
	LIFT_DOOR_SHUT: 1.15,        // ...and shut (a door closes slower than it opens)
	LIFT_START: 0.2,             // doors shut -> brake lifted, the car moves
	LIFT_LEVEL: 0.15,            // stopped -> levelled, the doors start to open
	LIFT_NEAR: 1.8,              // landing doors open for a body this close
	LIFT_CALL: 2.4,              // ...and the car is called from this far
	// ---- the field
	CELL: 0.05, Q: 0.005,
	STREET_DEPTH: 3.0,           // the doorstep outside a street door
};

/* ================================================================ the lift's run
 * A jerk-limited S-curve over distance D: jerk J builds the acceleration to
 * A (or less), it holds, jerk -J lets it go at speed V (or less); a cruise;
 * the mirror image down to rest. Short runs never reach V - the peak speed
 * is found so the seven phases cover exactly D. `at( t )` -> [ s, v, a ]. */
export function scurve( D, V, A, J ) {
	const dacc = ( v ) => v >= A * A / J ? v / 2 * ( v / A + A / J ) : v * Math.sqrt( v / J );
	let v = V;
	if ( 2 * dacc( V ) > D ) {
		let lo = 0, hi = V;
		for ( let i = 0; i < 60; i ++ ) { const m = ( lo + hi ) / 2; if ( 2 * dacc( m ) > D ) hi = m; else lo = m; }
		v = lo;
	}
	if ( D < 1e-4 || v < 1e-6 ) return { D, T: 0, vmax: 0, at: () => [ D, 0, 0 ] };
	const ap = v >= A * A / J ? A : Math.sqrt( v * J );
	const tj = ap / J, ta = Math.max( 0, v / ap - tj ), tc = Math.max( 0, ( D - 2 * dacc( v ) ) / v );
	const seg = [ [ J, tj ], [ 0, ta ], [ - J, tj ], [ 0, tc ], [ - J, tj ], [ 0, ta ], [ J, tj ] ];
	const T = seg.reduce( ( q, x ) => q + x[ 1 ], 0 );
	return { D, T, vmax: v, amax: ap, at( t ) {
		let s = 0, u = 0, a = 0, r = Math.max( 0, Math.min( T, t ) );
		for ( const [ j, d ] of seg ) {
			const h = Math.min( r, d );
			s += u * h + a * h * h / 2 + j * h * h * h / 6;
			u += a * h + j * h * h / 2;
			a += j * h;
			r -= h;
			if ( r <= 0 ) break;
		}
		return t >= T ? [ D, 0, 0 ] : [ Math.min( D, s ), Math.max( 0, u ), a ];
	} };
}

/* ================================================================ geometry */

function ring( r ) {
	const a = new Float64Array( r.length * 2 );
	for ( let i = 0; i < r.length; i ++ ) { a[ 2 * i ] = r[ i ][ 0 ]; a[ 2 * i + 1 ] = r[ i ][ 1 ]; }
	return a;
}

function polyOf( p ) {
	const rings = [ ring( p.outline ) ];
	for ( const h of p.holes || [] ) rings.push( ring( h ) );
	let x0 = Infinity, y0 = Infinity, x1 = - Infinity, y1 = - Infinity;
	for ( const r of rings ) for ( let i = 0; i < r.length; i += 2 ) {
		if ( r[ i ] < x0 ) x0 = r[ i ]; if ( r[ i ] > x1 ) x1 = r[ i ];
		if ( r[ i + 1 ] < y0 ) y0 = r[ i + 1 ]; if ( r[ i + 1 ] > y1 ) y1 = r[ i + 1 ];
	}
	return { rings, bb: [ x0, y0, x1, y1 ] };
}

function rectPoly( pts ) { return polyOf( { outline: pts } ); }

// even-odd over every ring, so holes are holes
function inPoly( P, x, y ) {
	const b = P.bb;
	if ( x < b[ 0 ] || x > b[ 2 ] || y < b[ 1 ] || y > b[ 3 ] ) return false;
	let c = false;
	for ( const r of P.rings ) {
		const n = r.length;
		for ( let i = 0, j = n - 2; i < n; j = i, i += 2 ) {
			const yi = r[ i + 1 ], yj = r[ j + 1 ];
			if ( ( yi > y ) !== ( yj > y ) &&
				x < ( r[ j ] - r[ i ] ) * ( y - yi ) / ( yj - yi ) + r[ i ] ) c = ! c;
		}
	}
	return c;
}

function polyArea( P ) {
	let a = 0;
	P.rings.forEach( ( r, k ) => {
		let s = 0;
		for ( let i = 0, j = r.length - 2; i < r.length; j = i, i += 2 )
			s += r[ j ] * r[ i + 1 ] - r[ i ] * r[ j + 1 ];
		a += ( k === 0 ? 1 : - 1 ) * Math.abs( s ) / 2;
	} );
	return a;
}

function segDist( px, py, ax, ay, bx, by ) {
	const vx = bx - ax, vy = by - ay, L = vx * vx + vy * vy;
	let t = L > 0 ? ( ( px - ax ) * vx + ( py - ay ) * vy ) / L : 0;
	t = t < 0 ? 0 : t > 1 ? 1 : t;
	return Math.hypot( px - ax - vx * t, py - ay - vy * t );
}

// where a ray from p along unit d crosses segment a-b, or Infinity
function raySeg( px, py, dx, dy, ax, ay, bx, by ) {
	const ex = bx - ax, ey = by - ay;
	const den = dx * ey - dy * ex;
	if ( Math.abs( den ) < 1e-9 ) return Infinity;
	const wx = ax - px, wy = ay - py;
	const t = ( wx * ey - wy * ex ) / den;       // along the ray
	const u = ( wx * dy - wy * dx ) / den;       // along the segment
	return ( t >= 0 && u >= 0 && u <= 1 ) ? t : Infinity;
}

function segsCross( ax, ay, bx, by, cx, cy, dx, dy ) {
	const o = ( px, py, qx, qy, rx, ry ) => ( qx - px ) * ( ry - py ) - ( qy - py ) * ( rx - px );
	const d1 = o( cx, cy, dx, dy, ax, ay ), d2 = o( cx, cy, dx, dy, bx, by );
	const d3 = o( ax, ay, bx, by, cx, cy ), d4 = o( ax, ay, bx, by, dx, dy );
	return ( d1 * d2 < 0 ) && ( d3 * d4 < 0 );
}

const D2R = Math.PI / 180;

/* ============================================================ the field
 *
 * Pure and plain-data in, plain-data out, so the same function runs on the
 * main thread or in a Worker. `spec`: {x0, y0, nx, ny, cell, q, free, solid,
 * force} - three lists of polygons as arrays of flat rings, painted in that
 * order (free, then solid over it, then force-free over both). The result is
 * the distance from each cell centre to the nearest non-free cell's edge,
 * quantised to `q` metres in a Uint8Array (0 = not free).
 */
export function buildField( spec ) {
	const { x0, y0, nx, ny, cell } = spec;
	const N = nx * ny;
	const free = new Uint8Array( N );
	const paint = ( rings, v ) => {
		let rx0 = Infinity, ry0 = Infinity, rx1 = - Infinity, ry1 = - Infinity;
		for ( const r of rings ) for ( let i = 0; i < r.length; i += 2 ) {
			if ( r[ i ] < rx0 ) rx0 = r[ i ]; if ( r[ i ] > rx1 ) rx1 = r[ i ];
			if ( r[ i + 1 ] < ry0 ) ry0 = r[ i + 1 ]; if ( r[ i + 1 ] > ry1 ) ry1 = r[ i + 1 ];
		}
		const j0 = Math.max( 0, Math.ceil( ( ry0 - y0 ) / cell - 0.5 ) );
		const j1 = Math.min( ny - 1, Math.floor( ( ry1 - y0 ) / cell - 0.5 ) );
		if ( j1 < j0 ) return;
		const rows = new Array( j1 - j0 + 1 );
		for ( let k = 0; k < rows.length; k ++ ) rows[ k ] = [];
		for ( const r of rings ) {
			const n = r.length;
			for ( let i = 0, j = n - 2; i < n; j = i, i += 2 ) {
				const xa = r[ j ], ya = r[ j + 1 ], xb = r[ i ], yb = r[ i + 1 ];
				if ( ya === yb ) continue;
				const lo = Math.min( ya, yb ), hi = Math.max( ya, yb );
				// rows whose centre y is in [lo, hi)
				let ja = Math.max( j0, Math.ceil( ( lo - y0 ) / cell - 0.5 ) );
				const jb = Math.min( j1, Math.ceil( ( hi - y0 ) / cell - 0.5 ) - 1 );
				for ( ; ja <= jb; ja ++ ) {
					const yc = y0 + ( ja + 0.5 ) * cell;
					rows[ ja - j0 ].push( xa + ( xb - xa ) * ( yc - ya ) / ( yb - ya ) );
				}
			}
		}
		for ( let k = 0; k < rows.length; k ++ ) {
			const xs = rows[ k ];
			if ( xs.length < 2 ) continue;
			xs.sort( ( a, b ) => a - b );
			const base = ( j0 + k ) * nx;
			for ( let m = 0; m + 1 < xs.length; m += 2 ) {
				const ia = Math.max( 0, Math.ceil( ( xs[ m ] - x0 ) / cell - 0.5 ) );
				const ib = Math.min( nx - 1, Math.floor( ( xs[ m + 1 ] - x0 ) / cell - 0.5 ) );
				for ( let i = ia; i <= ib; i ++ ) free[ base + i ] = v;
			}
		}
	};
	for ( const p of spec.free ) paint( p, 1 );
	for ( const p of spec.solid ) paint( p, 0 );
	for ( const p of spec.force ) paint( p, 1 );

	/* Exact squared Euclidean distance (Felzenszwalb & Huttenlocher), rows
	 * then columns. Linear in the cells, which is what makes a whole storey
	 * of an 83 m building affordable. */
	const INF = 1e20;
	const f = new Float32Array( N );
	for ( let i = 0; i < N; i ++ ) f[ i ] = free[ i ] ? INF : 0;
	const M = Math.max( nx, ny );
	const g = new Float64Array( M ), out = new Float64Array( M ), z = new Float64Array( M + 1 );
	const v = new Int32Array( M );
	const edt1 = ( n ) => {
		let k = 0; v[ 0 ] = 0; z[ 0 ] = - INF; z[ 1 ] = INF;
		for ( let q = 1; q < n; q ++ ) {
			let p = v[ k ];
			let s = ( ( g[ q ] + q * q ) - ( g[ p ] + p * p ) ) / ( 2 * q - 2 * p );
			while ( s <= z[ k ] ) {
				k --; p = v[ k ];
				s = ( ( g[ q ] + q * q ) - ( g[ p ] + p * p ) ) / ( 2 * q - 2 * p );
			}
			k ++; v[ k ] = q; z[ k ] = s; z[ k + 1 ] = INF;
		}
		k = 0;
		for ( let q = 0; q < n; q ++ ) {
			while ( z[ k + 1 ] < q ) k ++;
			const p = v[ k ];
			out[ q ] = ( q - p ) * ( q - p ) + g[ p ];
		}
	};
	for ( let j = 0; j < ny; j ++ ) {
		const b = j * nx;
		for ( let i = 0; i < nx; i ++ ) g[ i ] = f[ b + i ];
		edt1( nx );
		for ( let i = 0; i < nx; i ++ ) f[ b + i ] = out[ i ];
	}
	for ( let i = 0; i < nx; i ++ ) {
		for ( let j = 0; j < ny; j ++ ) g[ j ] = f[ j * nx + i ];
		edt1( ny );
		for ( let j = 0; j < ny; j ++ ) f[ j * nx + i ] = out[ j ];
	}
	const d = new Uint8Array( N ), q = spec.q;
	for ( let i = 0; i < N; i ++ ) {
		if ( ! free[ i ] ) continue;
		// centre-to-centre less half a cell: the distance to the solid cell's edge
		const m = Math.sqrt( f[ i ] ) * cell - cell * 0.5;
		const u = Math.round( m / q );
		d[ i ] = u < 1 ? 1 : u > 255 ? 255 : u;
	}
	return { x0, y0, nx, ny, cell, q, d };
}

// bilinear over cell centres; off the grid is solid
function fieldAt( G, x, y ) {
	if ( ! G ) return 0;
	const fx = ( x - G.x0 ) / G.cell - 0.5, fy = ( y - G.y0 ) / G.cell - 0.5;
	const i = Math.floor( fx ), j = Math.floor( fy );
	const tx = fx - i, ty = fy - j, nx = G.nx, ny = G.ny, d = G.d;
	const at = ( a, b ) => ( a < 0 || b < 0 || a >= nx || b >= ny ) ? 0 : d[ b * nx + a ];
	return G.q * ( at( i, j ) * ( 1 - tx ) * ( 1 - ty ) + at( i + 1, j ) * tx * ( 1 - ty )
		+ at( i, j + 1 ) * ( 1 - tx ) * ty + at( i + 1, j + 1 ) * tx * ty );
}

/* A Worker started from this very file builds fields off the main thread. */
const IN_WORKER = typeof WorkerGlobalScope !== 'undefined' && typeof self !== 'undefined'
	&& self instanceof WorkerGlobalScope; // eslint-disable-line no-undef
if ( IN_WORKER ) {
	self.onmessage = ( e ) => {
		const t0 = performance.now();
		const F = buildField( e.data.spec );
		self.postMessage( { id: e.data.id, field: F, ms: performance.now() - t0 }, [ F.d.buffer ] );
	};
}

/* ======================================================== the furniture
 * What a body cannot walk through, from web/interior/furn/index.json: every
 * piece's drawn box (`box {centre, size [across, along], heading}` in plan
 * metres; corner glyphs `box_axis_aligned` with size [dx, dy]) that is
 * taller than `minH` - a bed, a table, a kitchen run are solid, a rug or a
 * coffee table is not. `heightOf( piece )` is the host's: it has the meshes
 * (the page reads them off the GLB, the rig off its accessors). Plan-data
 * in, polygons out, so the page and the rig paint exactly the same thing. */
export function furnitureSolids( lvIndex, heightOf, minH = 0.4 ) {
	const out = [];
	for ( const U of Object.values( ( lvIndex && lvIndex.units ) || {} ) ) for ( const p of U.pieces || [] ) {
		const b = p.box;
		if ( ! b || ! b.centre || ! b.size ) continue;
		const h = heightOf( p );
		if ( ! ( h > minH ) ) continue;
		const [ cx, cy ] = b.centre;
		let ring;
		if ( b.box_axis_aligned ) {
			const hx = b.size[ 0 ] / 2, hy = b.size[ 1 ] / 2;
			ring = [ [ cx - hx, cy - hy ], [ cx + hx, cy - hy ], [ cx + hx, cy + hy ], [ cx - hx, cy + hy ] ];
		} else {
			const t = ( b.heading || 0 ) * D2R, fx = Math.cos( t ), fy = Math.sin( t );
			const w = b.size[ 0 ] / 2, d = b.size[ 1 ] / 2;
			ring = [ [ - w, - d ], [ w, - d ], [ w, d ], [ - w, d ] ].map( ( [ u, v ] ) =>
				[ cx - fy * u + fx * v, cy + fx * u + fy * v ] );
		}
		out.push( { outline: ring, node: p.node, kind: p.kind } );
	}
	return out;
}

/* ============================================================ the walker */

export function createWalker( opts ) {
	const PM = opts.planMeta, SM = opts.meta || {};
	const emit = opts.on || ( () => {} );
	/* "Is the geometry HERE": the host answers, per level id, whether that
	 * level is on screen yet. A body is never let onto a surface whose level
	 * is not - a flight wants both of its ends - and a car's doors stay shut
	 * at a stop until its level is: the visitor waits at the threshold, a
	 * shut door or a landing, rather than walking into a hole. The doorstep
	 * outside a street door is the street's and always ready. */
	const ready = opts.ready || ( () => true );
	const fr = SM.frame;
	const toWorld = opts.toWorld || ( fr ? ( x, y, z ) => [
		fr.origin[ 0 ] + fr.ex[ 0 ] * x + fr.ey[ 0 ] * y + fr.up[ 0 ] * z,
		fr.origin[ 1 ] + fr.ex[ 1 ] * x + fr.ey[ 1 ] * y + fr.up[ 1 ] * z,
		fr.origin[ 2 ] + fr.ex[ 2 ] * x + fr.ey[ 2 ] * y + fr.up[ 2 ] * z ] : ( x, y, z ) => [ x, z, y ] );

	/* ---------------------------------------------------- the levels
	 * Every level with a nav block, plus the stair heads: the ROOF level has
	 * no nav of its own, so its floor is the cores' `head.walk` at head.z -
	 * which is where the top flights land. */
	const LV = [];
	for ( const l of PM.levels ) if ( l.nav ) LV.push( { src: l, id: l.id, z: l.z, h: l.h } );
	LV.sort( ( a, b ) => a.z - b.z );
	const heads = ( PM.cores || [] ).filter( c => c.head && c.head.walk );
	if ( heads.length ) {
		const roof = PM.levels.find( l => l.kind === 'roof' );
		LV.push( { src: null, id: roof ? roof.id : 'ROOF', z: heads[ 0 ].head.z,
			h: heads[ 0 ].head.z_top - heads[ 0 ].head.z, heads } );
	}
	const LI = new Map( LV.map( ( L, i ) => [ L.id, i ] ) );

	/* ---------------------------------------------------- the lifts */
	const LIFTS = ( PM.lifts || [] ).map( ( l ) => {
		const stops = l.stops.map( s => ( { level: s.level, z: s.z, door: s.door,
			node: `in_${l.core}_lift${l.shaft}_${s.level}_door__chrome` } ) );
		const at = Math.max( 0, stops.findIndex( s => s.level === l.car_at ) );
		return { id: `${l.core}-${l.shaft}`, core: l.core, shaft: l.shaft, car: l.car_node,
			cab: polyOf( l.cab ), stops, at, target: at, z: stops[ at ].z, v: 0, a: 0,
			doorT: 0, riding: false, prof: null, wait: 0, call: null };
	} );

	for ( let i = 0; i < LV.length; i ++ ) prepLevel( LV[ i ], i );
	/* The terrace's furniture - planter benches, cafe sets, pergolas, tree
	 * tubs - stands on the +4.8 deck in the STREET file, and plan_meta's nav
	 * knows nothing of it: scene_meta.site.terrace.solids gives every
	 * footprint as a plan-frame box (exterior-polish, build 3). They are
	 * solid on the level at the deck's height, through the same doorway rule
	 * as furniture, so a visitor on the terrace walks round them. */
	{
		const T = SM.site && SM.site.terrace;
		const li = T && Array.isArray( T.solids ) ? LV.findIndex( L => Math.abs( L.z - ( T.z ?? 4.8 ) ) < 0.05 ) : - 1;
		if ( li >= 0 ) {
			/* ...but not a box standing over a flight that lands on this
			 * level: that is the terrace stair's HOUSE, whose walls the
			 * interior already has - solid all through, it shut the stair's
			 * head and nobody arrived on the deck at all. */
			const flights = [];
			for ( const j of [ li - 1, li ] ) if ( LV[ j ] ) for ( const f of LV[ j ].surf ) {
				if ( ! f.ramp ) continue;
				const r = f.P.rings[ 0 ]; let fx0 = Infinity, fy0 = Infinity, fx1 = - Infinity, fy1 = - Infinity;
				for ( let i = 0; i < r.length; i += 2 ) { fx0 = Math.min( fx0, r[ i ] ); fx1 = Math.max( fx1, r[ i ] ); fy0 = Math.min( fy0, r[ i + 1 ] ); fy1 = Math.max( fy1, r[ i + 1 ] ); }
				flights.push( [ fx0, fy0, fx1, fy1 ] );
			}
			const overFlight = ( [ x0, y0, x1, y1 ] ) => flights.some( f => x0 < f[ 2 ] && x1 > f[ 0 ] && y0 < f[ 3 ] && y1 > f[ 1 ] );
			const boxes = T.solids.filter( b => b && b.length >= 4 && ! overFlight( b ) ).map( ( [ x0, y0, x1, y1 ] ) =>
				[ [ x0, y0 ], [ x1, y0 ], [ x1, y1 ], [ x0, y1 ] ] );
			LV[ li ].site = doorways( LV[ li ], boxes ).kept;
		}
	}


	function prepLevel( L, li ) {
		const S = L.surf = [];
		const add = ( s ) => { s.li = li; s.level = L.id; S.push( s ); return s; };
		const src = L.src;
		if ( src ) {
			for ( const w of src.nav.walk ) add( { kind: w.kind, z: w.z, P: polyOf( w.poly ),
				owner: w.owner || null, door: w.door || null, core: w.core || null } );
			for ( const r of src.nav.ramps ) {
				const P = polyOf( r.poly );
				let lo = Infinity, hi = - Infinity;
				const rr = P.rings[ 0 ];
				for ( let i = 0; i < rr.length; i += 2 ) {
					const t = rr[ i ] * r.axis[ 0 ] + rr[ i + 1 ] * r.axis[ 1 ];
					if ( t < lo ) lo = t; if ( t > hi ) hi = t;
				}
				add( { kind: 'stair', P, z: Math.min( r.z0, r.z1 ), ramp: { z0: r.z0, z1: r.z1,
					ax: r.axis[ 0 ], ay: r.axis[ 1 ], lo, hi }, core: r.core, flight: r.flight,
				from: r.from, to: r.to, owner: null } );
			}
			for ( const c of src.nav.lifts ) {
				const lift = LIFTS.find( l => l.core === c.core && l.shaft === c.shaft );
				if ( ! lift ) continue;
				add( { kind: 'lift', P: polyOf( c.cab ), z: c.z, lift, door: c.door, core: c.core, owner: null } );
				/* The sill between the car and the landing: the car's floor
				 * carried out under the doors, so a body can stand in them. */
				const [ a, b ] = c.door, ux = b[ 0 ] - a[ 0 ], uy = b[ 1 ] - a[ 1 ], l = Math.hypot( ux, uy ) || 1;
				const nx = - uy / l * 0.26, ny = ux / l * 0.26;
				add( { kind: 'sill', P: rectPoly( [ [ a[ 0 ] - nx, a[ 1 ] - ny ], [ b[ 0 ] - nx, b[ 1 ] - ny ],
					[ b[ 0 ] + nx, b[ 1 ] + ny ], [ a[ 0 ] + nx, a[ 1 ] + ny ] ] ), z: c.z, lift, core: c.core, owner: null } );
			}
		} else {
			for ( const c of L.heads ) for ( const w of c.head.walk )
				add( { kind: 'head', z: c.head.z, P: polyOf( w ), core: c.id, owner: null } );
		}
		// the doorstep outside every street opening at grade
		L.aprons = [];
		if ( src && li === LI.get( 'L00' ) ) {
			const walkIn = ( x, y ) => S.some( s => s.kind !== 'stair' && inPoly( s.P, x, y ) );
			for ( const p of PM.portals || [] ) {
				const s = apron( p.a, p.b, p.normal, 0.30 );
				L.aprons.push( add( { kind: 'street', z: L.z, P: s, core: p.core, owner: null, portal: p } ) );
			}
			const doors = ( src.doors || [] ).filter( d => d.kind === 'street' );
			for ( const d of doors ) {
				if ( ( PM.portals || [] ).some( p => p.node === d.node ) ) continue;
				const a = [ d.hinge[ 0 ], d.hinge[ 1 ] ];
				const b = [ a[ 0 ] + d.w * Math.cos( d.shut * D2R ), a[ 1 ] + d.w * Math.sin( d.shut * D2R ) ];
				let n = [ - Math.sin( d.shut * D2R ), Math.cos( d.shut * D2R ) ];
				const cx = ( a[ 0 ] + b[ 0 ] ) / 2, cy = ( a[ 1 ] + b[ 1 ] ) / 2;
				if ( walkIn( cx + n[ 0 ] * 0.6, cy + n[ 1 ] * 0.6 ) ) n = [ - n[ 0 ], - n[ 1 ] ];
				if ( walkIn( cx + n[ 0 ] * 0.6, cy + n[ 1 ] * 0.6 ) ) continue;   // no outside to it
				L.aprons.push( add( { kind: 'street', z: L.z, P: apron( a, b, n, 0.10 ), owner: null,
					streetDoor: d.node } ) );
			}
		}
		let x0 = Infinity, y0 = Infinity, x1 = - Infinity, y1 = - Infinity;
		for ( const s of S ) {
			const b = s.P.bb;
			x0 = Math.min( x0, b[ 0 ] ); y0 = Math.min( y0, b[ 1 ] );
			x1 = Math.max( x1, b[ 2 ] ); y1 = Math.max( y1, b[ 3 ] );
		}
		L.bb = [ x0 - 0.5, y0 - 0.5, x1 + 0.5, y1 + 0.5 ];
		// surfaces bucketed on a 1 m grid; a bucket is a HAZARD if a body near
		// it could have a floor at another height round its rim
		const B = L.buck = { x0: L.bb[ 0 ], y0: L.bb[ 1 ], c: 1,
			nx: Math.ceil( ( L.bb[ 2 ] - L.bb[ 0 ] ) ), ny: Math.ceil( ( L.bb[ 3 ] - L.bb[ 1 ] ) ) };
		B.list = new Array( B.nx * B.ny ); B.haz = new Uint8Array( B.nx * B.ny );
		S.forEach( ( s, k ) => {
			const b = s.P.bb;
			const i0 = Math.max( 0, Math.floor( b[ 0 ] - B.x0 ) - 1 ), i1 = Math.min( B.nx - 1, Math.floor( b[ 2 ] - B.x0 ) + 1 );
			const j0 = Math.max( 0, Math.floor( b[ 1 ] - B.y0 ) - 1 ), j1 = Math.min( B.ny - 1, Math.floor( b[ 3 ] - B.y0 ) + 1 );
			const hz = s.kind === 'stair' || s.kind === 'half_landing' || s.kind === 'lift' || s.kind === 'sill'
				|| s.kind === 'street' || s.kind === 'head';
			for ( let j = j0; j <= j1; j ++ ) for ( let i = i0; i <= i1; i ++ ) {
				const q = j * B.nx + i;
				( B.list[ q ] || ( B.list[ q ] = [] ) ).push( k );
				if ( hz ) B.haz[ q ] = 1;
			}
		} );
		/* Every leaf of the level: the common doors and each unit's. */
		L.doors = [];
		L.units = [];
		if ( src ) {
			const units = ( src.flats || [] ).map( u => ( { u, office: false } ) )
				.concat( ( src.offices || [] ).map( u => ( { u, office: true } ) ) );
			const leaf = ( d ) => {
				const sh = d.shut * D2R;
				const ex = Math.cos( sh ), ey = Math.sin( sh );
				const D = { key: d.node, id: d.id, node: d.node, kind: d.kind, owner: d.owner,
					level: L.id, z: L.z, hx: d.hinge[ 0 ], hy: d.hinge[ 1 ], w: d.w, shut: d.shut, open: d.open,
					ax: d.hinge[ 0 ], ay: d.hinge[ 1 ], bx: d.hinge[ 0 ] + ex * d.w, by: d.hinge[ 1 ] + ey * d.w,
					cx: d.hinge[ 0 ] + ex * d.w / 2, cy: d.hinge[ 1 ] + ey * d.w / 2,
					t: 0, v: 0, latched: false, rest: 1, max: 1 };
				L.doors.push( D );
			};
			for ( const d of src.doors || [] ) leaf( d );
			for ( const { u, office } of units ) {
				for ( const d of u.doors || [] ) leaf( d );
				const rooms = ( u.rooms || [] ).map( ( r, i ) => ( { i, name: r.name, kind: r.kind,
					id: r.rooms_id || null, P: polyOf( r.poly ) } ) );
				const logg = ( u.loggias || [] ).map( ( p, k ) => ( { i: rooms.length + k,
					name: 'Loggia', kind: 'loggia', id: null, P: polyOf( p ) } ) );
				L.units.push( { n: u.n, token: u.token, office, P: polyOf( u.poly ),
					rooms: rooms.concat( logg ), doors: u.doors || [], core: u.core } );
			}
		}
		L.unitBy = new Map( L.units.map( u => [ u.token, u ] ) );
		L.field = null;
		L.extra = [];          // solids the host adds: the furniture (W.solids)
		L.ver = 0;             // ...and the field's version, for the worker
	}

	// a doorstep: the opening a-b pushed `depth` out along n, `inset` in
	function apron( a, b, n, inset ) {
		const ux = b[ 0 ] - a[ 0 ], uy = b[ 1 ] - a[ 1 ], L = Math.hypot( ux, uy ) || 1;
		const tx = ux / L * 0.6, ty = uy / L * 0.6, D = WALK.STREET_DEPTH;
		const A = [ a[ 0 ] - tx - n[ 0 ] * inset, a[ 1 ] - ty - n[ 1 ] * inset ];
		const Bp = [ b[ 0 ] + tx - n[ 0 ] * inset, b[ 1 ] + ty - n[ 1 ] * inset ];
		return rectPoly( [ A, Bp, [ Bp[ 0 ] + n[ 0 ] * D, Bp[ 1 ] + n[ 1 ] * D ],
			[ A[ 0 ] + n[ 0 ] * D, A[ 1 ] + n[ 1 ] * D ] ] );
	}

	/* ---------------------------------------------------- fields */
	const STATS = {};
	function fieldSpec( li ) {
		const L = LV[ li ], C = WALK.CELL;
		const free = [], solid = [], force = [];
		const rings = P => P.rings.map( r => Array.from( r ) );
		for ( const s of L.surf ) if ( s.kind !== 'lift' && s.kind !== 'sill' ) free.push( rings( s.P ) );
		if ( li > 0 ) for ( const s of LV[ li - 1 ].surf ) if ( s.kind === 'stair' ) free.push( rings( s.P ) );
		if ( L.src ) for ( const p of L.src.nav.solid ) solid.push( rings( polyOf( p ) ) );
		/* Furniture: the build's own footprints under nav (`furn`, written by
		 * the interior build from the furniture files), or else the host's
		 * (W.solids, from index.json). Either way through the same rule:
		 * solid over 0.4 m, never in a doorway. */
		for ( const P of navFurn( L ).kept ) solid.push( rings( P ) );
		for ( const P of L.extra ) solid.push( rings( P ) );
		for ( const P of L.site || [] ) solid.push( rings( P ) );
		/* The cabs, and the throat between each cab and its landing door,
		 * are inside nav.solid (the shaft). They are carved back out: the
		 * door that closes the throat is a moving segment, like a leaf. */
		for ( const s of L.surf ) if ( s.kind === 'lift' ) {
			force.push( rings( s.P ) );
			const [ a, b ] = s.door, ux = b[ 0 ] - a[ 0 ], uy = b[ 1 ] - a[ 1 ], l = Math.hypot( ux, uy ) || 1;
			const nx = - uy / l * 0.26, ny = ux / l * 0.26;
			force.push( [ [ a[ 0 ] - nx, a[ 1 ] - ny, b[ 0 ] - nx, b[ 1 ] - ny, b[ 0 ] + nx, b[ 1 ] + ny,
				a[ 0 ] + nx, a[ 1 ] + ny ] ] );
		}
		const x0 = L.bb[ 0 ], y0 = L.bb[ 1 ];
		const nx = Math.ceil( ( L.bb[ 2 ] - x0 ) / C ), ny = Math.ceil( ( L.bb[ 3 ] - y0 ) / C );
		return { x0, y0, nx, ny, cell: C, q: WALK.Q, free, solid, force };
	}
	function ensureField( li ) {
		const L = LV[ li ];
		if ( ! L.field ) {
			const t0 = now();
			L.field = buildField( fieldSpec( li ) );
			STATS[ L.id ] = { ms: +( now() - t0 ).toFixed( 1 ), bytes: L.field.d.byteLength,
				cells: [ L.field.nx, L.field.ny ], where: 'main' };
		}
		return L.field;
	}
	const now = () => ( typeof performance !== 'undefined' ? performance.now() : Date.now() );

	let worker = null, wid = 0;
	const pending = new Map();
	if ( opts.worker && typeof Worker !== 'undefined' ) {
		try {
			worker = new Worker( new URL( import.meta.url ), { type: 'module' } );
			worker.onmessage = ( e ) => {
				const job = pending.get( e.data.id );
				pending.delete( e.data.id );
				const li = job && job.li, L = LV[ li ];
				// a field asked for before the level's solids changed is stale
				if ( L && ! L.field && job.ver === L.ver ) {
					L.field = e.data.field;
					STATS[ L.id ] = { ms: +e.data.ms.toFixed( 1 ), bytes: L.field.d.byteLength,
						cells: [ L.field.nx, L.field.ny ], where: 'worker' };
				}
			};
		} catch ( e ) { worker = null; }
	}
	/* Keep the body's level and its neighbours, drop the rest; the
	 * neighbours are asked for ahead of time (in the worker if there is one)
	 * so a flight never waits on arithmetic. */
	function manageFields( li ) {
		for ( let i = 0; i < LV.length; i ++ ) {
			const L = LV[ i ];
			if ( Math.abs( i - li ) > 1 ) { L.field = null; continue; }
			if ( L.field || i === li ) continue;
			if ( worker ) {
				if ( ! [ ...pending.values() ].some( j => j.li === i && j.ver === L.ver ) ) {
					const id = ++ wid; pending.set( id, { li: i, ver: L.ver } );
					worker.postMessage( { id, spec: fieldSpec( i ) } );
				}
			} else if ( opts.eagerNeighbours ) ensureField( i );
		}
		ensureField( li );
	}

	/* ---------------------------------------------------- floors */
	function zOf( s, x, y ) {
		if ( s.ramp ) {
			const r = s.ramp, t = ( x * r.ax + y * r.ay - r.lo ) / ( r.hi - r.lo );
			return r.z0 + ( r.z1 - r.z0 ) * ( t < 0 ? 0 : t > 1 ? 1 : t );
		}
		// a car's floor is a floor on this storey only while the car is here
		if ( s.lift ) return Math.abs( s.lift.z - s.z ) < 0.3 ? s.lift.z : NaN;
		return s.z;
	}
	const ZS = new Float64Array( 64 );
	let zsN = 0;
	/* The highest surface under (x, y) with its top in [zc - down, zc + up],
	 * and in ZS every surface height there. Only levels whose band is near
	 * zc are asked. */
	/* The walk polygons are cut from the drawing separately, and where a
	 * door throat meets a room they can miss each other by a few
	 * millimetres - a crack a body would fall into. A point on no surface
	 * looks 3 cm round itself before it is called a void. */
	const CRACK = [ [ 0.03, 0 ], [ - 0.03, 0 ], [ 0, 0.03 ], [ 0, - 0.03 ] ];
	function surfAt( x, y, zc, up, down ) {
		const r = surfAt0( x, y, zc, up, down );
		if ( r ) return r;
		for ( const [ dx, dy ] of CRACK ) {
			const q = surfAt0( x + dx, y + dy, zc, up, down );
			if ( q ) return q;
		}
		surfAt0( x, y, zc, up, down );   // ZS as it is at the point itself
		return null;
	}
	function surfAt0( x, y, zc, up, down ) {
		let best = null, bz = - Infinity;
		zsN = 0;
		for ( let li = 0; li < LV.length; li ++ ) {
			const L = LV[ li ];
			if ( zc < L.z - 3.5 || zc > L.z + ( L.h || 3 ) + 3.5 ) continue;
			const B = L.buck;
			const i = Math.floor( x - B.x0 ), j = Math.floor( y - B.y0 );
			if ( i < 0 || j < 0 || i >= B.nx || j >= B.ny ) continue;
			const lst = B.list[ j * B.nx + i ];
			if ( ! lst ) continue;
			for ( const k of lst ) {
				const s = L.surf[ k ];
				if ( ! inPoly( s.P, x, y ) ) continue;
				const z = zOf( s, x, y );
				if ( z !== z ) continue;
				if ( zsN < 64 ) ZS[ zsN ++ ] = z;
				if ( z <= zc + up && z >= zc - down && z > bz ) { bz = z; best = s; }
			}
		}
		return best ? { s: best, z: bz } : null;
	}
	function hazard( x, y, zc ) {
		for ( const L of LV ) {
			if ( zc < L.z - 3.5 || zc > L.z + ( L.h || 3 ) + 3.5 ) continue;
			const B = L.buck, i = Math.floor( x - B.x0 ), j = Math.floor( y - B.y0 );
			if ( i >= 0 && j >= 0 && i < B.nx && j < B.ny && B.haz[ j * B.nx + i ] ) return true;
		}
		return false;
	}
	const PROBES = [];
	for ( let k = 0; k < 8; k ++ ) PROBES.push( [ Math.cos( k * Math.PI / 4 ), Math.sin( k * Math.PI / 4 ) ] );
	/* Can a body stand at (x, y) coming from feet height zc? Returns the
	 * floor or null. A body needs a floor within a riser under its centre,
	 * nothing lower than HEAD over it, and - near anything that is not one
	 * flat floor - a floor round its rim too, or a wall: a stairwell's edge
	 * stops it a body's radius short, the way a rail would. */
	function stand( x, y, zc, G ) {
		const f = surfAt( x, y, zc, WALK.RISER, WALK.RISER );
		if ( ! f ) return null;
		for ( let k = 0; k < zsN; k ++ ) if ( ZS[ k ] > f.z + WALK.RISER && ZS[ k ] < f.z + WALK.HEAD ) return null;
		if ( ! hazard( x, y, f.z ) ) return f;
		const R = WALK.R;
		for ( const [ ux, uy ] of PROBES ) {
			const px = x + ux * R, py = y + uy * R;
			if ( fieldAt( G, px, py ) <= WALK.CELL ) continue;         // a wall: fine
			const g = surfAt( px, py, f.z, WALK.PROBE_DZ, WALK.PROBE_DZ );
			if ( ! g ) return null;                                    // floor there, but not ours
			for ( let k = 0; k < zsN; k ++ )
				if ( ZS[ k ] > f.z + WALK.PROBE_DZ && ZS[ k ] < f.z + WALK.HEAD ) return null;
		}
		return f;
	}

	/* ---------------------------------------------------- doors */
	const DOORS = new Map();      // node -> door, every level
	const LIVE = new Set();       // leaves in motion or wanting to be
	for ( const L of LV ) for ( const D of L.doors ) DOORS.set( D.key, D );
	function leafAngle( D ) { return D.shut + D.open * D.t; }
	function leafSeg( D ) {
		const a = leafAngle( D ) * D2R, len = D.w - 0.008;
		return [ D.hx, D.hy, D.hx + Math.cos( a ) * len, D.hy + Math.sin( a ) * len ];
	}
	function leafHits( D, t ) {
		if ( Math.abs( D.hx - B.x ) > D.w + 0.5 || Math.abs( D.hy - B.y ) > D.w + 0.5 ) return false;
		const a = ( D.shut + D.open * t ) * D2R, len = D.w - 0.008;
		return segDist( B.x, B.y, D.hx, D.hy, D.hx + Math.cos( a ) * len, D.hy + Math.sin( a ) * len )
			- WALK.LEAF_HALF < WALK.R - 0.002;
	}
	/* ...unless the body can step out of its way: the leaf pushes it the
	 * few centimetres it needs - the old doorRig's push, done before the
	 * leaf is in the body rather than after - never into a wall's clearance
	 * or off the floor. Away from the hinge first: pushed straight off the
	 * leaf a body is herded round with it into the corner the open leaf
	 * makes with the wall, and pinned there (the balcony doors of flats 47,
	 * 89, 110 ... open against a side wall 0.25 m away). */
	function stepAside( D, t ) {
		const a = ( D.shut + D.open * t ) * D2R, len = D.w - 0.008;
		const ax = D.hx, ay = D.hy, bx = ax + Math.cos( a ) * len, by = ay + Math.sin( a ) * len;
		const clear = ( x, y ) => segDist( x, y, ax, ay, bx, by ) - WALK.LEAF_HALF >= WALK.R + 0.002;
		if ( clear( B.x, B.y ) ) return true;
		const vx = bx - ax, vy = by - ay, L2 = vx * vx + vy * vy;
		let u = ( ( B.x - ax ) * vx + ( B.y - ay ) * vy ) / L2; u = u < 0 ? 0 : u > 1 ? 1 : u;
		const dirs = [ [ B.x - ax, B.y - ay ], [ B.x - ax - vx * u, B.y - ay - vy * u ] ];
		const G = ensureField( B.li );
		for ( const [ dx, dy ] of dirs ) {
			const l = Math.hypot( dx, dy );
			if ( l < 1e-6 ) continue;
			for ( let m = 0.005; m <= 0.08; m += 0.005 ) {
				const x = B.x + dx / l * m, y = B.y + dy / l * m;
				if ( ! clear( x, y ) ) continue;
				if ( fieldAt( G, x, y ) < WALK.R ) break;
				if ( free( G, x, y, D ) < WALK.R ) break;      // nor into another leaf
				const f = stand( x, y, B.z, G );
				if ( ! f ) break;
				B.x = x; B.y = y; B.z = f.z; B.surf = f.s;
				return true;
			}
		}
		return false;
	}
	function liftDoorSegs( lift, stop, out ) {
		// centre-opening: each half slides back toward its own end
		const [ a, b ] = stop.door, t = ( lift.at === lift.stops.indexOf( stop ) && lift.v === 0 ) ? lift.doorT : 0;
		if ( t >= 1 ) return;
		const mx = ( a[ 0 ] + b[ 0 ] ) / 2, my = ( a[ 1 ] + b[ 1 ] ) / 2, k = 1 - t;
		out.push( [ a[ 0 ], a[ 1 ], a[ 0 ] + ( mx - a[ 0 ] ) * k, a[ 1 ] + ( my - a[ 1 ] ) * k ] );
		out.push( [ b[ 0 ], b[ 1 ], b[ 0 ] + ( mx - b[ 0 ] ) * k, b[ 1 ] + ( my - b[ 1 ] ) * k ] );
	}
	/* The moving solids near the body: leaves on its level, and the lift
	 * doors of its level. Gathered once a frame - a body crosses 4 cm. */
	let near = [];
	/* The doors that can touch the body: those of every storey whose floor
	 * is within reach of its feet - a body coming off the top of a flight
	 * meets the next storey's doors before it is standing on that storey. */
	let actZ = NaN, act = [];
	function activeDoors() {
		if ( Math.abs( B.z - actZ ) < 0.05 ) return act;
		actZ = B.z; act = [];
		for ( const L of LV ) if ( Math.abs( L.z - B.z ) < 1.2 ) for ( const D of L.doors ) act.push( D );
		return act;
	}
	function gatherNear( li, x, y ) {
		near = [];
		for ( const D of activeDoors() )
			if ( Math.abs( D.hx - x ) < D.w + 2.5 && Math.abs( D.hy - y ) < D.w + 2.5 ) { const sg = leafSeg( D ); sg.door = D; near.push( sg ); }
		for ( const lift of LIFTS ) for ( const st of lift.stops ) {
			if ( Math.abs( st.z - B.z ) >= 1.2 ) continue;
			if ( Math.abs( st.door[ 0 ][ 0 ] - x ) < 5 && Math.abs( st.door[ 0 ][ 1 ] - y ) < 5 ) liftDoorSegs( lift, st, near );
		}
	}
	function free( G, x, y, skip ) {
		let d = fieldAt( G, x, y );
		for ( const s of near ) {
			if ( skip && s.door === skip ) continue;
			const t = segDist( x, y, s[ 0 ], s[ 1 ], s[ 2 ], s[ 3 ] ) - WALK.LEAF_HALF;
			if ( t < d ) d = t;
		}
		return d;
	}

	/* ---------------------------------------------------- the body */
	const B = { li: 0, x: 0, y: 0, z: 0, vx: 0, vy: 0, h: 0, p: 0, ph: 0,
		bobY: 0, sway: 0, roll: 0, nod: 0, surf: null, lift: null, flatKey: null, roomKey: null,
		on: false };
	let last = null, lastLevel = null;

	function place( li, x, y, heading, zHint ) {
		B.li = li; B.x = x; B.y = y;
		const L = LV[ li ];
		manageFields( li );
		const f = surfAt( x, y, zHint != null ? zHint : L.z, 0.5, 0.5 );
		B.z = f ? f.z : L.z; B.surf = f ? f.s : null;
		if ( f && f.s.li !== li ) { B.li = f.s.li; manageFields( B.li ); }
		B.vx = B.vy = 0; B.ph = 0; B.bobY = B.sway = B.roll = B.nod = 0;
		if ( heading != null ) B.h = heading;
		B.p = 0; B.lift = null; B.on = true;
		for ( const l of LIFTS ) l.riding = false;
		settle();
		return snapshot( true );
	}
	/* Out of anything the body was put into: the nearest spot, spiralling
	 * out, where a body fits. Teleports land on authored points (a door's
	 * middle, a room's widest spot), which can be a shoulder too close. */
	function settle() {
		const G = ensureField( B.li );
		gatherNear( B.li, B.x, B.y );
		if ( free( G, B.x, B.y ) >= WALK.R && stand( B.x, B.y, B.z, G ) ) return true;
		for ( let r = 0.05; r < 1.5; r += 0.05 ) {
			const n = Math.ceil( r * 2 * Math.PI / 0.05 );
			let best = null, bd = - 1;
			for ( let k = 0; k < n; k ++ ) {
				const a = k / n * 2 * Math.PI, x = B.x + Math.cos( a ) * r, y = B.y + Math.sin( a ) * r;
				const d = free( G, x, y );
				if ( d >= WALK.R && d > bd ) {
					const f = stand( x, y, B.z, G );
					if ( f ) { bd = d; best = [ x, y, f ]; }
				}
			}
			if ( best ) { B.x = best[ 0 ]; B.y = best[ 1 ]; B.z = best[ 2 ].z; B.surf = best[ 2 ].s; return true; }
		}
		return false;
	}

	function walkPush( G ) {
		let d = free( G, B.x, B.y );
		for ( let s = 0; s < 4 && d < WALK.R; s ++ ) {
			const e = 0.03;
			const gx = free( G, B.x + e, B.y ) - free( G, B.x - e, B.y );
			const gy = free( G, B.x, B.y + e ) - free( G, B.x, B.y - e );
			const L = Math.hypot( gx, gy );
			if ( L < 1e-6 ) break;
			const st = Math.min( WALK.R - d, 0.05 );
			const nx = B.x + gx / L * st, ny = B.y + gy / L * st;
			const nd = free( G, nx, ny );
			if ( nd <= d + 1e-5 ) break;
			// a leaf may shove the body, but never into a wall's clearance
			if ( fieldAt( G, nx, ny ) < Math.min( WALK.R, fieldAt( G, B.x, B.y ) ) ) break;
			const f = stand( nx, ny, B.z, G );
			if ( ! f ) break;
			B.x = nx; B.y = ny; B.z = f.z; B.surf = f.s; d = nd;
		}
	}

	/* An open leaf standing in the way YIELDS to a body walking into it: it
	 * turns away from the body - further open, or back toward shut,
	 * whichever side the body is pushing from - until the body clears it or
	 * the leaf meets a wall, and then stays where it was pushed, as a door
	 * does. Without it a front door left standing open across a flat's hall
	 * is a plank nobody can get past, and the architect's swings do that:
	 * the entrance leaf of flat 79 opens in front of its bathroom door. A
	 * leaf still swinging is not pushed back - it pushes (walkPush). */
	function yieldLeaves( G, x, y ) {
		const L = { doors: activeDoors() };
		let moved = false;
		for ( const D of L.doors ) {
			if ( ! D.latched || D.v !== 0 || D.t <= 0 || D.blocked ) continue;
			if ( Math.abs( D.hx - x ) > D.w + 0.5 || Math.abs( D.hy - y ) > D.w + 0.5 ) continue;
			let sg = leafSeg( D );
			if ( segDist( x, y, sg[ 0 ], sg[ 1 ], sg[ 2 ], sg[ 3 ] ) - WALK.LEAF_HALF >= WALK.R ) continue;
			const side = ( sg[ 2 ] - sg[ 0 ] ) * ( y - sg[ 1 ] ) - ( sg[ 3 ] - sg[ 1 ] ) * ( x - sg[ 0 ] );
			const dirDeg = side > 0 ? - 1 : 1;     // turn the leaf away from the body
			const a0 = leafAngle( D );
			/* ...and not INTO another door's throat either: a leaf pushed round
			 * until its tip stands a hand's width short of the next door's
			 * opening shuts that door as surely as crossing it (flat 6's front
			 * leaf, pushed to 110 degrees, in front of its bathroom door). It
			 * may stay where it was drawn, but not come any nearer. */
			const others = L.doors.filter( E => E !== D && Math.abs( E.cx - D.hx ) < 2.5 && Math.abs( E.cy - D.hy ) < 2.5 );
			const tipNear = ( tx, ty ) => others.map( E => segDist( tx, ty, E.ax, E.ay, E.bx, E.by ) );
			const near0 = tipNear( sg[ 2 ], sg[ 3 ] );
			for ( let k = 1; k <= 120; k ++ ) {
				const a = a0 + dirDeg * k, t = ( a - D.shut ) / D.open;
				if ( t < 0.05 || t > 2 ) break;
				const ar = a * D2R, ca = Math.cos( ar ), sa = Math.sin( ar ), len = D.w - 0.008;
				let wall = false;
				for ( const f of [ 0.4, 0.7, 1 ] )
					if ( fieldAt( G, D.hx + ca * len * f, D.hy + sa * len * f ) < 0.03 ) { wall = true; break; }
				if ( wall ) break;
				const tx = D.hx + ca * len, ty = D.hy + sa * len;
				// ...nor across another door's opening, which is free floor to the field
				if ( others.some( E => segsCross( D.hx, D.hy, tx, ty, E.ax, E.ay, E.bx, E.by ) ) ) break;
				if ( tipNear( tx, ty ).some( ( d, k ) => d < WALK.R + 0.1 && d < near0[ k ] - 1e-3 ) ) break;
				if ( segDist( x, y, D.hx, D.hy, tx, ty ) - WALK.LEAF_HALF >= WALK.R + 0.005 ) {
					D.t = D.rest = t; D.max = Math.max( 1, t ); moved = true; LIVE.add( D ); break;
				}
			}
			/* A front door that will not turn any further away from a visitor
			 * inside the flat - it is against a wall, or in front of the next
			 * door - is pulled shut instead, the way anyone shuts their front
			 * door behind them: the spring takes it, and a leaf that meets the
			 * body steps it aside as it comes (doorsStep). Flats 6/27/132: the
			 * front leaf stands across the bathroom door. */
			if ( ! moved && D.kind === 'entrance' && D.latched && D.t > 0.5 && dirDeg * Math.sign( D.open ) > 0
				&& B.surf && B.surf.owner && B.surf.owner === D.owner ) {
				D.latched = false; D.rest = 1; D.max = 1; LIVE.add( D ); moved = true;
			}
		}
		if ( moved ) gatherNear( B.li, B.x, B.y );
		return moved;
	}

	/* The storeys a body at (x, y, z) on level li can see down or up a
	 * stairwell: both ends of every flight within 3 m, of its own storey or
	 * the one below. */
	function nearFlights( li, x, y, z ) {
		const out = [];
		for ( const k of [ li, li - 1 ] ) {
			if ( k < 0 ) continue;
			for ( const s of LV[ k ].surf ) {
				if ( s.kind !== 'stair' ) continue;
				const b = s.P.bb;
				if ( x > b[ 0 ] - 3 && x < b[ 2 ] + 3 && y > b[ 1 ] - 3 && y < b[ 3 ] + 3
					&& Math.abs( z - zOf( s, x, y ) ) < 3.4 ) {
					if ( s.from && LI.has( s.from ) ) out.push( s.from );
					if ( s.to && LI.has( s.to ) ) out.push( s.to );
				}
			}
		}
		return out;
	}
	function surfReady( s, x, y, z ) {
		if ( ! s || s.kind === 'street' ) return true;
		/* On a flight a body sees down and up the well: every storey it
		 * would then need has to be here before it takes the step - stepping
		 * along the flight it is already on included. */
		if ( s.kind === 'stair' || s.kind === 'half_landing' )
			return ready( s.level ) && ( ! s.from || ready( s.from ) ) && ( ! s.to || ready( s.to ) )
				&& nearFlights( s.li, x, y, z ).every( ready );
		if ( s === B.surf ) return true;
		return ready( s.level );
	}
	function walkTry( G, sx, sy ) {
		if ( free( G, B.x + sx, B.y + sy ) < WALK.R ) yieldLeaves( G, B.x + sx, B.y + sy );
		const d0 = free( G, B.x, B.y );
		const ok = ( x, y ) => {
			const d = free( G, x, y );
			if ( ! ( d >= WALK.R || d > d0 + 1e-4 ) ) return null;
			const f = stand( x, y, B.z, G );
			return f && surfReady( f.s, x, y, f.z ) ? f : null;
		};
		let f;
		if ( ( f = ok( B.x + sx, B.y + sy ) ) ) { B.x += sx; B.y += sy; }
		else if ( sx && ( f = ok( B.x + sx, B.y ) ) ) { B.x += sx; B.vy = 0; }
		else if ( sy && ( f = ok( B.x, B.y + sy ) ) ) { B.y += sy; B.vx = 0; }
		else { B.vx = B.vy = 0; return; }
		B.z = f.z; B.surf = f.s;
	}

	/* ---------------------------------------------------- doors, sprung */
	/* A FRONT door shuts behind the visitor. Room and balcony doors stay
	 * open (the old show flat's rule: a flat is photographed with them
	 * open, and doors shutting behind a visitor are rooms going dark one
	 * after another) - but a front door left open stands across the flat's
	 * hall, and in this plan often across the bathroom door next to it
	 * (flats 77, 79, 80 ...), and nobody leaves their front door open. It
	 * shuts once the body is clear of everything the leaf sweeps. */
	function frontDoorsClose() {
		for ( const D of activeDoors() ) {
			if ( D.kind !== 'entrance' || ! D.latched || D.v !== 0 ) continue;
			if ( Math.abs( D.hx - B.x ) > 3 || Math.abs( D.hy - B.y ) > 3 ) { D.latched = false; LIVE.add( D ); continue; }
			let clear = true;
			for ( let k = 0; k <= 8 && clear; k ++ ) {
				const a = ( D.shut + D.open * D.t * k / 8 ) * D2R;
				if ( segDist( B.x, B.y, D.hx, D.hy, D.hx + Math.cos( a ) * D.w, D.hy + Math.sin( a ) * D.w )
					< WALK.R + WALK.LEAF_HALF + 0.05 ) clear = false;
			}
			// ...and is not being walked at
			if ( clear && Math.hypot( B.vx, B.vy ) > 0.05 ) {
				const sp = Math.hypot( B.vx, B.vy );
				if ( raySeg( B.x, B.y, B.vx / sp, B.vy / sp, D.ax, D.ay, D.bx, D.by ) < WALK.DOOR_NEAR ) clear = false;
			}
			if ( clear ) { D.latched = false; D.rest = 1; D.max = 1; LIVE.add( D ); }
		}
	}

	function doorsStep( dt ) {
		let busy = false;
		// only the leaves something has happened to: 1,800 doors, a handful live
		for ( const D of LIVE ) {
			const want = D.latched ? D.rest : 0;
			if ( D.t === want && D.v === 0 ) { LIVE.delete( D ); continue; }
			{
				const a = ( want - D.t ) * WALK.DOOR_K - D.v * WALK.DOOR_C;
				const v1 = D.v + a * dt, t1 = Math.min( D.max, Math.max( 0, D.t + v1 * dt ) );
				/* A leaf swinging toward a body stops against it, as a door
				 * does, and goes on when the body has stepped round it -
				 * rather than sweeping through the visitor's head. */
				if ( Math.abs( D.z - B.z ) < 1.2 && ! LIFTS.some( l => l.riding ) && leafHits( D, t1 ) && ! stepAside( D, t1 ) ) {
					D.v = 0; D.blocked = true; continue;
				}
				D.blocked = false;
				D.v = v1; D.t += D.v * dt;
				if ( D.t >= D.max ) { D.t = D.max; D.v = 0; }
				if ( D.t < 0 ) { D.t = 0; D.v = 0; }
				if ( Math.abs( want - D.t ) < 1e-3 && Math.abs( D.v ) < 1e-3 ) { D.t = want; D.v = 0; }
				else busy = true;
			}
		}
		return busy;
	}
	/* A door opens when the body walks AT it: its path crosses the opening
	 * within DOOR_NEAR, or it is up against the leaf. */
	function doorsTrigger() {
		const sp = Math.hypot( B.vx, B.vy );
		const dx = sp > 0.05 ? B.vx / sp : 0, dy = sp > 0.05 ? B.vy / sp : 0;
		for ( const D of activeDoors() ) {
			if ( D.latched && D.rest >= 1 ) continue;
			if ( Math.abs( D.cx - B.x ) > 2.2 || Math.abs( D.cy - B.y ) > 2.2 ) continue;
			const ux = ( D.bx - D.ax ) / D.w * 0.1, uy = ( D.by - D.ay ) / D.w * 0.1;
			let hit = segDist( B.x, B.y, D.ax, D.ay, D.bx, D.by ) < WALK.R + 0.12;
			if ( ! hit && sp > 0.05 )
				hit = raySeg( B.x, B.y, dx, dy, D.ax - ux, D.ay - uy, D.bx + ux, D.by + uy ) < WALK.DOOR_NEAR;
			if ( hit ) {
				if ( ! D.latched ) emit( 'door', { id: D.id, node: D.node, level: D.level } );
				D.latched = true; D.rest = 1; D.max = Math.max( D.max, 1 ); LIVE.add( D );
			}
		}
	}

	/* ---------------------------------------------------- lifts */
	function inCab( lift ) {
		return inPoly( lift.cab, B.x, B.y ) && Math.abs( B.z - lift.z ) < 0.3;
	}
	function liftsStep( dt ) {
		let busy = false;
		const Lid = LV[ B.li ].id;
		for ( const l of LIFTS ) {
			const here = l.stops[ l.at ];
			const inside = ! l.riding && inCab( l );
			// called: the body is near a landing door on a floor the car is not at
			if ( ! B.lift && l.v === 0 && ! l.prof && l.target === l.at && here.level !== Lid ) {
				const st = l.stops.find( s => s.level === Lid && ! s.dead );
				if ( st && Math.abs( B.z - st.z ) < 1.0 ) {
					const mx = ( st.door[ 0 ][ 0 ] + st.door[ 1 ][ 0 ] ) / 2, my = ( st.door[ 0 ][ 1 ] + st.door[ 1 ][ 1 ] ) / 2;
					if ( Math.hypot( B.x - mx, B.y - my ) < WALK.LIFT_CALL ) { l.target = l.stops.indexOf( st ); l.call = l.target; }
				}
			}
			const travelling = l.target !== l.at;
			let wantOpen = false;
			// nobody is shut in the doors: a body in the doorway holds them
			if ( l.v === 0 && ! l.prof && Math.abs( B.z - here.z ) < 1.0 && ! l.riding
				&& segDist( B.x, B.y, here.door[ 0 ][ 0 ], here.door[ 0 ][ 1 ], here.door[ 1 ][ 0 ], here.door[ 1 ][ 1 ] ) < WALK.R + 0.06 )
				wantOpen = l.doorT > 0;
			if ( ! travelling && l.v === 0 ) {
				if ( inside ) wantOpen = true;
				else if ( here.level === Lid && Math.abs( B.z - here.z ) < 1.0 ) {
					const mx = ( here.door[ 0 ][ 0 ] + here.door[ 1 ][ 0 ] ) / 2, my = ( here.door[ 0 ][ 1 ] + here.door[ 1 ][ 1 ] ) / 2;
					wantOpen = Math.hypot( B.x - mx, B.y - my ) < WALK.LIFT_NEAR;
				}
			}
			// ...and not onto a storey that is not on screen yet: shut till it is
			if ( wantOpen && ! ready( here.level ) ) wantOpen = false;
			// a car that has just stopped levels before its doors part
			if ( ! travelling && l.wait > 0 ) { l.wait = Math.max( 0, l.wait - dt ); wantOpen = false; busy = true; }
			if ( wantOpen && l.doorT < 1 ) { l.doorT = Math.min( 1, l.doorT + dt / WALK.LIFT_DOOR_OPEN ); busy = true; }
			else if ( ! wantOpen && l.doorT > 0 ) { l.doorT = Math.max( 0, l.doorT - dt / WALK.LIFT_DOOR_SHUT ); busy = true; }
			// the call is answered: its lamp goes out as the doors start to part
			if ( l.call === l.at && ! travelling && l.doorT > 0 ) l.call = null;
			if ( travelling && l.doorT === 0 ) {
				// shut: go. The body rides if it is standing in the car
				if ( ! l.prof && l.v === 0 && B.lift === l ) l.riding = true;
				busy = true;
				if ( ! l.prof ) {
					// the brake lifts a moment after the doors meet
					l.wait += dt;
					if ( l.wait < WALK.LIFT_START ) continue;
					const goal = l.stops[ l.target ].z;
					l.prof = scurve( Math.abs( goal - l.z ), WALK.LIFT_V, WALK.LIFT_A, WALK.LIFT_J );
					l.prof.z0 = l.z; l.prof.s = Math.sign( goal - l.z ); l.prof.t = 0; l.wait = 0;
				}
				const P = l.prof, t1 = Math.min( P.T, P.t + dt );
				const [ d1, v1, a1 ] = P.at( t1 );
				const z1 = P.z0 + P.s * d1;
				/* A car with a visitor in it sees the shaft, and a shaft's
				 * walls are each storey's: it does not run into a storey that
				 * is not on screen - it waits, doors shut, a car's length short
				 * of it (the gate, as for a stair: "is the geometry HERE"). */
				if ( l.riding && ! shaftReady( z1 + P.s * Math.min( Math.abs( P.z0 + P.s * P.D - z1 ), 1.2 ) ) ) { l.v = 0; l.a = 0; continue; }
				P.t = t1;
				if ( t1 >= P.T ) {
					const goal = l.stops[ l.target ].z;
					l.z = goal; l.v = 0; l.a = 0; l.at = l.target; l.prof = null; l.wait = WALK.LIFT_LEVEL;
					if ( l.riding ) {
						l.riding = false;
						B.z = goal; B.li = LI.get( l.stops[ l.at ].level ); manageFields( B.li );
						const f = surfAt( B.x, B.y, goal, 0.05, 0.05 );
						B.surf = f ? f.s : null;
						emit( 'arrive', { id: l.id, level: l.stops[ l.at ].level } );
					}
				} else { l.z = z1; l.v = P.s * Math.max( v1, 1e-4 ); l.a = P.s * a1; }
			}
			if ( l.riding ) {
				B.z = l.z;
				// the storey the car is passing, for needLevels
				let li = 0;
				for ( let i = 0; i < LV.length; i ++ ) if ( LV[ i ].z <= l.z + 0.01 ) li = i;
				if ( li !== B.li ) { B.li = li; }
			}
		}
		return busy;
	}

	/* The storeys a car whose floor is at z can see of its shaft: the one it
	 * is in and the one over it. */
	function shaftLevels( z ) {
		const out = [];
		for ( let i = 0; i < LV.length; i ++ )
			if ( LV[ i ].z <= z + 0.01 && z < LV[ i ].z + ( LV[ i ].h || 3 ) + 0.01 ) { out.push( LV[ i ].id ); if ( LV[ i + 1 ] ) out.push( LV[ i + 1 ].id ); }
		return out;
	}
	const shaftReady = ( z ) => shaftLevels( z ).every( id => ready( id, 'shaft' ) );
	function liftGo( level ) {
		const l = B.lift;
		if ( ! l || l.v !== 0 || l.prof || l.riding ) return false;
		const k = l.stops.findIndex( s => s.level === level );
		if ( k < 0 || k === l.at || l.stops[ k ].dead ) return false;
		l.target = k;
		return true;
	}

	/* ---------------------------------------------------- where am I */
	function whereAmI() {
		const L = LV[ B.li ];
		let unit = null;
		const ow = B.surf && B.surf.owner;
		if ( ow ) unit = L.unitBy.get( ow ) || null;
		if ( ! unit && B.surf && ( B.surf.kind === 'flat' ) )
			unit = L.units.find( u => inPoly( u.P, B.x, B.y ) ) || null;
		let room = null;
		if ( unit ) for ( const r of unit.rooms ) if ( inPoly( r.P, B.x, B.y ) ) { room = r; break; }
		return { unit, room };
	}

	/* ---------------------------------------------------- one frame */
	const _in = { forward: 0, strafe: 0, turn: 0, run: false, look: null };
	function step( dt, input ) {
		if ( ! B.on ) return snapshot( false );
		const I = input || _in;
		const h0 = B.h, p0 = B.p, x0 = B.x, y0 = B.y, z0 = B.z;
		B.h += ( I.turn || 0 ) * WALK.TURN * dt + ( I.look ? I.look.yaw || 0 : 0 );
		B.p += I.look ? I.look.pitch || 0 : 0;
		B.p = Math.max( - WALK.PITCH_MAX, Math.min( WALK.PITCH_MAX, B.p ) );

		gatherNear( B.li, B.x, B.y );
		let busy = doorsStep( dt );
		busy = liftsStep( dt ) || busy;

		const riding = LIFTS.some( l => l.riding );
		const G = ensureField( B.li );
		if ( riding ) {
			B.vx = B.vy = 0;
			B.bobY = B.sway = B.roll = B.nod = 0;
		} else {
			gatherNear( B.li, B.x, B.y );
			walkPush( G );
			const f = I.forward || 0, r = I.strafe || 0;
			let tx = 0, ty = 0;
			if ( f || r ) {
				const ch = Math.cos( B.h ), sh = Math.sin( B.h );
				// right of heading h is h + 90 degrees in the (mirrored) plan
				const wx = ch * f - sh * r, wy = sh * f + ch * r;
				const len = Math.hypot( wx, wy ) || 1, sp = ( I.run ? WALK.RUN : WALK.V ) / len;
				tx = wx * sp; ty = wy * sp;
			}
			const k = 1 - Math.exp( - dt / ( ( f || r ) ? WALK.TAU_UP : WALK.TAU_DOWN ) );
			B.vx += ( tx - B.vx ) * k; B.vy += ( ty - B.vy ) * k;
			if ( Math.hypot( B.vx, B.vy ) < WALK.STILL ) B.vx = B.vy = 0;
			const dist = Math.hypot( B.vx, B.vy ) * dt;
			const n = Math.max( 1, Math.ceil( dist / ( WALK.CELL * 0.7 ) ) );
			for ( let s = 0; s < n; s ++ ) {
				walkTry( ensureField( B.li ), B.vx * dt / n, B.vy * dt / n );
				// standing on another storey's surface hands the body over to it
				if ( B.surf && B.surf.li !== B.li ) {
					B.li = B.surf.li; manageFields( B.li ); gatherNear( B.li, B.x, B.y );
				}
			}
			const sp = Math.hypot( B.vx, B.vy ), gait = Math.min( 1, sp / WALK.V );
			if ( gait < 0.01 ) B.bobY = B.sway = B.roll = B.nod = 0;
			else {
				B.ph += sp * dt / WALK.STEP;
				const p = B.ph * Math.PI * 2;
				B.bobY = - WALK.BOB * gait * Math.cos( p );
				B.sway = WALK.SWAY * gait * Math.sin( p * 0.5 );
				B.roll = - WALK.ROLL * gait * Math.sin( p * 0.5 );
				B.nod = WALK.NOD * gait * Math.cos( p );
			}
			doorsTrigger();
			frontDoorsClose();
			// in a car?
			const was = B.lift;
			B.lift = B.surf && B.surf.kind === 'lift' ? B.surf.lift : null;
			if ( B.lift && B.lift !== was ) {
				const l = B.lift;
				emit( 'lift', { id: l.id, core: l.core, stops: l.stops.filter( s => ! s.dead ).map( s => s.level ), at: l.stops[ l.at ].level } );
			} else if ( was && ! B.lift ) emit( 'liftExit', { id: was.id } );
		}
		const moved = B.h !== h0 || B.p !== p0 || B.x !== x0 || B.y !== y0 || B.z !== z0
			|| B.bobY !== 0;
		return snapshot( moved || busy );
	}

	/* ---------------------------------------------------- the state */
	function snapshot( moving ) {
		const L = LV[ B.li ];
		if ( lastLevel !== L.id ) { emit( 'level', { level: L.id, prev: lastLevel } ); lastLevel = L.id; }
		const { unit, room } = whereAmI();
		const fk = unit ? unit.token + '@' + L.id : null;
		if ( fk !== B.flatKey ) {
			B.flatKey = fk;
			emit( 'flat', { flat: unit && ! unit.office ? unit.n : null, office: unit && unit.office ? unit.n : null, level: L.id } );
		}
		const rk = room ? fk + ':' + room.i : null;
		if ( rk !== B.roomKey ) { B.roomKey = rk; if ( room ) emit( 'room', { room: { name: room.name, kind: room.kind, i: room.i } } ); }
		// head: sway is across the heading
		const rx = - Math.sin( B.h ), ry = Math.cos( B.h );
		const ex = B.x + rx * B.sway, ey = B.y + ry * B.sway, ez = B.z + WALK.EYE + B.bobY;
		const pp = B.p + B.nod, cp = Math.cos( pp );
		const eye = toWorld( ex, ey, ez );
		const target = toWorld( ex + Math.cos( B.h ) * cp, ey + Math.sin( B.h ) * cp, ez + Math.sin( pp ) );
		const onStair = !! B.surf && ( B.surf.kind === 'stair' || B.surf.kind === 'half_landing' );
		const need = new Set( [ L.id ] );
		const sees = new Set( [ L.id ] );       // what the body can see now (needLevels also asks ahead)
		const ride = LIFTS.find( l => l.riding );
		if ( ride ) {
			// the shaft where the car is, the stretch it is about to run into, and where it is going
			const s = Math.sign( ride.stops[ ride.target ].z - ride.z );
			for ( const id of shaftLevels( ride.z ) ) need.add( id );
			for ( const id of shaftLevels( ride.z + s * 3.4 ) ) need.add( id );
			need.add( ride.stops[ ride.target ].level );
		} else {
			for ( const id of nearFlights( B.li, B.x, B.y, B.z ) ) { need.add( id ); sees.add( id ); }
			/* ...and what the next step down a flight would see: the gate
			 * (surfReady) asks it of the flight's own storey, so it has to
			 * be asked for from here or the body would wait for ever. */
			if ( need.size > 1 && B.li > 0 ) for ( const id of nearFlights( B.li - 1, B.x, B.y, B.z ) ) need.add( id );
		}
		const doors = [];
		for ( const id of need ) {
			const Ll = LV[ LI.get( id ) ];
			if ( Ll ) for ( const D of Ll.doors ) if ( D.t > 0 ) {
				const a = leafAngle( D );
				doors.push( { id: D.id, node: D.node, level: D.level, angle: a, rotY: - a * D2R, t: D.t } );
			}
		}
		const lifts = LIFTS.map( l => {
			/* The car is AT its stop until it moves: a floor pressed sets
			 * `target` at once, but the doors still take LIFT_DOOR_SHUT to
			 * close. Testing `target === at` here reported them shut the
			 * moment a button was pressed, and the page drew both pairs
			 * slammed in one frame (user, 2026-11-25: "the lift's closing
			 * animation is no good"). */
			const st = l.v === 0 && ! l.prof ? l.stops[ l.at ] : null;
			// the storey the indicators name: the stop the car is nearest
			let near = 0;
			for ( let k = 1; k < l.stops.length; k ++ ) if ( Math.abs( l.stops[ k ].z - l.z ) < Math.abs( l.stops[ near ].z - l.z ) ) near = k;
			const dir = l.target === l.at ? 0 : Math.sign( l.stops[ l.target ].z - l.stops[ l.at ].z );
			return { id: l.id, core: l.core, shaft: l.shaft, car: l.car, z: l.z, v: l.v, a: l.a,
				doorOpen: st ? l.doorT : 0, level: st ? st.level : null,
				doorNode: st ? st.node : null, door: st ? st.door : null,
				shows: l.stops[ near ].level, dir, called: l.call == null ? null : l.stops[ l.call ].level };
		} );
		const inLift = B.lift ? { id: B.lift.id, riding: B.lift.riding,
			stops: B.lift.stops.filter( s => ! s.dead ).map( s => s.level ), at: B.lift.stops[ B.lift.at ].level,
			to: B.lift.stops[ B.lift.target ].level } : null;
		last = {
			pos: { plan: [ B.x, B.y, B.z ], world: toWorld( B.x, B.y, B.z ) },
			eye, target, roll: B.roll, near: WALK.NEAR, heading: B.h, pitch: B.p,
			level: L.id, onStair, surface: B.surf ? B.surf.kind : null, inLift,
			flat: unit && ! unit.office ? unit.n : null, office: unit && unit.office ? unit.n : null,
			room: room ? { name: room.name, kind: room.kind, i: room.i } : null,
			doors, lifts, needLevels: [ ...need ].sort( ( a, b ) => LI.get( a ) - LI.get( b ) ),
			seesLevels: [ ...sees ].sort( ( a, b ) => LI.get( a ) - LI.get( b ) ),
			moving: !! moving,
		};
		return last;
	}

	/* ---------------------------------------------------- teleports */
	function findUnit( n ) {
		n = String( n );
		for ( let li = 0; li < LV.length; li ++ ) for ( const u of LV[ li ].units )
			if ( ! u.office && u.n === n ) return { li, u };
		for ( let li = 0; li < LV.length; li ++ ) for ( const u of LV[ li ].units )
			if ( u.office && ( u.n === n || u.token === n ) ) return { li, u };
		return null;
	}
	function toFlat( n ) {
		const F = findUnit( n );
		if ( ! F ) return null;
		const d = F.u.doors.find( x => x.kind === 'entrance' ) || F.u.doors[ 0 ];
		const sh = d.shut * D2R, cx = d.hinge[ 0 ] + Math.cos( sh ) * d.w / 2, cy = d.hinge[ 1 ] + Math.sin( sh ) * d.w / 2;
		let nx = - Math.sin( sh ), ny = Math.cos( sh );
		if ( ! inPoly( F.u.P, cx + nx * 0.6, cy + ny * 0.6 ) ) { nx = - nx; ny = - ny; }
		return place( F.li, cx + nx * 0.75, cy + ny * 0.75, Math.atan2( ny, nx ) );
	}
	/* A room's widest spot - the cell inside it furthest from any wall - and
	 * the longest view across it from there. */
	function toRoom( n, i ) {
		const F = findUnit( n );
		if ( ! F ) return null;
		const r = F.u.rooms[ i ];
		if ( ! r ) return null;
		const p = roomSpot( F.li, r );
		if ( ! p ) return null;
		return place( F.li, p[ 0 ], p[ 1 ], p[ 2 ] );
	}
	function roomSpot( li, r ) {
		const G = ensureField( li ), b = r.P.bb;
		const cxm = ( b[ 0 ] + b[ 2 ] ) / 2, cym = ( b[ 1 ] + b[ 3 ] ) / 2;
		let best = null, bd = - 1;
		for ( let y = b[ 1 ]; y <= b[ 3 ]; y += 0.05 ) for ( let x = b[ 0 ]; x <= b[ 2 ]; x += 0.05 ) {
			if ( ! inPoly( r.P, x, y ) ) continue;
			const d = Math.min( fieldAt( G, x, y ), 0.9 ) - 1e-3 * Math.hypot( x - cxm, y - cym );
			if ( d > bd ) { bd = d; best = [ x, y ]; }
		}
		if ( ! best ) return null;
		return [ best[ 0 ], best[ 1 ], viewFrom( G, best[ 0 ], best[ 1 ], r.P ) ];
	}
	/* The way to face from a spot: down the longest free line ACROSS THE ROOM.
	 * The field has no door leaves in it, so the longest line through the
	 * whole flat was often the one out through a doorway - and from a
	 * bathroom that is a shut leaf half a metre away (build 3's tour).
	 * Counting only the part of a line that stays inside the room (and
	 * clear of walls) faces the room; the whole line's length breaks ties,
	 * so a view on through an open plan still wins between equals. */
	function viewFrom( G, x, y, P ) {
		let bh = 0, bs = - 1;
		for ( let k = 0; k < 48; k ++ ) {
			const a = k / 48 * 2 * Math.PI, ca = Math.cos( a ), sa = Math.sin( a );
			let l = 0, inside = 0, gone = false;
			while ( l < 12 && fieldAt( G, x + ca * l, y + sa * l ) > 0.05 ) {
				if ( ! gone && P && ! inPoly( P, x + ca * l, y + sa * l ) ) gone = true;
				if ( ! gone ) inside = l;
				l += 0.1;
			}
			const score = ( P ? inside : l ) + 0.05 * l;
			if ( score > bs ) { bs = score; bh = a; }
		}
		return bh;
	}
	/* For the host: how far a body at (x, y) on level `id` can see along
	 * `heading` (plan radians) before a wall, and the room-facing heading
	 * from there (`viewFrom`, within the room the spot is in). */
	function sight( id, x, y, heading ) {
		const li = LI.get( id );
		if ( li == null ) return null;
		const G = ensureField( li ), ca = Math.cos( heading ), sa = Math.sin( heading );
		let l = 0;
		while ( l < 12 && fieldAt( G, x + ca * l, y + sa * l ) > 0.05 ) l += 0.05;
		let room = null;
		for ( const u of LV[ li ].units ) if ( inPoly( u.P, x, y ) ) {
			for ( const r of u.rooms ) if ( inPoly( r.P, x, y ) ) { room = r; break; }
			break;
		}
		return { free: l, best: viewFrom( G, x, y, room ? room.P : null ) };
	}
	function toPortal( core ) {
		const L0 = LI.get( 'L00' );
		const s = LV[ L0 ].aprons.find( a => a.core === core && a.portal );
		if ( ! s ) return null;
		const p = s.portal;
		const mx = ( p.a[ 0 ] + p.b[ 0 ] ) / 2, my = ( p.a[ 1 ] + p.b[ 1 ] ) / 2;
		return place( L0, mx + p.normal[ 0 ] * 2.2, my + p.normal[ 1 ] * 2.2,
			Math.atan2( - p.normal[ 1 ], - p.normal[ 0 ] ) );
	}
	function enter( o ) {
		if ( o.portal ) return toPortal( o.portal );
		if ( o.flat != null && o.room != null ) return toRoom( o.flat, o.room );
		if ( o.flat != null ) return toFlat( o.flat );
		const li = LI.get( o.level );
		if ( li == null ) return null;
		const at = o.at || LV[ li ].bb.slice( 0, 2 );
		return place( li, at[ 0 ], at[ 1 ], o.heading != null ? o.heading : B.h, o.z );
	}

	function markDeadStops() {
		/* A stop whose landing door opens onto no floor - drawn on the side of
		 * the shaft that faces a stair flight, say - is not a stop: it is left
		 * out of the buttons and a car is never sent there. Read off the data,
		 * so a plan that is put right gets its stop back with no change here. */
		for ( const l of LIFTS ) for ( const st of l.stops ) {
			const li = LI.get( st.level );
			if ( li == null ) { st.dead = true; continue; }
			const [ a, b ] = st.door, mx = ( a[ 0 ] + b[ 0 ] ) / 2, my = ( a[ 1 ] + b[ 1 ] ) / 2;
			const ux = b[ 0 ] - a[ 0 ], uy = b[ 1 ] - a[ 1 ], ln = Math.hypot( ux, uy ) || 1;
			let nx = - uy / ln, ny = ux / ln;
			if ( inPoly( l.cab, mx + nx * 0.4, my + ny * 0.4 ) ) { nx = - nx; ny = - ny; }
			/* a floor within a riser of the stop, outside the doors, with
			 * nothing lower than a soffit over it (the flight over the halls) */
			let floor = false;
			for ( const d of [ 0.45, 0.7, 0.95 ] ) {
				const x = mx + nx * d, y = my + ny * d;
				const f = surfAt0( x, y, st.z, WALK.RISER, WALK.RISER );
				if ( ! f || f.s.kind === 'lift' || f.s.kind === 'sill' ) continue;
				let low = false;
				for ( let k = 0; k < zsN; k ++ ) if ( ZS[ k ] > f.z + WALK.RISER && ZS[ k ] < f.z + WALK.HEAD ) low = true;
				if ( ! low ) { floor = true; break; }
			}
			st.dead = ! floor;
		}
		for ( const l of LIFTS ) if ( l.stops[ l.at ].dead ) {
			// parked at a dead stop: it waits at the nearest live one instead
			const k = l.stops.findIndex( s => ! s.dead );
			if ( k >= 0 ) { l.at = l.target = k; l.z = l.stops[ k ].z; }
		}
	}
	markDeadStops();

	/* The host's own solids for a level - the furniture, as polygons in plan
	 * metres ({outline} or a ring) - replacing any it gave before. The field
	 * is built again the next time it is wanted; give them before the body
	 * goes there and that costs nothing anyone sees. */
	/* No piece may stand in a doorway: a footprint within a body's radius of
	 * a door's throat - the middle of the opening and a step either side of
	 * it - is left out of the collision (and returned, so the host can say
	 * so). The sheets draw a few that way: a walk-in shower straight behind a
	 * bathroom door, a bed and its nightstand across a bedroom's. A visitor
	 * brushes the edge of the bed rather than finding the room shut. */
	/* plan_meta nav.furn: {node, c [x, y], s [across, along], hd (deg), z
	 * [bottom, top] over the floor} (older builds: polygons or {poly}). A
	 * piece is solid if it stands in the body's band - its top over 0.4 m,
	 * its bottom under 1.4 m (a wall cupboard is not in the way of a body). */
	function navFurn( L ) {
		if ( L.navFurnC ) return L.navFurnC;
		const nf = L.src && ( L.src.nav.furn || L.src.nav.furniture || L.src.nav.furniture_solid );
		const polys = [];
		if ( Array.isArray( nf ) ) for ( const p of nf ) {
			if ( p && p.c && p.s ) {
				if ( p.z && ! ( p.z[ 1 ] > 0.4 && p.z[ 0 ] < 1.4 ) ) continue;
				const t = ( p.hd || 0 ) * D2R, fx = Math.cos( t ), fy = Math.sin( t ), w = p.s[ 0 ] / 2, d = p.s[ 1 ] / 2;
				polys.push( { node: p.node, outline: [ [ - w, - d ], [ w, - d ], [ w, d ], [ - w, d ] ].map( ( [ u, v ] ) =>
					[ p.c[ 0 ] - fy * u + fx * v, p.c[ 1 ] + fx * u + fy * v ] ) } );
			} else {
				const q = p && ( p.poly || p );
				if ( q && ( q.outline || Array.isArray( q ) ) ) polys.push( q.outline ? q : { outline: q } );
			}
		}
		L.navFurnC = doorways( L, polys );
		L.navFurnC.count = polys.length;
		return L.navFurnC;
	}
	function solids( id, polys ) {
		const li = LI.get( id );
		if ( li == null ) return null;
		const L = LV[ li ];
		/* the build's own footprints win: the host's would be the same pieces twice */
		if ( navFurn( L ).count ) return { kept: 0, dropped: [], build: navFurn( L ).kept.length };
		const { kept, dropped } = doorways( L, polys );
		L.extra = kept;
		L.ver ++;
		L.field = null;
		if ( B.on && Math.abs( li - B.li ) <= 1 ) manageFields( B.li );
		return { kept: kept.length, dropped };
	}
	function doorways( L, polys ) {
		const kept = [], dropped = [];
		const throats = [];
		for ( const D of L.doors ) {
			const ux = ( D.bx - D.ax ) / D.w, uy = ( D.by - D.ay ) / D.w;
			for ( const t of [ - 0.4, 0, 0.4 ] ) throats.push( [ D.cx - uy * t, D.cy + ux * t ] );
		}
		for ( const p of polys || [] ) {
			const P = polyOf( p.outline ? p : { outline: p } ), r = P.rings[ 0 ], b = P.bb;
			let bad = false;
			for ( const [ x, y ] of throats ) {
				if ( x < b[ 0 ] - 0.6 || x > b[ 2 ] + 0.6 || y < b[ 1 ] - 0.6 || y > b[ 3 ] + 0.6 ) continue;
				let d = inPoly( P, x, y ) ? 0 : Infinity;
				for ( let i = 0, j = r.length - 2; i < r.length && d > 0; j = i, i += 2 )
					d = Math.min( d, segDist( x, y, r[ j ], r[ j + 1 ], r[ i ], r[ i + 1 ] ) );
				if ( d < WALK.R + 0.03 ) { bad = true; break; }
			}
			if ( bad ) dropped.push( p.node || p ); else kept.push( P );
		}
		return { kept, dropped };
	}

	return {
		WALK, enter, toFlat, toRoom, toPortal, step, liftGo, solids, sight,
		/* the stops a car offers: every stop with a floor outside its doors */
		furnFromBuild: ( id ) => { const li = LI.get( id ); return li == null ? null : navFurn( LV[ li ] ); },
		stopsOf: ( id ) => { const l = LIFTS.find( x => x.id === id ); return l ? l.stops.filter( s => ! s.dead ).map( s => s.level ) : []; },
		deadStops: () => LIFTS.flatMap( l => l.stops.filter( s => s.dead ).map( s => l.id + '@' + s.level ) ),
		state: () => last,
		levels: () => LV.map( L => ( { id: L.id, z: L.z, h: L.h, bb: L.bb } ) ),
		field: ( id ) => ensureField( LI.get( id ) ),
		nav: ( id ) => LV[ LI.get( id ) ],
		stats: () => ( { fields: STATS, resident: LV.filter( L => L.field ).map( L => L.id ) } ),
		flats: () => LV.flatMap( ( L, li ) => L.units.map( u => ( { level: L.id, n: u.n, office: u.office,
			rooms: u.rooms.map( r => ( { name: r.name, kind: r.kind, i: r.i, area: polyArea( r.P ) } ) ) } ) ) ),
		/* For rigs and the bench, not for the page. */
		debug: { B, LV, LIFTS, DOORS, surfAt, stand: ( x, y, z, id ) => stand( x, y, z, ensureField( LI.get( id ) ) ),
			fieldAt, roomSpot: ( id, r ) => roomSpot( LI.get( id ), r ), inPoly, free: ( id, x, y ) => {
				gatherNear( LI.get( id ), x, y ); return free( ensureField( LI.get( id ) ), x, y ); },
			ensureField: ( id ) => ensureField( LI.get( id ) ), manageFields: ( id ) => manageFields( LI.get( id ) ) },
	};
}
