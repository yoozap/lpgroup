#!/usr/bin/env node
/* Two walks through the REAL page, on foot, headless - with a picture at every
 * station and assertions that can fail.
 *
 *   node tools/tourcheck.cjs [--tour=A|B|AB] [--mbps=4] [--out=dir] [--lang=en] [--q='bwgate=0']
 *
 * Tour A  street -> "Entrance 1" (the hero's own link) -> up the C1 stair to
 *         floor 2 (L03) -> along the corridor -> into a flat -> every room ->
 *         its loggia -> back out of the flat, down the stair and out of the
 *         street door, where the walk hands back to the street's shot.
 * Tour B  "Entrance 2" -> the C2 lift (its stop buttons, clicked in the HUD)
 *         to floor 9 (L10) -> the corridor to the wing -> the wing's big end
 *         flat on the main street -> its loggia.
 *
 * The body is driven through the page's own walk (window.__bw.step: the
 * engine the keys drive, a fixed 1/60 s a step, three steps a frame), on
 * routes found on the engine's own collision field (A* in the page, every
 * leaf standing open; stairs by their flights' ends). Every animation frame
 * of the whole run asks the page whether the body is standing on a storey
 * that is not on screen (`__bw.hole()`: the flatwindow detector, for a body
 * instead of a floor view) and any such frame is a FAIL.
 *
 * At each station: the level the page's HUD names, the flat and the room,
 * the eye 1.60 over the floor, the body a radius clear of every wall, and a
 * screenshot to LOOK AT. Then: the console clean, the page idle (no frames
 * drawn) once the body stands still, bytes fetched over the tour, and the
 * frame's cost walking a furnished level against the street's (a batch of
 * pipeline.render() off the rAF path, as tools/fpsmax.cjs does - noise when
 * other Chromes are running, said so in the output).
 *
 * `--q=bwgate=0` tells the engine every level is here: it must FAIL (holes).
 *
 * THE LIGHT (build 4). Every station under a ceiling - a flat's rooms, the
 * corridors, the halls - is also a number: the mean luminance of the frame
 * right of the HUD (Rec.709 on the sRGB screenshot, 0..255) and its warmth
 * (mean R - B). A daylight interior with white walls and parquet must sit in
 * LUM_BAND and must not lean blue (WARM_MIN): the build-3 walk read 118-148
 * and R-B -9..-19 - the grey-navy wash - and fails here. `--base=` points the
 * rig at another server (an older build, to prove that). A room's picture is
 * taken only once the body has turned to its stance heading (checked), and
 * a stance that looks at a wall within 1.2 m is a failure.
 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const arg = ( k, d ) => { const a = process.argv.find( s => s.startsWith( '--' + k + '=' ) ); return a ? a.slice( k.length + 3 ) : d; };
const ROOT = path.join( __dirname, '..' );
const TOURS = arg( 'tour', 'AB' ).toUpperCase();
const MBPS = + arg( 'mbps', 0 );
const LANG = arg( 'lang', 'en' );
const Q = arg( 'q', '' );
const OUT = arg( 'out', path.join( ROOT, 'perf-shots', 'tourcheck' ) );
const BASE = arg( 'base', 'http://127.0.0.1:8777' );
const LUM_BAND = [ 145, 215 ], WARM_MIN = 0;
/* The C1 hall's station stands at the foot of the stair looking up it, and
 * half that frame is the treads' dark stone (materials.js int_stone_dark,
 * #3a3a3c - the owner's, not a lighting fault): its floor is lower. */
const LUM_STAIR = 105;
const W = 1600, H = 900;
const PROFILE = path.join( os.tmpdir(), 'lp-tourcheck' );

/* ------------------------------------------------ the in-page driver */
const LIB = String.raw`
window.__tour = ( () => {
	const bw = window.__bw;
	const Wk = () => bw.W, D = () => bw.W.debug, B = () => bw.W.debug.B;
	const R = 0.24, SPF = 3;
	const frame = () => new Promise( r => requestAnimationFrame( r ) );
	const S = { ticks: 0, hole: 0, holes: [], on: false, c0: 0, held: 0 };
	function sampler() {
		if ( ! S.on ) return;
		S.ticks ++;
		/* the longest time the frame loop was lent to a compile: a frozen picture */
		const now = performance.now();
		if ( window.__lv().compiling ) { if ( ! S.c0 ) S.c0 = now; S.held = Math.max( S.held, now - S.c0 ); } else S.c0 = 0;
		const h = bw.hole();
		if ( h ) { S.hole ++; if ( S.holes.length < 20 ) S.holes.push( h.join( ',' ) + ' @' + ( bw.s && bw.s.level ) + ' ' + ( bw.s && bw.s.surface ) ); }
		requestAnimationFrame( sampler );
	}
	const wrap = a => Math.atan2( Math.sin( a ), Math.cos( a ) );
	async function run( n, input ) { for ( let i = 0; i < n; i += SPF ) { bw.step( SPF, input || {} ); await frame(); } }
	async function settle( max = 600 ) { for ( let i = 0; i < max; i += SPF ) { const s = bw.step( SPF, {} ); await frame(); if ( s && ! s.moving ) return true; } return false; }

	/* A planner over a window of a level: cells a body fits in, standing on
	 * that level's floor, every leaf at its drawn open angle in the way. */
	function planner( id, a, b, leaves = true ) {
		const F = Wk().field( id ), L = Wk().nav( id );
		const pad = 7;
		const x0 = Math.max( F.x0, Math.min( a[ 0 ], b[ 0 ] ) - pad ), x1 = Math.min( F.x0 + F.nx * F.cell, Math.max( a[ 0 ], b[ 0 ] ) + pad );
		const y0 = Math.max( F.y0, Math.min( a[ 1 ], b[ 1 ] ) - pad ), y1 = Math.min( F.y0 + F.ny * F.cell, Math.max( a[ 1 ], b[ 1 ] ) + pad );
		const cell = 0.1, nx = Math.ceil( ( x1 - x0 ) / cell ), ny = Math.ceil( ( y1 - y0 ) / cell );
		const ok = new Uint8Array( nx * ny );
		const open = [];
		for ( const d of L.doors ) open.push( [ d.hx, d.hy, d.hx, d.hy ] );
		if ( leaves ) for ( const d of L.doors ) { const t = ( d.shut + d.open ) * Math.PI / 180; open.push( [ d.hx, d.hy, d.hx + Math.cos( t ) * d.w, d.hy + Math.sin( t ) * d.w ] ); }
		const sd = ( px, py, s ) => { const vx = s[ 2 ] - s[ 0 ], vy = s[ 3 ] - s[ 1 ], l = vx * vx + vy * vy || 1e-12;
			let t = ( ( px - s[ 0 ] ) * vx + ( py - s[ 1 ] ) * vy ) / l; t = t < 0 ? 0 : t > 1 ? 1 : t; return Math.hypot( px - s[ 0 ] - vx * t, py - s[ 1 ] - vy * t ); };
		for ( let j = 0; j < ny; j ++ ) for ( let i = 0; i < nx; i ++ ) {
			const x = x0 + ( i + 0.5 ) * cell, y = y0 + ( j + 0.5 ) * cell;
			if ( D().fieldAt( F, x, y ) < R + 0.03 ) continue;
			let bad = false;
			for ( const s of open ) if ( Math.abs( s[ 0 ] - x ) < 1.5 && Math.abs( s[ 1 ] - y ) < 1.5 && sd( x, y, s ) < R + 0.05 ) { bad = true; break; }
			if ( bad ) continue;
			const f = D().stand( x, y, L.z, id );
			if ( ! f || Math.abs( f.z - L.z ) > 0.05 || f.s.kind === 'lift' || f.s.kind === 'stair' ) continue;
			ok[ j * nx + i ] = 1;
		}
		return { id, ok, nx, ny, cell, x0, y0 };
	}
	function near( P, x, y, r = 0.6 ) {
		const ci = Math.floor( ( x - P.x0 ) / P.cell ), cj = Math.floor( ( y - P.y0 ) / P.cell ), rr = Math.ceil( r / P.cell );
		let best = null, bd = Infinity;
		for ( let j = cj - rr; j <= cj + rr; j ++ ) for ( let i = ci - rr; i <= ci + rr; i ++ ) {
			if ( i < 0 || j < 0 || i >= P.nx || j >= P.ny || ! P.ok[ j * P.nx + i ] ) continue;
			const d = Math.hypot( P.x0 + ( i + 0.5 ) * P.cell - x, P.y0 + ( j + 0.5 ) * P.cell - y );
			if ( d < bd ) { bd = d; best = [ i, j ]; }
		}
		return best;
	}
	function astar( P, from, to ) {
		const a = near( P, from[ 0 ], from[ 1 ] ), b = near( P, to[ 0 ], to[ 1 ] );
		if ( ! a ) return { fail: 'start not standable' };
		if ( ! b ) return { fail: 'goal not standable' };
		const { nx, ny, ok } = P, N = nx * ny, s0 = a[ 1 ] * nx + a[ 0 ], g0 = b[ 1 ] * nx + b[ 0 ];
		const g = new Float32Array( N ).fill( Infinity ), par = new Int32Array( N ).fill( - 1 ), closed = new Uint8Array( N );
		const hp = [], hk = [];
		const push = ( k, f ) => { hp.push( f ); hk.push( k ); let i = hp.length - 1; while ( i > 0 ) { const p = ( i - 1 ) >> 1; if ( hp[ p ] <= hp[ i ] ) break;
			[ hp[ p ], hp[ i ] ] = [ hp[ i ], hp[ p ] ]; [ hk[ p ], hk[ i ] ] = [ hk[ i ], hk[ p ] ]; i = p; } };
		const pop = () => { const k = hk[ 0 ], lf = hp.pop(), lk = hk.pop(); if ( hp.length ) { hp[ 0 ] = lf; hk[ 0 ] = lk; let i = 0;
			for ( ;; ) { const l = 2 * i + 1, r = l + 1; let m = i; if ( l < hp.length && hp[ l ] < hp[ m ] ) m = l; if ( r < hp.length && hp[ r ] < hp[ m ] ) m = r;
				if ( m === i ) break; [ hp[ m ], hp[ i ] ] = [ hp[ i ], hp[ m ] ]; [ hk[ m ], hk[ i ] ] = [ hk[ i ], hk[ m ] ]; i = m; } } return k; };
		const h = ( i, j ) => { const dx = Math.abs( i - b[ 0 ] ), dy = Math.abs( j - b[ 1 ] ); return dx + dy + ( Math.SQRT2 - 2 ) * Math.min( dx, dy ); };
		g[ s0 ] = 0; push( s0, h( a[ 0 ], a[ 1 ] ) );
		while ( hp.length ) {
			const k = pop(); if ( closed[ k ] ) continue; closed[ k ] = 1; if ( k === g0 ) break;
			const i = k % nx, j = ( k - i ) / nx;
			for ( let dj = - 1; dj <= 1; dj ++ ) for ( let di = - 1; di <= 1; di ++ ) {
				if ( ! di && ! dj ) continue; const ii = i + di, jj = j + dj;
				if ( ii < 0 || jj < 0 || ii >= nx || jj >= ny ) continue;
				const kk = jj * nx + ii; if ( ! ok[ kk ] || closed[ kk ] ) continue;
				if ( di && dj && ( ! ok[ j * nx + ii ] || ! ok[ jj * nx + i ] ) ) continue;
				const ng = g[ k ] + ( di && dj ? Math.SQRT2 : 1 );
				if ( ng < g[ kk ] ) { g[ kk ] = ng; par[ kk ] = k; push( kk, ng + h( ii, jj ) ); }
			}
		}
		if ( par[ g0 ] < 0 && g0 !== s0 ) return { fail: 'no route' };
		const pts = [];
		for ( let k = g0; k >= 0; k = par[ k ] ) { const i = k % nx; pts.push( [ P.x0 + ( i + 0.5 ) * P.cell, P.y0 + ( ( k - i ) / nx + 0.5 ) * P.cell ] ); if ( k === s0 ) break; }
		return { pts: pts.reverse() };
	}
	/* Follow a route: pure pursuit on a dense one, waypoint by waypoint on a
	 * sparse one. A body held at a threshold by the gate (its next storey
	 * not here yet) is waiting, not stuck: the watchdog only counts time in
	 * which every level the engine needs is on screen. */
	function los( P, a, b ) {
		const L = Math.hypot( b[ 0 ] - a[ 0 ], b[ 1 ] - a[ 1 ] ), n = Math.ceil( L / 0.04 );
		for ( let k = 0; k <= n; k ++ ) {
			const x = a[ 0 ] + ( b[ 0 ] - a[ 0 ] ) * k / n, y = a[ 1 ] + ( b[ 1 ] - a[ 1 ] ) * k / n;
			const i = Math.floor( ( x - P.x0 ) / P.cell ), j = Math.floor( ( y - P.y0 ) / P.cell );
			if ( i < 0 || j < 0 || i >= P.nx || j >= P.ny || ! P.ok[ j * P.nx + i ] ) return false;
		}
		return true;
	}
	async function follow( pts, dense, maxS = 120, P = null ) {
		let i = 0, best = - Infinity, since = 0;
		const n1 = pts.length - 1, end = pts[ n1 ];
		const dist = k => Math.hypot( pts[ k ][ 0 ] - B().x, pts[ k ][ 1 ] - B().y );
		for ( let t = 0; t < maxS * 60; t += SPF ) {
			if ( dist( n1 ) < ( dense ? 0.15 : 0.25 ) && ( dense || i === n1 ) ) return { ok: true };
			let j;
			if ( dense ) {
				let bd = dist( i );
				for ( let k = i + 1; k <= Math.min( n1, i + 40 ); k ++ ) { const d = dist( k ); if ( d < bd ) { bd = d; i = k; } }
				j = Math.min( n1, i + 1 );
				for ( let k = i + 1; k <= n1 && dist( k ) < 1.0; k ++ ) if ( ! P || los( P, [ B().x, B().y ], pts[ k ] ) ) j = k;
			} else { while ( i < n1 && dist( i ) < 0.25 ) i ++; j = i; }
			const aim = pts[ j ], yaw = wrap( Math.atan2( aim[ 1 ] - B().y, aim[ 0 ] - B().x ) - B().h );
			bw.step( SPF, { forward: Math.abs( yaw ) > 1.2 ? 0 : 1, run: dist( j ) > 0.6, look: { yaw, pitch: - B().p * 0.2 } } );
			await frame();
			const prog = i * 1000 - dist( i );
			const waiting = bw.s && ! bw.s.needLevels.every( id => bw.ready( id ) );
			if ( prog > best + 0.02 ) { best = prog; since = 0; } else if ( ! waiting ) since += SPF / 60;
			if ( since > 5 ) return { ok: false, why: 'stuck at ' + B().x.toFixed( 2 ) + ',' + B().y.toFixed( 2 ) + ' z ' + B().z.toFixed( 2 ) + ' ' + ( bw.s && bw.s.surface ) + ' aiming ' + aim.map( v => v.toFixed( 2 ) ) };
		}
		return { ok: false, why: 'timeout' };
	}
	/* A point half way along the route to 'to' (a corridor picture taken
	 * half way there, not at a straight-line midpoint inside some flat). */
	function routeMid( to ) {
		const id = bw.s.level, from = [ B().x, B().y ];
		let r = astar( planner( id, from, to, true ), from, to );
		if ( r.fail ) r = astar( planner( id, from, to, false ), from, to );
		return r.fail ? null : r.pts[ Math.floor( r.pts.length / 2 ) ];
	}
	async function goTo( to, tag ) {
		let why = '';
		for ( let k = 0; k < 4; k ++ ) {
			const id = bw.s.level, from = [ B().x, B().y ];
			let P = planner( id, from, to, true ), r = astar( P, from, to );
			if ( r.fail ) { P = planner( id, from, to, false ); r = astar( P, from, to ); }
			if ( r.fail ) return { ok: false, why: tag + ': ' + r.fail };
			const f = await follow( r.pts, true, 120, P );
			if ( f.ok ) return f;
			why = f.why;
		}
		return { ok: false, why: tag + ': ' + why };
	}
	async function face( h, pitch = 0 ) {
		bw.step( 1, { look: { yaw: wrap( h - B().h ), pitch: pitch - B().p } } );
		await frame(); await frame();
	}
	const flights = ( id, core ) => ( Wk().nav( id ).surf || [] ).filter( s => s.kind === 'stair' && s.core === core ).sort( ( a, b ) => a.flight - b.flight );
	const ends = ( s ) => { const r = s.ramp, b = s.P.bb, cx = ( b[ 0 ] + b[ 2 ] ) / 2, cy = ( b[ 1 ] + b[ 3 ] ) / 2, h = ( r.hi - r.lo ) / 2;
		return { bot: [ cx - r.ax * h, cy - r.ay * h ], top: [ cx + r.ax * h, cy + r.ay * h ], ax: [ r.ax, r.ay ] }; };
	function foot( id, core ) { const f = flights( id, core )[ 0 ]; if ( ! f ) return null; const e = ends( f );
		return [ e.bot[ 0 ] - e.ax[ 0 ] * 0.55, e.bot[ 1 ] - e.ax[ 1 ] * 0.55 ]; }
	function stairWp( id, core ) {
		const fl = flights( id, core ); if ( fl.length < 2 ) return null;
		const e1 = ends( fl[ 0 ] ), e2 = ends( fl[ 1 ] );
		const hl = Wk().nav( id ).surf.find( x => x.kind === 'half_landing' && x.core === core ), hb = hl.P.bb;
		return { to: fl[ 1 ].to, wp: [ foot( id, core ), [ e1.bot[ 0 ] + e1.ax[ 0 ] * 0.3, e1.bot[ 1 ] + e1.ax[ 1 ] * 0.3 ],
			[ e1.top[ 0 ] - e1.ax[ 0 ] * 0.3, e1.top[ 1 ] - e1.ax[ 1 ] * 0.3 ], [ ( hb[ 0 ] + hb[ 2 ] ) / 2, ( hb[ 1 ] + hb[ 3 ] ) / 2 ],
			[ e2.bot[ 0 ] + e2.ax[ 0 ] * 0.3, e2.bot[ 1 ] + e2.ax[ 1 ] * 0.3 ], [ e2.top[ 0 ] + e2.ax[ 0 ] * 0.7, e2.top[ 1 ] + e2.ax[ 1 ] * 0.7 ] ],
			mid: [ ( e1.bot[ 0 ] + e1.top[ 0 ] ) / 2, ( e1.bot[ 1 ] + e1.top[ 1 ] ) / 2 ], ax: e1.ax };
	}
	/* Up one storey on a core's stair: to its foot, then flight, landing,
	 * flight. 'half' stops on the first flight's middle (a picture). */
	async function climb( core, half = false ) {
		const id = bw.s.level, st = stairWp( id, core );
		if ( ! st ) return { ok: false, why: 'no flights of ' + core + ' on ' + id };
		// already on its first flight (a picture was taken half way up): on up
		const g = bw.s.onStair ? { ok: true } : await goTo( st.wp[ 0 ], 'to the foot of the ' + core + ' stair on ' + id );
		if ( ! g.ok ) return g;
		if ( half ) { const f = await follow( [ st.wp[ 0 ], st.mid ], false ); await face( Math.atan2( st.ax[ 1 ], st.ax[ 0 ] ), 0.12 ); await settle(); return f; }
		const f = await follow( st.wp.slice( 1 ), false );
		await settle();
		if ( ! f.ok ) return f;
		return bw.s.level === st.to ? { ok: true } : { ok: false, why: 'arrived on ' + bw.s.level + ' not ' + st.to };
	}
	async function descend( core ) {
		const id = bw.s.level, below = Wk().levels().map( l => l.id ), k = below.indexOf( id ) - 1;
		const lo = below[ k ], st = stairWp( lo, core );
		if ( ! st ) return { ok: false, why: 'no flights below ' + id };
		const g = await goTo( st.wp[ 5 ], 'to the head of the ' + core + ' stair on ' + id );
		if ( ! g.ok ) return g;
		const f = await follow( st.wp.slice( 0, 5 ).reverse(), false );
		await settle();
		if ( ! f.ok ) return f;
		return bw.s.level === lo ? { ok: true } : { ok: false, why: 'arrived on ' + bw.s.level + ' not ' + lo };
	}
	function unit( n ) {
		for ( const l of Wk().levels() ) { const N = Wk().nav( l.id ); const u = N && N.units.find( x => ! x.office && String( x.n ) === String( n ) ); if ( u ) return { level: l.id, u }; }
		return null;
	}
	function doorOf( u ) {
		const d = u.doors.find( x => x.kind === 'entrance' ) || u.doors[ 0 ], sh = d.shut * Math.PI / 180;
		const cx = d.hinge[ 0 ] + Math.cos( sh ) * d.w / 2, cy = d.hinge[ 1 ] + Math.sin( sh ) * d.w / 2;
		let nx = - Math.sin( sh ), ny = Math.cos( sh );
		if ( ! D().inPoly( u.P, cx + nx * 0.6, cy + ny * 0.6 ) ) { nx = - nx; ny = - ny; }
		return { out: [ cx - nx * 0.7, cy - ny * 0.7 ], in: [ cx + nx * 0.8, cy + ny * 0.8 ], n: [ nx, ny ] };
	}
	async function enterFlat( n ) {
		const U = unit( n ), d = doorOf( U.u );
		let r = await goTo( d.out, 'to the door of flat ' + n ); if ( ! r.ok ) return r;
		r = await goTo( d.in, 'through the door of flat ' + n ); if ( ! r.ok ) return r;
		await settle();
		return { ok: bw.s.flat === String( n ), why: 'inside? flat ' + bw.s.flat };
	}
	async function leaveFlat( n ) {
		const U = unit( n ), d = doorOf( U.u );
		let r = await goTo( d.in, 'back to the door of flat ' + n ); if ( ! r.ok ) return r;
		r = await goTo( d.out, 'out of flat ' + n ); await settle();
		return r.ok ? { ok: bw.s.flat == null, why: 'still in flat ' + bw.s.flat } : r;
	}
	async function room( n, i ) {
		const U = unit( n ), r = U.u.rooms[ i ];
		const sp = D().roomSpot( U.level, r );
		if ( ! sp ) return { ok: false, why: 'no spot in ' + r.name };
		const g = await goTo( [ sp[ 0 ], sp[ 1 ] ], r.name );
		if ( ! g.ok ) return g;
		await face( sp[ 2 ], - 0.12 ); await settle();
		/* the picture is taken facing the stance: the body must have turned,
		 * and what it faces must not be a wall at arm's length */
		const dh = Math.abs( wrap( B().h - sp[ 2 ] ) );
		const see = Wk().sight ? Wk().sight( U.level, B().x, B().y, B().h ) : null;
		const why = [];
		if ( dh > 0.05 ) why.push( 'not turned to the stance (' + dh.toFixed( 2 ) + ' rad off)' );
		if ( see && see.free < 1.2 ) why.push( 'faces a wall ' + see.free.toFixed( 2 ) + ' m away' );
		if ( ! ( bw.s.room && bw.s.room.i === i ) ) why.push( 'room says ' + JSON.stringify( bw.s.room ) );
		return { ok: ! why.length, why: why.join( '; ' ), facing: see ? + see.free.toFixed( 2 ) : null };
	}
	/* Out onto a loggia, and turned to look out over its rail. */
	async function loggia( n ) {
		const U = unit( n ), k = U.u.rooms.findIndex( r => r.kind === 'loggia' );
		if ( k < 0 ) return { ok: false, why: 'no loggia' };
		const r = await room( n, k );
		if ( ! r.ok ) return r;
		const ub = U.u.P.bb, rb = U.u.rooms[ k ].P.bb;
		await face( Math.atan2( ( rb[ 1 ] + rb[ 3 ] ) / 2 - ( ub[ 1 ] + ub[ 3 ] ) / 2, ( rb[ 0 ] + rb[ 2 ] ) / 2 - ( ub[ 0 ] + ub[ 2 ] ) / 2 ), - 0.06 );
		await settle();
		return { ok: true, i: k };
	}
	function landing( id, level ) {
		const l = D().LIFTS.find( x => x.id === id ), st = l.stops.find( s => s.level === level );
		const [ a, b ] = st.door, mx = ( a[ 0 ] + b[ 0 ] ) / 2, my = ( a[ 1 ] + b[ 1 ] ) / 2, ln = Math.hypot( b[ 0 ] - a[ 0 ], b[ 1 ] - a[ 1 ] );
		let nx = - ( b[ 1 ] - a[ 1 ] ) / ln, ny = ( b[ 0 ] - a[ 0 ] ) / ln;
		if ( D().inPoly( l.cab, mx + nx * 0.4, my + ny * 0.4 ) ) { nx = - nx; ny = - ny; }
		const cb = l.cab.bb;
		return { lift: l, out: [ mx + nx * 1.0, my + ny * 1.0 ], mid: [ mx, my ], cab: [ ( cb[ 0 ] + cb[ 2 ] ) / 2, ( cb[ 1 ] + cb[ 3 ] ) / 2 ], n: [ nx, ny ] };
	}
	async function boardLift( id ) {
		const Lg = landing( id, bw.s.level );
		let r = await goTo( Lg.out, 'to lift ' + id ); if ( ! r.ok ) return r;
		for ( let t = 0; t < 60 * 40 && ! ( Lg.lift.stops[ Lg.lift.at ].level === bw.s.level && Lg.lift.doorT >= 1 ); t += SPF ) await run( SPF, {} );
		if ( Lg.lift.doorT < 1 ) return { ok: false, why: 'doors never opened' };
		const f = await follow( [ Lg.mid, Lg.cab ], false ); await settle();
		await face( Math.atan2( Lg.n[ 1 ], Lg.n[ 0 ] ), 0 ); await settle( 120 );
		return f.ok && bw.s.inLift ? { ok: true } : { ok: false, why: 'not in the car: ' + ( f.why || '' ) };
	}
	async function rideWait( level, mid ) {
		const l = D().LIFTS.find( x => x.id === bw.s.inLift.id ), z1 = l.stops.find( s => s.level === level ).z;
		for ( let t = 0; t < 60 * 90; t += SPF ) {
			await run( SPF, {} );
			if ( mid && l.riding && Math.abs( l.z - z1 ) < Math.abs( z1 - l.stops[ 0 ].z ) * 0.5 ) return { ok: true, mid: true };
			if ( l.stops[ l.at ].level === level && l.v === 0 && l.doorT >= 1 ) return { ok: true };
		}
		return { ok: false, why: 'never arrived at ' + level };
	}
	async function leaveLift( level ) {
		const Lg = landing( bw.s.inLift ? bw.s.inLift.id : null, level );
		const f = await follow( [ Lg.mid, Lg.out ], false ); await settle();
		return f;
	}
	function status() {
		const s = bw.s; if ( ! s ) return null;
		return { level: s.level, flat: s.flat, office: s.office, room: s.room && s.room.name, surface: s.surface,
			z: s.pos.plan[ 2 ], eyeY: s.eye[ 1 ], footY: s.pos.world[ 1 ],
			free: D().free( s.level, B().x, B().y ), need: s.needLevels, shown: bw.shown, near: bw.near(),
			doors: s.doors.length, inLift: s.inLift, cut: bw.cut() };
	}
	return { S, start() { S.on = true; requestAnimationFrame( sampler ); }, stop() { S.on = false; },
		run, settle, goTo, routeMid, follow, face, climb, descend, enterFlat, leaveFlat, room, loggia, unit, foot, boardLift, rideWait, leaveLift, landing, status, doorOf };
} )();
`;

/* ------------------------------------------------ the rig */
( async () => {
	fs.mkdirSync( OUT, { recursive: true } );
	fs.rmSync( PROFILE, { recursive: true, force: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + PROFILE ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: 1 } );
	const cdp = await p.target().createCDPSession();
	await cdp.send( 'Network.enable' );
	if ( MBPS ) {
		await cdp.send( 'Network.setCacheDisabled', { cacheDisabled: true } );
		await cdp.send( 'Network.emulateNetworkConditions', { offline: false, latency: 40,
			downloadThroughput: MBPS * 1024 * 1024 / 8, uploadThroughput: MBPS * 1024 * 1024 / 8 } );
	}
	let bytes = 0, counting = false;
	const urls = new Map();
	cdp.on( 'Network.responseReceived', e => urls.set( e.requestId, e.response.url ) );
	const fetched = [];
	cdp.on( 'Network.loadingFinished', e => { if ( counting ) { bytes += e.encodedDataLength; fetched.push( [ ( urls.get( e.requestId ) || '' ).replace( /^.*\/web\//, '' ).replace( /^http:\/\/[^/]+\//, '' ), e.encodedDataLength ] ); } } );
	const cons = [];
	p.on( 'console', m => { const t = m.text();
		if ( ( m.type() === 'error' || /unmapped|invalid|failed|did not load/i.test( t ) ) && ! /404|facade-|photos\//.test( t ) ) cons.push( t.slice( 0, 240 ) ); } );
	p.on( 'pageerror', e => cons.push( 'PAGEERROR ' + String( e.stack || e ).slice( 0, 400 ) ) );
	const url = BASE + '/index.html?lang=' + LANG + ( Q ? '&' + Q : '' );
	await p.goto( url, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')", { timeout: 300000, polling: 100 } );
	await sleep( 2500 );
	await p.evaluate( LIB );

	const bad = [], log = [], lums = [];
	const say = ( s ) => { console.log( s ); log.push( s ); };
	const ev = ( f, ...a ) => p.evaluate( f, ...a );
	const until = async ( pred, ms = 60000 ) => { const t0 = Date.now(); while ( Date.now() - t0 < ms ) { if ( await p.evaluate( pred ) ) return true; await sleep( 150 ); } return false; };
	const hud = () => ev( () => ( { on: ! document.getElementById( 'walkhud' ).hidden,
		level: document.getElementById( 'wh-level' ).textContent, flat: document.getElementById( 'wh-flat' ).textContent,
		room: document.getElementById( 'wh-room' ).textContent,
		stops: [ ...document.querySelectorAll( '#wh-stops .wstop' ) ].map( b => b.textContent ) } ) );
	const levelName = ( id ) => id === 'L00' ? 'Ground floor' : id === 'L01' ? 'Offices' : id === 'ROOF' ? 'Roof' : `Floor ${ + id.slice( 1 ) - 1 } of 9`;
	let nShot = 0;
	/* One station: a picture and what has to be true there. */
	async function station( tag, want = {} ) {
		/* The frame the body stopped on, drawn and resolved: not while a
		 * compile holds the loop (a level arriving), and at least a few
		 * frames drawn after it. */
		await until( '!window.__lv().compiling', 20000 );
		const r0 = await ev( () => { window.LP.invalidate( 6 ); return window.__perf.rendered; } );
		await until( `window.__perf.rendered >= ${ r0 + 4 }`, 8000 );
		await sleep( 300 );
		const s = await ev( () => window.__tour.status() );
		const h = await hud();
		const name = String( ++ nShot ).padStart( 2, '0' ) + '_' + tag;
		const shot = await p.screenshot( { path: path.join( OUT, name + '.png' ) } );
		const errs = [];
		let lit = null;
		if ( want.lit ) {
			lit = await ev( async ( b64 ) => {
				const img = new Image(); img.src = 'data:image/png;base64,' + b64; await img.decode();
				const c = document.createElement( 'canvas' ); c.width = img.width; c.height = img.height;
				const g = c.getContext( '2d' ); g.drawImage( img, 0, 0 );
				const x0 = Math.round( img.width * 0.22 ), y0 = Math.round( img.height * 0.1 );
				const d = g.getImageData( x0, y0, img.width - x0, img.height - y0 ).data;
				let s = 0, rb = 0, n = 0;
				for ( let i = 0; i < d.length; i += 16 ) { s += 0.2126 * d[ i ] + 0.7152 * d[ i + 1 ] + 0.0722 * d[ i + 2 ]; rb += d[ i ] - d[ i + 2 ]; n ++; }
				return { mean: s / n, warm: rb / n };
			}, Buffer.from( shot ).toString( 'base64' ) );
			lums.push( [ tag, lit.mean, lit.warm ] );
			const lo = want.lit === 'stair' ? LUM_STAIR : LUM_BAND[ 0 ];
			if ( lit.mean < lo || lit.mean > LUM_BAND[ 1 ] ) errs.push( `luminance ${ lit.mean.toFixed( 1 ) } outside the daylight band ${ lo }..${ LUM_BAND[ 1 ] }` );
			if ( lit.warm < WARM_MIN ) errs.push( `a blue cast: R-B ${ lit.warm.toFixed( 1 ) }` );
		}
		if ( ! s ) errs.push( 'not walking' );
		else {
			const eye = s.eyeY - s.footY;
			if ( Math.abs( eye - 1.6 ) > 0.04 ) errs.push( `eye ${ eye.toFixed( 3 ) } over the floor` );
			if ( s.surface !== 'lift' && s.free < 0.23 ) errs.push( `only ${ s.free.toFixed( 3 ) } m clear of a wall` );
			if ( Math.abs( s.near - 0.1 ) > 1e-6 ) errs.push( 'near plane ' + s.near );
			if ( want.level && s.level !== want.level ) errs.push( `on ${ s.level }, wanted ${ want.level }` );
			if ( want.flat !== undefined && String( s.flat ) !== String( want.flat ) ) errs.push( `in flat ${ s.flat }, wanted ${ want.flat }` );
			if ( want.room && s.room !== want.room ) errs.push( `in "${ s.room }", wanted "${ want.room }"` );
			if ( ! h.on ) errs.push( 'the HUD is not up' );
			if ( LANG === 'en' && s.level && h.level !== levelName( s.level ) ) errs.push( `HUD says "${ h.level }" on ${ s.level }` );
			if ( LANG === 'en' && s.flat && h.flat !== 'Flat ' + s.flat ) errs.push( `HUD says "${ h.flat }" in flat ${ s.flat }` );
			if ( LANG === 'en' && s.room && h.room !== s.room && ! ( s.room === null ) ) errs.push( `HUD says room "${ h.room }", engine "${ s.room }"` );
			if ( s.cut.lv < 1e3 || s.cut.tower < 1e3 ) errs.push( 'a cut is down while walking' );
		}
		if ( want.stops && h.stops.length < 2 ) errs.push( 'no lift buttons in the HUD' );
		say( `  ${ name.padEnd( 30 ) } ${ lit ? `[lum ${ lit.mean.toFixed( 0 ) } R-B ${ lit.warm.toFixed( 0 ) }] ` : '' }${ s ? `${ s.level } ${ s.surface }${ s.flat ? ' flat ' + s.flat : '' }${ s.room ? ' "' + s.room + '"' : '' } eye ${ ( s.eyeY - s.footY ).toFixed( 2 ) } free ${ s.free.toFixed( 2 ) } shown ${ s.shown.join( ',' ) }` : '-' }  HUD "${ h.level } | ${ h.flat } | ${ h.room }"${ h.stops.length ? ' stops ' + h.stops.join( ' ' ) : '' }   ${ errs.length ? 'FAIL ' + errs.join( '; ' ) : 'ok' }` );
		for ( const e of errs ) bad.push( tag + ': ' + e );
		return s;
	}
	const must = ( r, what ) => { if ( ! r || ! r.ok ) { bad.push( what + ': ' + ( r && r.why ) ); say( '  FAIL ' + what + ': ' + ( r && r.why ) ); return false; } return true; };
	const T = ( f, ...a ) => ev( f, ...a );

	async function walkIn( k ) {
		// the hero's own link, as a visitor clicks it
		await ev( ( k ) => { scrollTo( 0, 0 ); document.querySelector( `[data-walkin="${ k }"]` ).click(); }, k );
		const ok = await until( '!!(window.__bw && window.__bw.on && !window.__lv().tweens)', 90000 );
		if ( ! ok ) { bad.push( 'entrance ' + k + ': the walk never started ' + await ev( () => JSON.stringify( { on: window.__bw.on, scene: window.LP.scene, lv: window.__lv(), cls: document.body.className } ) ) ); return false; }
		return true;
	}

	/* ================= tour A */
	if ( TOURS.includes( 'A' ) ) {
		say( '\nTOUR A  street -> Entrance 1 -> C1 stair to L03 -> a flat -> every room -> loggia -> out to the street' );
		counting = true; bytes = 0; fetched.length = 0;
		const t0 = Date.now();
		await ev( () => window.__tour.start() );
		const light0 = await ev( () => { if ( ! window.__bwLight ) return null; const L = window.__bwLight(); return JSON.stringify( [ L.t, L.env, L.hemi, L.exp, L.vign ] ); } );
		if ( await walkIn( 1 ) ) {
			await station( 'A_street_door_C1', { level: 'L00' } );
			const F = await ev( () => {
				const W = window.__bw.W, N = W.nav( 'L03' );
				const c = N.units.filter( u => ! u.office && u.core === 'C1' && u.rooms.some( r => r.kind === 'loggia' ) )
					.sort( ( a, b ) => b.rooms.length - a.rooms.length )[ 0 ];
				return c ? { n: c.n, rooms: c.rooms.map( r => ( { name: r.name, kind: r.kind } ) ) } : null;
			} );
			say( `  flat for tour A: ${ F && F.n } (${ F && F.rooms.map( r => r.name ).join( ', ' ) })` );
			let ok = must( await T( () => window.__tour.goTo( window.__tour.foot( 'L00', 'C1' ), 'hall to the stair' ) ), 'A hall' );
			if ( ok ) await station( 'A_hall_C1', { level: 'L00', lit: 'stair' } );
			if ( ok ) ok = must( await T( () => window.__tour.climb( 'C1' ) ), 'A up to L01' );
			if ( ok ) ok = must( await T( () => window.__tour.climb( 'C1', true ) ), 'A half flight L01' );
			if ( ok ) await station( 'A_on_the_stair_L01' );
			if ( ok ) ok = must( await T( () => window.__tour.climb( 'C1' ) ), 'A up to L02' );
			if ( ok ) ok = must( await T( () => window.__tour.climb( 'C1' ) ), 'A up to L03' );
			if ( ok ) await station( 'A_landing_L03', { level: 'L03' } );
			if ( ok && F ) {
				const d = await ev( ( n ) => window.__tour.doorOf( window.__tour.unit( n ).u ).out, F.n );
				ok = must( await T( ( d ) => window.__tour.goTo( d, 'corridor' ), d ), 'A corridor' );
				if ( ok ) await station( 'A_corridor_L03', { level: 'L03', flat: null, lit: true } );
				if ( ok ) ok = must( await T( ( n ) => window.__tour.enterFlat( n ), F.n ), 'A into flat ' + F.n );
				if ( ok ) await station( 'A_flat_' + F.n + '_door', { level: 'L03', flat: F.n, lit: true } );
				for ( let i = 0; ok && i < F.rooms.length; i ++ ) {
					if ( F.rooms[ i ].kind === 'loggia' ) continue;
					const r = await T( ( n, i ) => window.__tour.room( n, i ), F.n, i );
					if ( must( r, `A room ${ F.rooms[ i ].name }` ) ) await station( `A_${ F.n }_room${ i }`, { level: 'L03', flat: F.n, room: F.rooms[ i ].name, lit: true } );
				}
				/* Standing still: the page must go quiet - no frame drawn for
				 * two seconds - within ten (a few frames are owed after the
				 * body stops: the still frame's supersample, a level's
				 * furniture arriving behind the walk). */
				const tq = Date.now();
				let quiet = false, r0 = await ev( () => window.__perf.rendered ), drawn = 0;
				while ( Date.now() - tq < 12000 ) {
					await sleep( 2000 );
					const r1 = await ev( () => window.__perf.rendered );
					drawn = r1 - r0; r0 = r1;
					if ( drawn === 0 ) { quiet = true; break; }
				}
				say( `  idle standing in a room: ${ quiet ? 'no frame drawn for 2 s, ' + ( ( Date.now() - tq ) / 1000 ).toFixed( 0 ) + ' s after stopping' : 'STILL DRAWING (' + drawn + ' frames in the last 2 s)' }` );
				if ( ! quiet ) bad.push( 'A: the page never went idle standing still' );
				// ...and the HUD in Georgian, then back
				await ev( () => { const b = document.querySelector( '#lang button[data-lang="ka"]' ); if ( b ) b.click(); } );
				await sleep( 600 );
				await p.screenshot( { path: path.join( OUT, String( ++ nShot ).padStart( 2, '0' ) + '_A_hud_ka.png' ) } );
				const hk = await hud();
				say( `  HUD in Georgian: "${ hk.level } | ${ hk.flat } | ${ hk.room }"` );
				if ( ! /[ა-ჿ]/.test( hk.level + hk.room ) ) bad.push( 'A: the HUD did not turn Georgian' );
				await ev( () => { const b = document.querySelector( '#lang button[data-lang="en"]' ); if ( b ) b.click(); } );
				await sleep( 400 );
				const lg = ok && await T( ( n ) => window.__tour.loggia( n ), F.n );
				if ( ok && must( lg, 'A loggia' ) ) await station( `A_${ F.n }_loggia`, { level: 'L03', flat: F.n, room: 'Loggia' } );
				if ( ok ) ok = must( await T( ( n ) => window.__tour.leaveFlat( n ), F.n ), 'A out of the flat' );
				if ( ok ) await station( 'A_corridor_back', { level: 'L03', flat: null, lit: true } );
				for ( const lv of [ 'L02', 'L01', 'L00' ] ) if ( ok ) ok = must( await T( () => window.__tour.descend( 'C1' ) ), 'A down to ' + lv );
				if ( ok ) await station( 'A_hall_again', { level: 'L00' } );
				if ( ok ) {
					// out of the street door, and on down the pavement
					const out = await ev( () => { const p = window.__bw.W.nav( 'L00' ).aprons.find( a => a.portal && a.core === 'C1' ).portal;
						return [ ( p.a[ 0 ] + p.b[ 0 ] ) / 2 + p.normal[ 0 ] * 0.4, ( p.a[ 1 ] + p.b[ 1 ] ) / 2 + p.normal[ 1 ] * 0.4, p.normal[ 0 ], p.normal[ 1 ] ]; } );
					ok = must( await T( ( o ) => window.__tour.goTo( [ o[ 0 ], o[ 1 ] ], 'to the street door' ), out ), 'A to the door' );
					if ( ok ) await T( ( o ) => window.__tour.follow( [ [ o[ 0 ] + o[ 2 ] * 2.0, o[ 1 ] + o[ 3 ] * 2.0 ] ], false, 20 ), out );
					const back = await until( '!window.__bw.on && window.LP.scene === 1 && !window.__lv().tweens', 20000 );
					await sleep( 800 );
					await p.screenshot( { path: path.join( OUT, String( ++ nShot ).padStart( 2, '0' ) + '_A_back_on_the_street.png' ) } );
					say( `  out of the street door, back to the street's shot: ${ back ? 'yes' : 'NO' }` );
					if ( ! back ) bad.push( 'A: walking out of the street door did not hand back to the street' );
					/* ...and with the street's own light, to the bit: the room's
					 * light is the same uniforms at other values (app.js `bwLight`) */
					if ( light0 ) {
						await until( '!window.__bwLight() || window.__bwLight().t === 0', 5000 );
						const light1 = await ev( () => { const L = window.__bwLight(); return JSON.stringify( [ L.t, L.env, L.hemi, L.exp, L.vign ] ); } );
						say( `  the street's light after the walk: ${ light1 === light0 ? 'identical to before it' : 'DIFFERENT ' + light0 + ' -> ' + light1 }` );
						if ( light1 !== light0 ) bad.push( 'A: the street is not lit as it was before the walk' );
					}
				}
			}
		}
		counting = false;
		const S = await ev( () => ( { ticks: window.__tour.S.ticks, hole: window.__tour.S.hole, holes: window.__tour.S.holes, held: window.__tour.S.held } ) );
		say( `  tour A: ${ ( ( Date.now() - t0 ) / 1000 ).toFixed( 0 ) } s, ${ S.ticks } frames sampled, ${ S.hole } with a storey missing under the body${ S.hole ? ': ' + S.holes.slice( 0, 6 ).join( ' | ' ) : '' }; longest frame held by a compile ${ S.held.toFixed( 0 ) } ms` );
		if ( S.hole ) bad.push( `A: ${ S.hole } frames with a hole` );
		if ( S.ticks < 100 ) bad.push( 'A: the hole sampler hardly ran (vacuous)' );
		const by = {};
		for ( const [ u, n ] of fetched ) { const k = u.split( '?' )[ 0 ]; by[ k ] = ( by[ k ] || 0 ) + n; }
		say( `  bytes fetched during tour A: ${ ( bytes / 1024 ).toFixed( 0 ) } KB on the wire (${ Object.entries( by ).sort( ( a, b ) => b[ 1 ] - a[ 1 ] ).slice( 0, 12 ).map( ( [ k, v ] ) => k + ' ' + ( v / 1024 ).toFixed( 0 ) ).join( ', ' ) })` );
		await ev( () => { window.__tour.S.ticks = 0; window.__tour.S.hole = 0; window.__tour.S.holes.length = 0; window.__tour.S.held = 0; } );
	}

	/* ================= tour B */
	if ( TOURS.includes( 'B' ) ) {
		say( '\nTOUR B  Entrance 2 -> the C2 lift to floor 9 (L10) -> the corridor to the wing -> its big end flat -> loggia' );
		const t0 = Date.now();
		counting = true;
		await ev( () => { window.__tour.start(); } );
		if ( await ev( () => window.__bw.on ) ) await ev( () => window.LP.walkExit( 'street' ) ), await until( '!window.__lv().tweens', 20000 );
		if ( await walkIn( 2 ) ) {
			await station( 'B_street_door_C2', { level: 'L00' } );
			const lift = await ev( () => window.__bw.W.debug.LIFTS.filter( l => l.core === 'C2' && window.__bw.W.stopsOf( l.id ).includes( 'L00' ) ).map( l => l.id )[ 0 ] );
			const F = await ev( () => {
				const W = window.__bw.W, N = W.nav( 'L10' );
				const area = ( u ) => { const b = u.P.bb; return ( b[ 2 ] - b[ 0 ] ) * ( b[ 3 ] - b[ 1 ] ); };
				const c = N.units.filter( u => ! u.office && u.core === 'C3' && u.rooms.some( r => r.kind === 'loggia' ) ).sort( ( a, b ) => area( b ) - area( a ) )[ 0 ];
				return c ? { n: c.n, rooms: c.rooms.length } : null;
			} );
			say( `  lift ${ lift }; flat for tour B: ${ F && F.n }` );
			let ok = must( await T( ( id ) => window.__tour.boardLift( id ), lift ), 'B into the car' );
			if ( ok ) await station( 'B_in_the_car_L00', { level: 'L00', stops: true } );
			if ( ok ) {
				// the HUD's own button for floor 9, as a visitor presses it
				const pressed = await ev( () => { const b = [ ...document.querySelectorAll( '#wh-stops .wstop' ) ].find( x => x.textContent === '9' ); if ( b && ! b.disabled ) { b.click(); return true; } return false; } );
				if ( ! pressed ) { bad.push( 'B: no enabled "9" button in the lift' ); ok = false; }
			}
			if ( ok ) { ok = must( await T( () => window.__tour.rideWait( 'L10', true ) ), 'B riding' ); if ( ok ) await station( 'B_riding' ); }
			if ( ok ) ok = must( await T( () => window.__tour.rideWait( 'L10' ) ), 'B arrive at L10' );
			if ( ok ) await station( 'B_arrived_L10', { level: 'L10' } );
			if ( ok ) ok = must( await T( () => window.__tour.leaveLift( 'L10' ) ), 'B out of the car' );
			if ( ok && F ) {
				const d = await ev( ( n ) => window.__tour.doorOf( window.__tour.unit( n ).u ).out, F.n );
				// half way along, a picture of the corridor
				const mid = await ev( ( d ) => window.__tour.routeMid( d ), d );
				const m = await T( ( m ) => window.__tour.goTo( m, 'corridor, half way' ), mid );
				if ( m.ok ) { await T( ( d ) => { const B = window.__bw.W.debug.B; return window.__tour.face( Math.atan2( d[ 1 ] - B.y, d[ 0 ] - B.x ), 0 ); }, d );
					await station( 'B_corridor_L10', { level: 'L10', flat: null, lit: true } ); }
				ok = must( await T( ( d ) => window.__tour.goTo( d, 'wing corridor' ), d ), 'B corridor to the wing' );
				if ( ok ) await station( 'B_wing_door', { level: 'L10' } );
				if ( ok ) ok = must( await T( ( n ) => window.__tour.enterFlat( n ), F.n ), 'B into flat ' + F.n );
				if ( ok ) await station( 'B_flat_' + F.n, { level: 'L10', flat: F.n, lit: true } );
				// its living room, furnished as drawn
				const liv = ok && await ev( ( n ) => window.__tour.unit( n ).u.rooms.findIndex( r => /living/.test( r.kind || '' ) ), F.n );
				if ( ok && liv >= 0 ) {
					const rr = await T( ( n, i ) => window.__tour.room( n, i ), F.n, liv );
					if ( must( rr, 'B living room' ) ) await station( `B_${ F.n }_living`, { level: 'L10', flat: F.n, lit: true } );
				}
				const lg = ok && await T( ( n ) => window.__tour.loggia( n ), F.n );
				if ( ok && must( lg, 'B loggia' ) ) await station( `B_${ F.n }_loggia`, { level: 'L10', flat: F.n, room: 'Loggia' } );
			}
		}
		counting = false;
		const S = await ev( () => ( { ticks: window.__tour.S.ticks, hole: window.__tour.S.hole, holes: window.__tour.S.holes, held: window.__tour.S.held } ) );
		say( `  tour B: ${ ( ( Date.now() - t0 ) / 1000 ).toFixed( 0 ) } s, ${ S.ticks } frames sampled, ${ S.hole } with a storey missing under the body${ S.hole ? ': ' + S.holes.slice( 0, 6 ).join( ' | ' ) : '' }; longest frame held by a compile ${ S.held.toFixed( 0 ) } ms` );
		if ( S.hole ) bad.push( `B: ${ S.hole } frames with a hole` );
		if ( S.ticks < 100 ) bad.push( 'B: the hole sampler hardly ran (vacuous)' );

		/* The frame's cost: standing in the furnished flat, then on the street. */
		if ( await ev( () => window.__bw.on ) ) {
			const batch = () => ev( async () => {
				const R = window.__renderer, P = window.__parts.pipeline, nf = R._nodes && R._nodes.nodeFrame, dev = R.backend && R.backend.device;
				const pr = R.getPixelRatio();
				for ( let i = 0; i < 3; i ++ ) { nf.update(); P.render(); }
				await dev.queue.onSubmittedWorkDone();
				const t0 = performance.now();
				for ( let i = 0; i < 30; i ++ ) { nf.update(); P.render(); }
				await dev.queue.onSubmittedWorkDone();
				return { ms: ( performance.now() - t0 ) / 30, draws: R.info.render.drawCalls, tris: R.info.render.triangles, pr };
			} );
			const pin = ( r ) => ev( ( r ) => { const R = window.__renderer; R.setPixelRatio( r ); R.setSize( innerWidth, innerHeight, false ); }, r );
			await pin( 1 );
			const wa = await batch(), wb = await batch();
			await ev( () => window.LP.walkExit( 'street' ) );
			await until( '!window.__lv().tweens && window.LP.scene === 1', 20000 );
			await sleep( 1500 );
			await pin( 1 );
			const sa = await batch(), sb = await batch();
			const w = wa.ms < wb.ms ? wa : wb, st = sa.ms < sb.ms ? sa : sb;
			say( `\n  frame cost at 1600x900 @1 (1.44 Mpx), best of two batches of 30, off the rAF path:` );
			say( `    walking, furnished L10 flat: ${ w.ms.toFixed( 1 ) } ms  ${ w.draws } draws  ${ ( w.tris / 1e6 ).toFixed( 2 ) } M tris` );
			say( `    the street (rail):           ${ st.ms.toFixed( 1 ) } ms  ${ st.draws } draws  ${ ( st.tris / 1e6 ).toFixed( 2 ) } M tris` );
			const load = require( 'os' ).loadavg()[ 0 ];
			say( `    load average ${ load.toFixed( 1 ) }${ load > 2 ? ' - other work on the machine: treat these as NOISE' : '' }` );
			await ev( () => dispatchEvent( new Event( 'resize' ) ) );
		}
	}

	if ( lums.length ) say( `\n  light under a ceiling (band ${ LUM_BAND.join( '..' ) }, R-B >= ${ WARM_MIN }): `
		+ lums.map( ( [ t, m, w ] ) => `${ t } ${ m.toFixed( 0 ) }/${ w.toFixed( 0 ) }` ).join( ', ' ) );
	if ( cons.length ) { say( 'console:\n  ' + [ ...new Set( cons ) ].join( '\n  ' ) ); bad.push( 'console not clean' ); }
	say( bad.length ? `\nFAIL (${ bad.length })\n  ` + bad.join( '\n  ' ) : '\nPASS' );
	say( `shots in ${ OUT } - LOOK AT THEM.` );
	fs.writeFileSync( path.join( OUT, 'tourcheck.txt' ), log.join( '\n' ) + '\n' );
	await b.close();
	process.exit( bad.length ? 1 : 0 );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
