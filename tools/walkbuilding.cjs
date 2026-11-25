#!/usr/bin/env node
/* Walk the whole building, headless, with the real engine (web/walk.js).
 *
 *   node tools/walkbuilding.cjs engine [--break=<what>] [--only=flats|stairs|lifts|street] [--levels=L05,L06]
 *   node tools/walkbuilding.cjs shots  [outDir]
 *
 * ENGINE runs walk.js in node, fixed dt 1/60, and steers the body with the
 * same step() the page calls - nothing is teleported once a walk starts:
 *   flats   for every flat and office on every level: from the foot of its
 *           core's stair, along the corridor, through the entrance door and
 *           into every room and loggia, on a route A* finds on the level's
 *           own collision field (with every leaf standing open, so a route
 *           never runs through where a door will be)
 *   stairs  from each street portal up every flight to the stair head (the
 *           podium stair to the terrace), into each storey's corridor on the
 *           way, and back down and out into the street
 *   lifts   each car from L00 to every stop and out onto the landing
 *   street  every street door at grade, and the commercial floor's corners
 * After EVERY step: the body is a radius clear of every wall (static field),
 * it is standing on a surface, and its feet moved no more than a riser
 * (except riding a lift, where no more than the car's speed allows). Leaves
 * swinging into the body are counted separately (the push resolves them).
 *
 * --break proves each check can fail: R (the engine's body shrunk to 0.10
 * while the rig still asks for 0.24), jump (the feet are lifted 0.5 m in
 * one step every 500 steps), riser (the engine accepts a 3 m step),
 * doors (no door ever opens), lift (liftGo does nothing), fat (a 0.40 body
 * in both, which the narrow doors cannot pass).
 *
 * SHOTS drives web/walktest.html in headless Chrome through window.__walk
 * and writes the screenshots listed in SHOTS below.
 */
const fs = require( 'fs' ), path = require( 'path' ), os = require( 'os' );
const ROOT = path.join( __dirname, '..' );
const arg = ( k, d ) => { const a = process.argv.find( s => s.startsWith( '--' + k + '=' ) ); return a ? a.split( '=' )[ 1 ] : d; };
const MODE = process.argv[ 2 ] || 'engine';
const BREAK = arg( 'break', '' );
const ONLY = arg( 'only', '' );
const DT = 1 / 60;

function loadJSON( f, tries = 5 ) {
	for ( let i = 0; ; i ++ ) {
		try { return JSON.parse( fs.readFileSync( path.join( ROOT, f ) ) ); }
		catch ( e ) { if ( i >= tries ) throw e; Atomics.wait( new Int32Array( new SharedArrayBuffer( 4 ) ), 0, 0, 500 ); }
	}
}

/* The height of every furniture node of a level's GLB, off its accessors'
 * bounds (glTF keeps min/max even on Draco-compressed positions): the top
 * of the mesh over its foot, which is the node's origin. */
function furnHeights( rel ) {
	const out = new Map();
	let b;
	try { b = fs.readFileSync( path.join( ROOT, rel ) ); } catch ( e ) { return out; }
	const L = b.readUInt32LE( 12 ), j = JSON.parse( b.slice( 20, 20 + L ).toString() );
	for ( const n of j.nodes || [] ) {
		if ( n.mesh == null || ! n.name ) continue;
		let h = 0;
		for ( const p of j.meshes[ n.mesh ].primitives ) {
			const a = j.accessors[ p.attributes.POSITION ];
			if ( a && a.max ) h = Math.max( h, a.max[ 1 ] );
		}
		out.set( n.name, h * ( n.scale ? n.scale[ 1 ] : 1 ) );
	}
	return out;
}
const report0 = {};

/* ------------------------------------------------------------ the engine rig */
async function engine() {
	const { createWalker, WALK, furnitureSolids } = await import( path.join( ROOT, 'web/walk.js' ) );
	const pm = loadJSON( 'web/plan_meta.json' ), sm = loadJSON( 'web/scene_meta.json' );
	const R_CHECK = WALK.R, RISER_CHECK = WALK.RISER;
	if ( BREAK === 'R' ) WALK.R = 0.10;
	if ( BREAK === 'riser' ) WALK.RISER = 3.0;
	if ( BREAK === 'fat' ) WALK.R = 0.40;
	const R_PLAN = WALK.R;                      // what the planner asks room for
	const events = [];
	/* --break=terrace hands the engine a scene_meta without the terrace's
	 * footprints, while the check below still asks for them: it must FAIL. */
	const smW = BREAK === 'terrace' ? JSON.parse( JSON.stringify( sm ) ) : sm;
	if ( BREAK === 'terrace' && smW.site && smW.site.terrace ) delete smW.site.terrace.solids;
	const W = createWalker( { meta: smW, planMeta: pm, on: ( t, p ) => events.push( [ t, p ] ) } );
	const D = W.debug;
	/* The terrace's benches, cafe sets, pergolas and tubs (scene_meta
	 * site.terrace.solids, from the street file) are solid in the walk: the
	 * middle of every footprint must be inside a wall on the deck's level. */
	{
		const T = sm.site && sm.site.terrace;
		if ( T && Array.isArray( T.solids ) ) {
			const lv = W.levels().find( l => Math.abs( l.z - ( T.z ?? 4.8 ) ) < 0.05 );
			const F = lv && W.field( lv.id );
			const free = [];
			for ( const b of T.solids ) {
				const cx = ( b[ 0 ] + b[ 2 ] ) / 2, cy = ( b[ 1 ] + b[ 3 ] ) / 2;
				if ( ! F || D.fieldAt( F, cx, cy ) > 0.02 ) free.push( [ +cx.toFixed( 2 ), +cy.toFixed( 2 ) ] );
			}
			report0.terrace = { level: lv && lv.id, boxes: T.solids.length, solid: T.solids.length - free.length, free };
		}
	}
	/* The furniture, solid as the page makes it (web/walk.js furnitureSolids,
	 * pieces over 0.4 m): every bed, table and kitchen run of every flat is in
	 * the way of every route below. --furn=0 walks the empty building;
	 * --break=bigfurn grows every piece 0.35 m all round, which has to block
	 * doors and FAIL. */
	const FURN = arg( 'furn', '1' ) !== '0';
	report0.furniture = {};
	if ( FURN ) {
		const ix = loadJSON( 'web/interior/furn/index.json' );
		for ( const [ id, lv ] of Object.entries( ix.levels || {} ) ) {
			const hs = furnHeights( 'web/interior/furn/' + ( lv.file ? path.basename( lv.file ) : id + '.glb' ) );
			let polys = furnitureSolids( lv, p => hs.get( p.node ) );
			if ( BREAK === 'bigfurn' ) polys = polys.map( q => {
				const xs = q.outline.map( v => v[ 0 ] ), ys = q.outline.map( v => v[ 1 ] );
				const cx = ( Math.min( ...xs ) + Math.max( ...xs ) ) / 2, cy = ( Math.min( ...ys ) + Math.max( ...ys ) ) / 2;
				return { outline: q.outline.map( ( [ x, y ] ) => { const dx = x - cx, dy = y - cy, l = Math.hypot( dx, dy ) || 1;
					return [ x + dx / l * 0.5, y + dy / l * 0.5 ]; } ) };
			} );
			/* plan_meta's own nav.furn wins when the build wrote it (the
			 * engine then ignores these); --break=bigfurn needs the host's */
			if ( BREAK === 'bigfurn' ) for ( const L of pm.levels ) if ( L.id === id && L.nav ) delete L.nav.furn;
			const fb = W.furnFromBuild( id );
			const r = W.solids( id, polys );
			const from = r.build != null ? 'plan_meta nav.furn' : 'index.json + GLB heights';
			const kept = r.build != null ? fb.kept.length : r.kept, dropped = r.build != null ? fb.dropped : r.dropped;
			report0.furniture[ id ] = { from, solid: kept, in_a_doorway: dropped.length };
			( report0.furniture_in_doorways = report0.furniture_in_doorways || [] ).push( ...dropped.map( d => d.node || d ) );
		}
	}
	if ( BREAK === 'doors' ) for ( const d of D.DOORS.values() )
		Object.defineProperty( d, 'latched', { get: () => false, set: () => {} } );
	if ( BREAK === 'lift' ) W.liftGo = () => false;
	if ( BREAK === 'jump' ) {      // the feet jump half a metre every 500th step
		const st0 = W.step; let c = 0;
		W.step = ( dt, i ) => { const r = st0( dt, i ); if ( ++ c % 500 === 0 ) D.B.z += 0.5; return r; };
	}
	const rCheck = BREAK === 'fat' ? 0.40 : R_CHECK;

	const viol = { wall: [], riser: [], nofloor: [], leaf: 0, leafMax: 0 };
	let steps = 0, stepMs = 0, s = null;
	const stepT = [];
	function tick( input ) {
		const z0 = D.B.z, riding0 = D.LIFTS.some( l => l.riding );
		const t0 = performance.now();
		s = W.step( DT, input );
		const dtm = performance.now() - t0; stepMs += dtm; steps ++;
		if ( stepT.length < 2e6 ) stepT.push( dtm );
		const B = D.B, lvl = s.level;
		const riding = riding0 || D.LIFTS.some( l => l.riding );
		if ( ! riding ) {
			const d = D.fieldAt( W.field( lvl ), B.x, B.y );
			if ( d < rCheck - 0.006 && viol.wall.length < 50 ) viol.wall.push( { lvl, x: +B.x.toFixed( 3 ), y: +B.y.toFixed( 3 ), d: +d.toFixed( 3 ), ctx: ctxName } );
			const fr = D.free( lvl, B.x, B.y );
			if ( fr < rCheck - 0.01 ) {
				viol.leaf ++; viol.leafMax = Math.max( viol.leafMax, rCheck - fr );
				if ( process.env.WDEBUG ) {
					const Dn = W.nav( lvl ).doors.filter( d => Math.hypot( d.hx - B.x, d.hy - B.y ) < d.w + 0.4 ).map( d => `${d.kind}:${d.t.toFixed( 2 )}:${d.v.toFixed( 1 )}` ).join( ',' );
					viol.leafWhy = viol.leafWhy || {}; const k = Dn.replace( /:[-\d.]+/g, '' ) + ( Dn.includes( ':0.0' ) ? ' rest' : ' moving' );
					viol.leafWhy[ k ] = ( viol.leafWhy[ k ] || 0 ) + 1;
				}
			}
			if ( ! B.surf && viol.nofloor.length < 50 ) viol.nofloor.push( { lvl, x: B.x, y: B.y, ctx: ctxName } );
			if ( Math.abs( B.z - z0 ) > RISER_CHECK + 1e-6 && viol.riser.length < 50 )
				viol.riser.push( { lvl, x: +B.x.toFixed( 2 ), y: +B.y.toFixed( 2 ), dz: +( B.z - z0 ).toFixed( 3 ), ctx: ctxName } );
		} else if ( Math.abs( B.z - z0 ) > WALK.LIFT_V * DT + 0.01 && viol.riser.length < 50 )
			viol.riser.push( { lift: true, dz: B.z - z0, ctx: ctxName } );
		return s;
	}
	let ctxName = '';

	/* ---- a planner per level: the engine's own field, its own idea of
	 * where a body can stand, at floor height, with every leaf open */
	const planners = new Map();
	function planner( id, leaves = true ) {
		const pk = id + ( leaves ? '+leaves' : '' );
		if ( planners.has( pk ) ) return planners.get( pk );
		const L = W.nav( id ), F = W.field( id );
		const { nx, ny, cell, x0, y0 } = F;
		const ok = new Uint8Array( nx * ny );
		const need = ( R_PLAN + 0.015 ) / F.q;
		/* Leaves: the route goes round every leaf standing at its drawn 90
		 * degrees; where that leaves no way through (a front door open
		 * across a bathroom door) a second planner ignores the leaves and the
		 * body pushes them aside (walk.js yieldLeaves). */
		const open = [];
		// a hinge stays where it is whatever the leaf does: keep a body off it
		for ( const d of L.doors ) open.push( [ d.hx, d.hy, d.hx, d.hy ] );
		if ( leaves ) for ( const d of L.doors ) {
			const a = ( d.shut + d.open ) * Math.PI / 180;
			open.push( [ d.hx, d.hy, d.hx + Math.cos( a ) * d.w, d.hy + Math.sin( a ) * d.w ] );
		}
		const sd = ( px, py, s ) => {
			const vx = s[ 2 ] - s[ 0 ], vy = s[ 3 ] - s[ 1 ], l = vx * vx + vy * vy || 1e-12;
			let t = ( ( px - s[ 0 ] ) * vx + ( py - s[ 1 ] ) * vy ) / l; t = t < 0 ? 0 : t > 1 ? 1 : t;
			return Math.hypot( px - s[ 0 ] - vx * t, py - s[ 1 ] - vy * t );
		};
		for ( let j = 0; j < ny; j ++ ) for ( let i = 0; i < nx; i ++ ) {
			const k = j * nx + i;
			if ( F.d[ k ] < need ) continue;
			const x = x0 + ( i + 0.5 ) * cell, y = y0 + ( j + 0.5 ) * cell;
			let bad = false;
			for ( const s of open ) if ( Math.abs( s[ 0 ] - x ) < 1.5 && Math.abs( s[ 1 ] - y ) < 1.5
				&& sd( x, y, s ) < R_PLAN + 0.015 + WALK.LEAF_HALF ) { bad = true; break; }
			if ( bad ) continue;
			const f = D.stand( x, y, L.z, id );
			if ( ! f || Math.abs( f.z - L.z ) > 0.05 || f.s.kind === 'lift' || f.s.kind === 'stair' ) continue;
			ok[ k ] = 1;
		}
		const P = { id, L, F, ok, nx, ny, cell, x0, y0 };
		planners.set( pk, P );
		return P;
	}
	const cellOf = ( P, x, y ) => [ Math.floor( ( x - P.x0 ) / P.cell ), Math.floor( ( y - P.y0 ) / P.cell ) ];
	const ctr = ( P, i, j ) => [ P.x0 + ( i + 0.5 ) * P.cell, P.y0 + ( j + 0.5 ) * P.cell ];
	function nearestOk( P, x, y, maxR = 0.6, within ) {
		const [ ci, cj ] = cellOf( P, x, y ), rr = Math.ceil( maxR / P.cell );
		let best = null, bd = Infinity;
		for ( let j = cj - rr; j <= cj + rr; j ++ ) for ( let i = ci - rr; i <= ci + rr; i ++ ) {
			if ( i < 0 || j < 0 || i >= P.nx || j >= P.ny || ! P.ok[ j * P.nx + i ] ) continue;
			const [ cx, cy ] = ctr( P, i, j ), d = Math.hypot( cx - x, cy - y );
			if ( d < bd && ( ! within || within( cx, cy ) ) ) { bd = d; best = [ i, j ]; }
		}
		return best;
	}
	function astar( P, from, to ) {
		const { nx, ny, ok } = P, N = nx * ny;
		const a = nearestOk( P, from[ 0 ], from[ 1 ], 0.5 ), b = nearestOk( P, to[ 0 ], to[ 1 ], 0.5 );
		if ( ! a ) return { fail: 'start not standable' };
		if ( ! b ) return { fail: 'goal not standable' };
		const s0 = a[ 1 ] * nx + a[ 0 ], g0 = b[ 1 ] * nx + b[ 0 ];
		const g = new Float32Array( N ).fill( Infinity ), par = new Int32Array( N ).fill( - 1 );
		const heap = [], hk = [];
		const push = ( k, f ) => { heap.push( f ); hk.push( k ); let i = heap.length - 1;
			while ( i > 0 ) { const p = ( i - 1 ) >> 1; if ( heap[ p ] <= heap[ i ] ) break;
				[ heap[ p ], heap[ i ] ] = [ heap[ i ], heap[ p ] ]; [ hk[ p ], hk[ i ] ] = [ hk[ i ], hk[ p ] ]; i = p; } };
		const pop = () => { const k = hk[ 0 ]; const lf = heap.pop(), lk = hk.pop();
			if ( heap.length ) { heap[ 0 ] = lf; hk[ 0 ] = lk; let i = 0;
				for ( ;; ) { const l = 2 * i + 1, r = l + 1; let m = i;
					if ( l < heap.length && heap[ l ] < heap[ m ] ) m = l; if ( r < heap.length && heap[ r ] < heap[ m ] ) m = r;
					if ( m === i ) break; [ heap[ m ], heap[ i ] ] = [ heap[ i ], heap[ m ] ]; [ hk[ m ], hk[ i ] ] = [ hk[ i ], hk[ m ] ]; i = m; } }
			return k; };
		const bi = b[ 0 ], bj = b[ 1 ];
		const hh = ( i, j ) => { const dx = Math.abs( i - bi ), dy = Math.abs( j - bj ); return ( dx + dy ) + ( Math.SQRT2 - 2 ) * Math.min( dx, dy ); };
		g[ s0 ] = 0; push( s0, hh( a[ 0 ], a[ 1 ] ) );
		const closed = new Uint8Array( N );
		while ( heap.length ) {
			const k = pop();
			if ( closed[ k ] ) continue; closed[ k ] = 1;
			if ( k === g0 ) break;
			const i = k % nx, j = ( k - i ) / nx;
			for ( let dj = - 1; dj <= 1; dj ++ ) for ( let di = - 1; di <= 1; di ++ ) {
				if ( ! di && ! dj ) continue;
				const ii = i + di, jj = j + dj;
				if ( ii < 0 || jj < 0 || ii >= nx || jj >= ny ) continue;
				const kk = jj * nx + ii;
				if ( ! ok[ kk ] || closed[ kk ] ) continue;
				if ( di && dj && ( ! ok[ j * nx + ii ] || ! ok[ jj * nx + i ] ) ) continue;
				const ng = g[ k ] + ( di && dj ? Math.SQRT2 : 1 );
				if ( ng < g[ kk ] ) { g[ kk ] = ng; par[ kk ] = k; push( kk, ng + hh( ii, jj ) ); }
			}
		}
		if ( par[ g0 ] < 0 && g0 !== s0 ) return { fail: 'no route on the field' };
		const pts = [];
		for ( let k = g0; k >= 0; k = par[ k ] ) { const i = k % nx; pts.push( ctr( P, i, ( k - i ) / nx ) ); if ( k === s0 ) break; }
		pts.reverse();
		return { pts, len: g[ g0 ] * P.cell };
	}
	function los( P, a, b ) {
		const L = Math.hypot( b[ 0 ] - a[ 0 ], b[ 1 ] - a[ 1 ] ), n = Math.ceil( L / 0.03 );
		for ( let k = 0; k <= n; k ++ ) {
			const x = a[ 0 ] + ( b[ 0 ] - a[ 0 ] ) * k / n, y = a[ 1 ] + ( b[ 1 ] - a[ 1 ] ) * k / n;
			const [ i, j ] = cellOf( P, x, y );
			if ( i < 0 || j < 0 || i >= P.nx || j >= P.ny || ! P.ok[ j * P.nx + i ] ) return false;
		}
		return true;
	}
	const wrap = a => Math.atan2( Math.sin( a ), Math.cos( a ) );
	/* Steer the body along a route. A dense route (A* cells, with a planner
	 * P): pure pursuit - the nearest route point ahead of the body, then the
	 * furthest one within 1.2 m it can see. A sparse one (stair waypoints, no
	 * P): the next waypoint until within 0.25 m of it. */
	function follow( P, pts, maxS = 120 ) {
		let i = 0, best = - Infinity, since = 0;
		const end = pts[ pts.length - 1 ], n1 = pts.length - 1;
		const dist = ( k ) => Math.hypot( pts[ k ][ 0 ] - D.B.x, pts[ k ][ 1 ] - D.B.y );
		for ( let n = 0; n < maxS / DT; n ++ ) {
			const B = D.B;
			// a sparse route is done at its last waypoint, not at any point
			// that happens to lie over it (a stair's foot on the storey above)
			if ( Math.hypot( end[ 0 ] - B.x, end[ 1 ] - B.y ) < ( P ? 0.15 : 0.25 ) && ( P || i === n1 ) ) return { ok: true };
			let j;
			if ( P ) {
				let bd = dist( i );
				for ( let k = i + 1; k <= Math.min( n1, i + 60 ); k ++ ) { const d = dist( k ); if ( d < bd ) { bd = d; i = k; } }
				j = Math.min( n1, i + 1 );
				for ( let k = i + 1; k <= n1 && dist( k ) < 1.2; k ++ ) if ( los( P, [ B.x, B.y ], pts[ k ] ) ) j = k;
			} else {
				while ( i < n1 && dist( i ) < 0.25 ) i ++;
				j = i;
			}
			const aim = pts[ j ];
			const want = Math.atan2( aim[ 1 ] - B.y, aim[ 0 ] - B.x );
			const yaw = wrap( want - B.h );
			const dA = Math.hypot( aim[ 0 ] - B.x, aim[ 1 ] - B.y );
			tick( { forward: Math.abs( yaw ) > 1.2 ? 0 : 1, run: dA > 0.6, look: { yaw, pitch: 0 } } );
			const prog = i * 1000 - dist( i ) - ( P ? 0 : 0 );
			if ( prog > best + 0.02 ) { best = prog; since = 0; } else since += DT;
			if ( since > 4 ) {
				if ( process.env.WDEBUG ) {
					const Lv = W.nav( s.level );
					console.log( 'STUCK', D.B.x.toFixed( 3 ), D.B.y.toFixed( 3 ), 'v', D.B.vx.toFixed( 2 ), D.B.vy.toFixed( 2 ), 'i', i, pts.length, 'aim', aim,
						'field', D.fieldAt( W.field( s.level ), D.B.x, D.B.y ).toFixed( 3 ), 'free', D.free( s.level, D.B.x, D.B.y ).toFixed( 3 ),
						'freeAim', D.free( s.level, aim[ 0 ], aim[ 1 ] ).toFixed( 3 ),
						Lv.doors.filter( d => Math.hypot( d.cx - D.B.x, d.cy - D.B.y ) < 1.6 ).map( d => `${d.id} t${d.t.toFixed( 2 )} rest${d.rest.toFixed( 2 )} L${d.latched} shut${d.shut} open${d.open} h${d.hx},${d.hy}` ).join( ' | ' ) );
				}
				return { ok: false, why: `stuck at ${D.B.x.toFixed( 2 )},${D.B.y.toFixed( 2 )} z ${D.B.z.toFixed( 2 )} (${s.level} ${s.surface}) heading for ${aim[ 0 ].toFixed( 2 )},${aim[ 1 ].toFixed( 2 )}` };
			}
		}
		return { ok: false, why: 'timeout' };
	}
	function rest( n = 90 ) { for ( let k = 0; k < n; k ++ ) tick( {} ); }
	/* A* to `to` and walk it. A leaf that swings into the body can leave it
	 * on the far side of the plank from its route; a visitor would walk
	 * round, so the route is found again from where the body now is (at
	 * most four times). */
	function go( id, to, tag ) {
		let len = 0, why = '';
		for ( let k = 0; k < 5; k ++ ) {
			let P = planner( id, true );
			let r = astar( P, [ D.B.x, D.B.y ], to );
			if ( r.fail ) { P = planner( id, false ); r = astar( P, [ D.B.x, D.B.y ], to ); if ( ! r.fail ) pushes ++; }
			if ( r.fail ) return { ok: false, why: `${tag}: ${r.fail}` };
			if ( ! k ) len = r.len;
			const f = follow( P, r.pts );
			if ( f.ok ) { replans += k; return { ok: true, len }; }
			why = f.why;
		}
		return { ok: false, why: `${tag}: ${why}` };
	}
	let replans = 0, pushes = 0;

	const LVL = W.levels();
	const navLevel = id => pm.levels.find( l => l.id === id );
	const rampsOf = ( id, core ) => ( W.nav( id ).surf || [] ).filter( s => s.kind === 'stair' && s.core === core ).sort( ( a, b ) => a.flight - b.flight );
	const ends = ( s ) => {
		const r = s.ramp, b = s.P.bb, cx = ( b[ 0 ] + b[ 2 ] ) / 2, cy = ( b[ 1 ] + b[ 3 ] ) / 2, h = ( r.hi - r.lo ) / 2;
		return { bot: [ cx - r.ax * h, cy - r.ay * h ], top: [ cx + r.ax * h, cy + r.ay * h ], ax: [ r.ax, r.ay ] };
	};
	const foot = ( id, core ) => { const r = rampsOf( id, core )[ 0 ]; if ( ! r ) return null; const e = ends( r );
		return [ e.bot[ 0 ] - e.ax[ 0 ] * 0.55, e.bot[ 1 ] - e.ax[ 1 ] * 0.55, Math.atan2( e.ax[ 1 ], e.ax[ 0 ] ) ]; };
	const report = Object.assign( report0, { flats: {}, stairs: {}, lifts: {}, street: {}, unreachable: [] } );

	/* ================= flats */
	if ( ! ONLY || ONLY === 'flats' ) {
		let nFlats = 0, nRooms = 0, okRooms = 0, okFlats = 0, offices = 0;
		const levels = arg( 'levels', '' ) ? arg( 'levels' ).split( ',' ) : LVL.map( l => l.id );
		for ( const id of levels ) {
			const L = W.nav( id );
			if ( ! L.units.length ) continue;
			for ( const u of L.units ) {
				const tag = `${id} ${u.office ? 'office' : 'flat'} ${u.n}`;
				ctxName = tag;
				const ft = foot( id, u.core ) || foot( id, 'C1' );
				W.enter( { level: id, at: [ ft[ 0 ], ft[ 1 ] ], heading: ft[ 2 ] + Math.PI } );
				if ( u.office ) offices ++; else nFlats ++;
				const d = u.doors.find( x => x.kind === 'entrance' ) || u.doors[ 0 ];
				const sh = d.shut * Math.PI / 180, cx = d.hinge[ 0 ] + Math.cos( sh ) * d.w / 2, cy = d.hinge[ 1 ] + Math.sin( sh ) * d.w / 2;
				let nx = - Math.sin( sh ), ny = Math.cos( sh );
				if ( ! D.inPoly( u.P, cx + nx * 0.6, cy + ny * 0.6 ) ) { nx = - nx; ny = - ny; }
				let res = go( id, [ cx - nx * 0.6, cy - ny * 0.6 ], 'to the entrance' );
				if ( res.ok ) res = go( id, [ cx + nx * 0.6, cy + ny * 0.6 ], 'through the entrance' );
				const got = [];
				if ( ! res.ok ) {
					report.unreachable.push( { where: tag, what: 'entrance', why: res.why } );
				} else {
					const P = planner( id );
					for ( const r of u.rooms ) {
						nRooms ++;
						const sp = D.roomSpot( id, r );
						const c = sp && nearestOk( P, sp[ 0 ], sp[ 1 ], 3.0, ( x, y ) => D.inPoly( r.P, x, y ) );
						if ( ! c ) { report.unreachable.push( { where: tag, what: r.name + ' #' + r.i, why: 'no spot in the room a body fits (planner)' } ); continue; }
						const goal = ctr( P, c[ 0 ], c[ 1 ] );
						const g = go( id, goal, r.name );
						if ( g.ok && s.room && s.room.i === r.i && ( s.flat === u.n || s.office === u.n ) ) { okRooms ++; got.push( r.i ); }
						else report.unreachable.push( { where: tag, what: r.name + ' #' + r.i, why: g.ok ? `arrived but state says ${JSON.stringify( s.room )} flat ${s.flat}` : g.why } );
					}
					if ( got.length === u.rooms.length ) okFlats ++;
				}
			}
			process.stdout.write( `${id} ` );
		}
		report.flats = { flats: nFlats, offices, units_all_rooms: okFlats, rooms: nRooms, rooms_reached: okRooms };
		console.log( '\nflats', JSON.stringify( report.flats ) );
	}

	/* ================= stairs */
	if ( ! ONLY || ONLY === 'stairs' ) {
		for ( const core of [ 'C1', 'C2', 'C3', 'podium' ] ) {
			ctxName = 'stairs ' + core;
			const out = { up: [], corridors: [], down: false, street: false, why: null };
			report.stairs[ core ] = out;
			W.enter( { portal: core } );
			const fail = ( w ) => { out.why = w; };
			let id = 'L00';
			let r = go( 'L00', foot( 'L00', core ), 'portal to the stair' );
			if ( ! r.ok ) { fail( r.why ); continue; }
			// up
			const flights = [];
			for ( ;; ) {
				const fl = rampsOf( id, core );
				if ( fl.length < 2 ) break;
				const e1 = ends( fl[ 0 ] ), e2 = ends( fl[ 1 ] );
				const hl = W.nav( id ).surf.find( x => x.kind === 'half_landing' && x.core === core );
				const hb = hl.P.bb, hc = [ ( hb[ 0 ] + hb[ 2 ] ) / 2, ( hb[ 1 ] + hb[ 3 ] ) / 2 ];
				const wp = [ foot( id, core ), [ e1.bot[ 0 ] + e1.ax[ 0 ] * 0.3, e1.bot[ 1 ] + e1.ax[ 1 ] * 0.3 ],
					[ e1.top[ 0 ] - e1.ax[ 0 ] * 0.3, e1.top[ 1 ] - e1.ax[ 1 ] * 0.3 ], hc,
					[ e2.bot[ 0 ] + e2.ax[ 0 ] * 0.3, e2.bot[ 1 ] + e2.ax[ 1 ] * 0.3 ],
					[ e2.top[ 0 ] + e2.ax[ 0 ] * 0.7, e2.top[ 1 ] + e2.ax[ 1 ] * 0.7 ] ].map( p => [ p[ 0 ], p[ 1 ] ] );
				flights.push( { id, wp } );
				const f = follow( null, wp );
				const to = fl[ 1 ].to;
				if ( ! f.ok || s.level !== to ) { fail( `up from ${id}: ${f.why || 'arrived on ' + s.level + ' not ' + to}` ); break; }
				out.up.push( to );
				id = to;
				// the storey's corridor (or the terrace), and back to the stair
				const nav = W.nav( id );
				const walkK = nav.surf.filter( x => x.kind === 'corridor' || x.kind === 'terrace' );
				if ( walkK.length ) {
					const P = planner( id );
					const fb = foot( id, core ) || flights[ flights.length - 1 ].wp[ 5 ];
					// a corridor point 4-9 m from the stair
					let goal = null;
					for ( let rad = 4; rad < 12 && ! goal; rad += 1 ) for ( let a = 0; a < 2 * Math.PI && ! goal; a += 0.2 ) {
						const x = fb[ 0 ] + Math.cos( a ) * rad, y = fb[ 1 ] + Math.sin( a ) * rad;
						const c = cellOf( P, x, y );
						if ( c[ 0 ] < 0 || c[ 1 ] < 0 || c[ 0 ] >= P.nx || c[ 1 ] >= P.ny || ! P.ok[ c[ 1 ] * P.nx + c[ 0 ] ] ) continue;
						const sf = D.surfAt( x, y, nav.z, 0.1, 0.1 );
						if ( sf && ( sf.s.kind === 'corridor' || sf.s.kind === 'terrace' ) && astar( P, [ D.B.x, D.B.y ], [ x, y ] ).pts ) goal = [ x, y ];
					}
					if ( ! goal ) { fail( `${id}: no corridor point reachable from the stair` ); break; }
					r = go( id, goal, id + ' corridor' );
					if ( ! r.ok || s.surface !== D.surfAt( goal[ 0 ], goal[ 1 ], nav.z, 0.1, 0.1 ).s.kind ) { fail( r.why || 'corridor not reached' ); break; }
					out.corridors.push( id );
					// back to the stair: the next flight's foot, or (top of the
					// podium stair) the landing it arrived on
					const nf = foot( id, core ) || flights[ flights.length - 1 ].wp[ 5 ];
					r = go( id, nf, id + ' back to the stair' );
					if ( ! foot( id, core ) ) { if ( ! r.ok ) fail( r.why ); break; }
					if ( ! r.ok ) { fail( r.why ); break; }
				} else if ( ! foot( id, core ) ) {
					// the stair head: stand on it
					out.corridors.push( id + ' (head)' );
				}
			}
			if ( out.why ) continue;
			// down: every flight back, in reverse
			for ( const fl of flights.slice().reverse() ) {
				const wp = fl.wp.slice().reverse();
				const f = follow( null, wp );
				if ( ! f.ok || s.level !== fl.id ) { fail( `down to ${fl.id}: ${f.why || 'on ' + s.level}` ); break; }
			}
			if ( out.why ) continue;
			out.down = true;
			const ap = W.nav( 'L00' ).aprons.find( a => a.portal && a.core === core ).portal;
			const mx = ( ap.a[ 0 ] + ap.b[ 0 ] ) / 2, my = ( ap.a[ 1 ] + ap.b[ 1 ] ) / 2;
			r = go( 'L00', [ mx + ap.normal[ 0 ] * 1.8, my + ap.normal[ 1 ] * 1.8 ], 'out to the street' );
			out.street = r.ok && s.surface === 'street';
			if ( ! r.ok ) fail( r.why );
		}
		console.log( 'stairs', JSON.stringify( report.stairs ) );
	}

	/* ================= lifts */
	if ( ! ONLY || ONLY === 'lifts' ) {
		for ( const lift of D.LIFTS ) {
			ctxName = 'lift ' + lift.id;
			const out = { stops: [], fail: [] };
			report.lifts[ lift.id ] = out;
			W.enter( { portal: lift.core } );
			const outside = ( st ) => {
				const [ a, b ] = st.door, mx = ( a[ 0 ] + b[ 0 ] ) / 2, my = ( a[ 1 ] + b[ 1 ] ) / 2;
				const ux = b[ 0 ] - a[ 0 ], uy = b[ 1 ] - a[ 1 ], l = Math.hypot( ux, uy );
				let nx = - uy / l, ny = ux / l;
				if ( D.inPoly( lift.cab, mx + nx * 0.4, my + ny * 0.4 ) ) { nx = - nx; ny = - ny; }
				return { out: [ mx + nx * 0.9, my + ny * 0.9 ], mid: [ mx, my ], inn: [ mx - nx * 0.9, my - ny * 0.9 ] };
			};
			const cabC = [ ( lift.cab.bb[ 0 ] + lift.cab.bb[ 2 ] ) / 2, ( lift.cab.bb[ 1 ] + lift.cab.bb[ 3 ] ) / 2 ];
			/* Board at the lowest stop whose landing a body can reach (C1-2
			 * and C2-1 at L00 have their door drawn on the stair side). */
			let k0 = 0, st, o, r;
			for ( ; k0 < lift.stops.length; k0 ++ ) {
				st = lift.stops[ k0 ]; o = outside( st );
				if ( st.dead ) continue;        // the engine offers no such stop
				if ( k0 === 0 ) r = go( st.level, o.out, 'to the landing door at ' + st.level );
				else { W.enter( { level: st.level, at: o.out } ); r = { ok: Math.hypot( D.B.x - o.out[ 0 ], D.B.y - o.out[ 1 ] ) < 0.3 }; }
				if ( r.ok ) break;
				out.fail.push( 'no way to the landing door at ' + st.level + ( r.why ? ': ' + r.why : '' ) );
			}
			if ( ! r.ok ) continue;
			out.boarded = st.level;
			const board = () => {
				// wait for the car and its doors, then walk in
				for ( let k = 0; k < 60 * 40 && ! ( lift.at === lift.stops.indexOf( st ) && lift.doorT >= 1 && lift.v === 0 ); k ++ ) tick( { look: { yaw: 0, pitch: 0 } } );
				if ( lift.doorT < 1 ) return 'doors never opened at ' + st.level;
				const f = follow( null, [ o.mid, cabC ] );
				if ( ! f.ok ) return 'boarding: ' + f.why;
				if ( ! s.inLift || s.inLift.id !== lift.id ) return 'in the cab but no inLift';
				return null;
			};
			const order = lift.stops.map( ( x, k ) => k ).filter( k => k !== k0 && ! lift.stops[ k ].dead );
			/* ...and a stop the engine leaves out must be refused, not ridden */
			for ( const x of lift.stops ) if ( x.dead ) {
				out.dead = ( out.dead || [] ).concat( x.level );
				if ( W.stopsOf( lift.id ).includes( x.level ) ) out.fail.push( 'dead stop offered: ' + x.level );
			}
			for ( const k of order ) {
				const e = board();
				if ( e ) { out.fail.push( e ); break; }
				const target = lift.stops[ k ];
				const nEv = events.length;
				if ( ! W.liftGo( target.level ) ) { out.fail.push( 'liftGo refused ' + target.level ); break; }
				let arrived = false;
				for ( let n = 0; n < 60 * 60 && ! arrived; n ++ ) {
					tick( {} );
					arrived = events.slice( nEv ).some( ev => ev[ 0 ] === 'arrive' && ev[ 1 ].level === target.level );
				}
				if ( ! arrived ) { out.fail.push( 'never arrived at ' + target.level ); break; }
				if ( Math.abs( D.B.z - target.z ) > 1e-6 || s.level !== target.level ) { out.fail.push( `arrived z ${D.B.z} level ${s.level}` ); break; }
				st = target; o = outside( st );
				for ( let n = 0; n < 60 * 3 && lift.doorT < 1; n ++ ) tick( {} );
				if ( lift.doorT < 1 ) { out.fail.push( 'doors did not open at ' + st.level ); break; }
				if ( ! nearestOk( planner( st.level ), o.out[ 0 ], o.out[ 1 ], 0.3 ) ) {
					// the landing door is drawn where no body can stand outside it
					out.stops.push( `${st.level}:door faces no floor (${o.out.map( v => v.toFixed( 2 ) )})` );
					continue;
				}
				const f = follow( null, [ cabC, o.mid, o.out ] );
				const sf = s.surface;
				if ( ! f.ok ) { out.fail.push( `out at ${st.level}: ${f.why}` ); break; }
				out.stops.push( `${st.level}:${sf}` );
			}
		}
		console.log( 'lifts', JSON.stringify( report.lifts ) );
	}

	/* ================= street doors and the commercial floor */
	if ( ! ONLY || ONLY === 'street' ) {
		const L0 = W.nav( 'L00' ), P = planner( 'L00' );
		for ( const a of L0.aprons ) {
			const key = a.portal ? 'portal ' + a.core : a.streetDoor;
			ctxName = 'street ' + key;
			const b = a.P.bb, c = [ ( b[ 0 ] + b[ 2 ] ) / 2, ( b[ 1 ] + b[ 3 ] ) / 2 ];
			W.enter( { level: 'L00', at: c } );
			// walk to the widest spot of whatever the door leads into
			const inner = a.portal ? ( a.core === 'podium' || a.core === 'C3' ? 'hall' : 'hall' ) : 'commercial';
			let best = null, bd = - 1;
			for ( let j = 0; j < P.ny; j += 4 ) for ( let i = 0; i < P.nx; i += 4 ) {
				if ( ! P.ok[ j * P.nx + i ] ) continue;
				const [ x, y ] = ctr( P, i, j ), dd = Math.hypot( x - c[ 0 ], y - c[ 1 ] );
				if ( dd > 9 || dd < 3 ) continue;
				const sf = D.surfAt( x, y, 0, 0.1, 0.1 );
				if ( sf && sf.s.kind === inner && P.F.d[ j * P.nx + i ] > bd ) { bd = P.F.d[ j * P.nx + i ]; best = [ x, y ]; }
			}
			if ( ! best ) { report.street[ key ] = 'no ' + inner + ' floor within 9 m'; continue; }
			const r = go( 'L00', best, key );
			report.street[ key ] = r.ok && s.surface === inner ? 'in: ' + inner : ( r.why || 'on ' + s.surface );
		}
		// the commercial floor, corner to corner
		ctxName = 'commercial';
		const com = L0.surf.find( x => x.kind === 'commercial' ), cb = com.P.bb;
		const corners = [ [ cb[ 0 ] + 1, cb[ 1 ] + 1 ], [ cb[ 2 ] - 1, cb[ 1 ] + 1 ], [ cb[ 2 ] - 1, cb[ 3 ] - 1 ], [ cb[ 0 ] + 1, cb[ 3 ] - 1 ] ]
			.map( p => nearestOk( P, p[ 0 ], p[ 1 ], 6, ( x, y ) => D.inPoly( com.P, x, y ) ) ).filter( Boolean ).map( c => ctr( P, c[ 0 ], c[ 1 ] ) );
		W.enter( { level: 'L00', at: corners[ 0 ] } );
		report.street.commercial = corners.slice( 1 ).map( p => { const r = go( 'L00', p, 'commercial' ); return r.ok ? 'ok ' + r.len.toFixed( 0 ) + ' m' : r.why; } );
		console.log( 'street', JSON.stringify( report.street ) );
	}

	const st = W.stats();
	report.replans = replans;
	report.routes_through_leaves = pushes;
	report.step_us = +( stepMs / steps * 1000 ).toFixed( 1 );
	stepT.sort( ( a, b ) => a - b );
	const pc = q => +( stepT[ Math.min( stepT.length - 1, Math.floor( q * stepT.length ) ) ] * 1000 ).toFixed( 1 );
	// the mean carries the synchronous field builds (~30 ms, on a change of storey)
	report.step_us_pct = { p50: pc( 0.5 ), p90: pc( 0.9 ), p99: pc( 0.99 ), p999: pc( 0.999 ), max: pc( 1 ) };
	report.steps = steps;
	report.fields = st.fields;
	report.violations = viol;
	report.break = BREAK || null;
	/* What the plan data itself makes unreachable, found by this rig on
	 * plan_meta.json of 2026-11-24 and reported to the interior build. Only
	 * these are let through; anything else is a FAIL. */
	const KNOWN = [
		/* Empty: on plan_meta.json of 2026-11-24 19:56 every room of every
		 * flat and office is reached with the furniture in (L08 flat 129's
		 * made-up entrance was the last, put right by the interior build).
		 * Anything the data gets wrong again goes here, by name, and the
		 * line below prints it as stale the day it is put right. */
	];
	const KNOWN_LIFT = [
		/* Empty: C1-1's L09 door (into a flat) and the L00 landings of C1-2
		 * and C2-1 (onto the stair) were put right in the same build. A stop
		 * whose landing faces no floor is now left out by the engine itself
		 * (walk.js markDeadStops) and listed under known by the data. */
	];
	/* Stops the engine leaves out because their landing door faces no floor
	 * (walk.js markDeadStops) are data, and listed as such - by the data, not
	 * by name, so a plan put right drops off this list by itself. */
	for ( const d of W.deadStops() ) report.known = ( report.known || [] ).concat( { lift: d.split( '@' )[ 0 ], stop: d.split( '@' )[ 1 ], why: 'landing door faces no floor: not offered' } );
	report.known = ( report.known || [] ).concat( report.unreachable.filter( u => KNOWN.some( k => k( u ) ) ) );
	report.unreachable = report.unreachable.filter( u => ! KNOWN.some( k => k( u ) ) );
	for ( const [ id, o ] of Object.entries( report.lifts ) ) {
		report.known.push( ...o.fail.filter( f => KNOWN_LIFT.some( k => k( id, f ) ) ).map( f => ( { lift: id, why: f } ) ) );
		o.fail = o.fail.filter( f => ! KNOWN_LIFT.some( k => k( id, f ) ) );
		for ( const st of o.stops ) if ( ! /:corridor$/.test( st ) ) report.known.push( { lift: id, stop: st } );
	}
	/* a KNOWN entry nothing matched any more is stale: the data was put
	 * right, and the entry has to go (it is printed so it does) */
	report.known_stale = KNOWN.filter( k => ! report.known.some( u => u.where && k( u ) ) ).map( String )
		.concat( KNOWN_LIFT.filter( k => ! report.known.some( u => u.lift && u.why && k( u.lift, u.why ) ) ).map( String ) );
	const bad = viol.wall.length + viol.riser.length + viol.nofloor.length + report.unreachable.length
		+ Object.values( report.stairs ).filter( o => o.why || ! o.street ).length
		+ Object.values( report.lifts ).filter( o => o.fail.length ).length
		+ ( report.terrace && report.terrace.free.length ? 1 : 0 )
		+ ( report.flats.rooms != null && report.flats.rooms_reached + report.known.filter( k => k.where ).length !== report.flats.rooms ? 1 : 0 );
	report.verdict = bad ? 'FAIL' : 'PASS';
	const outF = arg( 'out', '' );
	if ( outF ) fs.writeFileSync( outF, JSON.stringify( report, null, 1 ) );
	console.log( 'known (plan data)', JSON.stringify( report.known ) );
	if ( report.known_stale.length ) console.log( 'KNOWN entries nothing matched (data fixed? remove them):', report.known_stale.join( ' | ' ) );
	console.log( 'furniture', JSON.stringify( report.furniture ), 'in doorways (not solid):', ( report.furniture_in_doorways || [] ).length );
	if ( report.terrace ) console.log( 'terrace', JSON.stringify( report.terrace ) );
	console.log( 'unreachable', report.unreachable.length, JSON.stringify( report.unreachable.slice( 0, 30 ), null, 0 ) );
	console.log( 'violations wall', viol.wall.length, 'riser', viol.riser.length, 'nofloor', viol.nofloor.length, 'leaf-in-body steps', viol.leaf, 'max', viol.leafMax.toFixed( 3 ) );
	if ( viol.wall.length ) console.log( ' wall e.g.', JSON.stringify( viol.wall.slice( 0, 4 ) ) );
	if ( viol.riser.length ) console.log( ' riser e.g.', JSON.stringify( viol.riser.slice( 0, 4 ) ) );
	if ( viol.leafWhy ) console.log( 'leaf why', JSON.stringify( viol.leafWhy ) );
	console.log( 'steps', steps, 'step() us mean', report.step_us, JSON.stringify( report.step_us_pct ) );
	console.log( report.verdict + ( BREAK ? ' (broken: ' + BREAK + ')' : '' ) );
	process.exitCode = bad ? 1 : 0;
}

/* ------------------------------------------------------------ the shots */
async function shots() {
	const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
	const outDir = process.argv[ 3 ] && ! process.argv[ 3 ].startsWith( '--' ) ? process.argv[ 3 ]
		: path.join( os.tmpdir(), 'walkshots' );
	fs.mkdirSync( outDir, { recursive: true } );
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1280,800', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-walk-' + process.pid ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1280, height: 800, deviceScaleFactor: 1 } );
	const errs = [];
	page.on( 'console', m => { const t = m.text(); if ( /error|failed|invalid/i.test( t ) ) errs.push( t.slice( 0, 200 ) ); } );
	page.on( 'pageerror', e => errs.push( String( e ).slice( 0, 200 ) ) );
	await page.goto( 'http://127.0.0.1:8777/walktest.html?rig=1', { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( 'window.__walk && window.__walk.ready', { timeout: 120000, polling: 100 } );
	const log = [];
	const shot = async ( name, script, ...args ) => {
		const r = await page.evaluate( script, ...args );
		await page.waitForFunction( 'window.__walk.loaded()', { timeout: 120000, polling: 100 } );
		const info = await page.evaluate( () => window.__walk.frame() );
		const f = path.join( outDir, name + '.png' );
		await page.screenshot( { path: f } );
		log.push( { name, r, info } );
		console.log( name, JSON.stringify( info ), r ? JSON.stringify( r ) : '' );
	};
	// every script returns a promise inside the page; __walk.* helpers step the engine
	await shot( '01_street_C1', () => window.__walk.go( { portal: 'C1' }, [] ) );
	await shot( '02_hall_C1', () => window.__walk.go( { portal: 'C1' }, [ [ 'walk', 3.2 ] ] ) );
	await shot( '03_flight_C1', () => window.__walk.stair( 'C1', 'L02', 0.5 ) );
	await shot( '04_halflanding_C1', () => window.__walk.stair( 'C1', 'L02', 'hl' ) );
	await shot( '05_lifts_L05_C1', () => window.__walk.lobby( 'C1-1', 'L05' ) );
	await shot( '06_corridor_L05', () => window.__walk.corridor( 'L05' ) );
	await shot( '07_flat90_door', () => window.__walk.flatDoor( '90' ) );
	const n90 = await page.evaluate( () => window.__walk.W.flats().find( f => f.n === '90' ).rooms.length );
	for ( let i = 0; i < n90; i ++ ) await shot( '08_flat90_room' + i, k => window.__walk.room( '90', k ), i );
	await shot( '09_loggia_out', () => window.__walk.loggiaOut( '90' ) );
	await shot( '10_lift_C2_ride', () => window.__walk.ride( 'C2-2', 'L10', 0.5 ) );
	await shot( '11_lift_C2_L10', () => window.__walk.ride( 'C2-2', 'L10', 1 ) );
	await shot( '12_core_C3', () => window.__walk.stair( 'C3', 'L04', 0.3 ) );
	await shot( '13_street_C3', () => window.__walk.go( { portal: 'C3' }, [ [ 'walk', 1.5 ] ] ) );
	await shot( '14_podium_stair', () => window.__walk.stair( 'podium', 'L00', 0.6 ) );
	await shot( '15_terrace', () => window.__walk.podiumTop() );
	fs.writeFileSync( path.join( outDir, 'shots.json' ), JSON.stringify( { log, errs }, null, 1 ) );
	console.log( errs.length ? 'ERRORS: ' + errs.slice( 0, 5 ).join( ' | ' ) : 'clean' );
	await browser.close();
}

( MODE === 'shots' ? shots() : engine() ).catch( e => { console.error( e ); process.exitCode = 2; } );
