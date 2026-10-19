#!/usr/bin/env node
/* How long a visitor waits for their FIRST hover to open a storey, measured
 * from navigation start on a cold cache. The pointer is put on the facade the
 * moment the veil lifts and held there; everything after that is the page.
 *
 *   node tools/hoverwait.cjs [rounds] [query] [w] [h] [dsf]
 *
 * Prints, per round: ready, armed, the wall starting to part, fully open, and
 * every `console.info` the warm logs with the time it landed. Rounds are
 * separate boots with their own profile, so nothing is cached between them -
 * which is the state a visitor arrives in. Take the MEDIAN; this machine
 * swings 30% between loads.                                                */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const ROUNDS = + ( process.argv[ 2 ] || 3 );
const QUERY = process.argv[ 3 ] || '';
const W = + ( process.argv[ 4 ] || 1600 ), H = + ( process.argv[ 5 ] || 900 );
const DSF = + ( process.argv[ 6 ] || 2 );
const med = ( a ) => { const s = a.filter( x => x != null ).slice().sort( ( x, y ) => x - y );
	return s.length ? s[ s.length >> 1 ] : null; };

/* Where on the facade to point. The hero is a moving rail, so a fixed point
 * is over a different storey a second later - that is fine, any storey will
 * do - but it must be ON the building at the moment the veil lifts. */
const PT = [ 0.52, 0.26 ];

async function round( n ) {
	const dir = path.join( os.tmpdir(), 'lp-hoverwait-' + process.pid + '-' + n );
	fs.rmSync( dir, { recursive: true, force: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H, '--user-data-dir=' + dir ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	const log = [];
	await p.evaluateOnNewDocument( () => { window.__t0 = performance.now(); } );
	p.on( 'console', m => { const t = m.text();
		if ( /warm|flat|frame|ready|pipeline|hover/i.test( t ) ) log.push( t.slice( 0, 160 ) ); } );
	const url = 'http://127.0.0.1:8777/index.html?' + ( QUERY || '' );
	await p.goto( url, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 50 } );
	const ready = await p.evaluate( () => performance.now() );
	/* On the building at once, and held there. The hero is a moving rail, so
	 * a fixed point is over a different storey a second later and may be off
	 * the building altogether - the page is swept down its facade until a
	 * band answers (`lp:floor` carries the storey even before the hover is
	 * armed), and then that point is nudged by a pixel every frame, because
	 * a visitor's hand is never perfectly still either. */
	const t = await p.evaluate( async ( W, H ) => {
		const out = { armed: null, part: null, open: null, found: null };
		const dom = document.querySelector( 'canvas' );
		const at = ( x, y ) => dom.dispatchEvent( new PointerEvent( 'pointermove',
			{ clientX: x, clientY: y, bubbles: true } ) );
		let seen = 0;
		addEventListener( 'lp:floor', ( e ) => { if ( e.detail && e.detail.floor ) seen = e.detail.floor; } );
		const XS = [ 0.52, 0.58, 0.46, 0.64, 0.40 ], YS = [ 0.26, 0.32, 0.20, 0.38, 0.44 ];
		let k = 0, pt = null;
		const t0 = performance.now();
		while ( performance.now() - t0 < 30000 ) {
			if ( ! pt ) {
				const x = XS[ k % XS.length ], y = YS[ Math.floor( k / XS.length ) % YS.length ];
				k ++;
				at( Math.round( W * x ), Math.round( H * y ) );
				await new Promise( r => requestAnimationFrame( r ) );
				if ( seen ) { pt = [ Math.round( W * x ), Math.round( H * y ) ]; out.found = performance.now(); }
				continue;
			}
			at( pt[ 0 ] + ( k ++ & 1 ), pt[ 1 ] );
			const f = window.__floor();
			const o = Math.max( 0, ...f.slots.map( s => s.open ) );
			if ( out.armed == null && f.armed ) out.armed = performance.now();
			if ( out.part == null && o > 0 ) out.part = performance.now();
			if ( out.open == null && o >= 1 ) { out.open = performance.now(); break; }
			if ( ! f.hot && f.armed && o === 0 ) pt = null;     // the rail moved it off
			await new Promise( r => requestAnimationFrame( r ) );
		}
		return out;
	}, W, H );
	const marks = await p.evaluate( () => ( window.__perf || {} ).marks || [] );
	await b.close();
	fs.rmSync( dir, { recursive: true, force: true } );
	return { ready, ...t, marks, log };
}

( async () => {
	const rows = [];
	for ( let i = 0; i < ROUNDS; i ++ ) {
		const r = await round( i );
		rows.push( r );
		console.log( `\n--- round ${ i + 1 }  ready ${ Math.round( r.ready ) } ms` +
			`   armed ${ r.armed ? Math.round( r.armed ) : '-' }` +
			`   parts ${ r.part ? Math.round( r.part ) : '-' }` +
			`   open ${ r.open ? Math.round( r.open ) : '-' } ms` );
		console.log( '    marks ' + r.marks.map( m => m[ 0 ] + ' ' + m[ 1 ] ).join( ' | ' ) );
		for ( const l of r.log ) console.log( '    ' + l );
	}
	console.log( `\n${ ROUNDS } rounds of index.html?${ QUERY }   ${ W }x${ H } @${ DSF }` );
	console.log( '  ready  ' + med( rows.map( r => r.ready ) ) );
	console.log( '  armed  ' + med( rows.map( r => r.armed ) ) );
	console.log( '  parts  ' + med( rows.map( r => r.part ) ) );
	console.log( '  open   ' + med( rows.map( r => r.open ) ) + '   (ms from navigation)' );
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
