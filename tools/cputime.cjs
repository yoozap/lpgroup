#!/usr/bin/env node
/* Where the MAIN THREAD goes while the hero sweeps.
 *
 * `tools/fpsmax.cjs` says what a frame costs the GPU; this says what it
 * costs the CPU. The question that prompted it: the GPU draws a frame in
 * 12 ms at the density the hero settles on, and the frames arrive 18 ms
 * apart - so is the page's own per-frame bookkeeping (the rail, the hover
 * tests, the tween list, the badge and dot placement, everything that runs
 * before `pipeline.render()` is reached) eating the difference?
 *
 * **It is not.** Measured 2026-10-20: 58.5 fps, the main thread 87% IDLE,
 * 2.2 ms a frame of real work, with three.js' own `updateByType` and
 * `_renderObjectDirect` at the top of what little there is. The gap was
 * the density ladder sitting on the wrong rung, not the CPU. Re-run this
 * before blaming `frame()` for anything.
 *
 * It is a CDP sampling profile of the live page, aggregated by self time.
 *
 *   node tools/cputime.cjs [page] [secs] [w] [h] [dsf] [extra query]
 *   node tools/cputime.cjs index.html 10
 *   node tools/cputime.cjs index.html 10 1600 900 2 'hover=1'
 *
 * `hover=1` parks the pointer on the facade, the way ridecost does, so the
 * x-ray storey is open while it records.                                  */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const PAGE = process.argv[ 2 ] || 'index.html';
const SECS = + ( process.argv[ 3 ] || 10 );
const W = + ( process.argv[ 4 ] || 1600 ), H = + ( process.argv[ 5 ] || 900 );
const DSF = + ( process.argv[ 6 ] || 2 );
const RAW = process.argv[ 7 ] || '';
const HOVER = /(^|&)hover=1(&|$)/.test( RAW );
const EXTRA = RAW.replace( /(^|&)hover=1(&|$)/, '$1' ).replace( /&$/, '' );

/* Wiped per run: a crashed rig otherwise leaves a `SingletonLock`
 * behind and every later one dies with "the browser is already
 * running" - into the output file, where it reads as an empty
 * result rather than an error. See the same note in ridecost. */
const PROFILE = path.join( os.tmpdir(), 'lp-cpu' );
require( 'fs' ).rmSync( PROFILE, { recursive: true, force: true } );

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + PROFILE ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/' + PAGE + ( EXTRA ? '?' + EXTRA : '' ),
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 14000 );              // past the show flat's warm
	if ( HOVER ) await p.mouse.move( W * 0.52, H * 0.52 );

	const cdp = await p.target().createCDPSession();
	await cdp.send( 'Profiler.enable' );
	await cdp.send( 'Profiler.setSamplingInterval', { interval: 100 } );   // us
	const before = await p.evaluate( () => ( {
		rendered: window.__perf ? window.__perf.rendered : 0,
		t: performance.now(), d: window.__density ? window.__density() : null } ) );
	await cdp.send( 'Profiler.start' );
	await sleep( SECS * 1000 );
	const { profile } = await cdp.send( 'Profiler.stop' );
	const after = await p.evaluate( () => ( {
		rendered: window.__perf ? window.__perf.rendered : 0,
		t: performance.now(), d: window.__density ? window.__density() : null } ) );

	/* self time per node, from the sample counts and the deltas between them */
	const byId = new Map();
	for ( const n of profile.nodes ) byId.set( n.id, n );
	const self = new Map();
	const deltas = profile.timeDeltas || [];
	for ( let i = 0; i < profile.samples.length; i ++ ) {
		const id = profile.samples[ i ];
		const dt = ( deltas[ i ] || 0 ) / 1000;      // us -> ms
		self.set( id, ( self.get( id ) || 0 ) + dt );
	}
	const label = ( n ) => {
		const f = n.callFrame;
		const where = ( f.url || '' ).split( '/' ).pop().split( '?' )[ 0 ];
		return ( f.functionName || '(anonymous)' ) + ( where ? '  ' + where : '' );
	};
	const rows = [ ...self.entries() ]
		.map( ( [ id, ms ] ) => ( { ms, n: byId.get( id ) } ) )
		.filter( r => r.n )
		.sort( ( a, b ) => b.ms - a.ms );
	const total = rows.reduce( ( s, r ) => s + r.ms, 0 );
	const wall = after.t - before.t;
	const drawn = after.rendered - before.rendered;

	console.log( `page ${ PAGE }${ EXTRA ? '?' + EXTRA : '' }   ${ W }x${ H } @${ DSF }${ HOVER ? '   pointer on the facade' : '' }` );
	console.log( `${ SECS } s: ${ drawn } frames drawn = ${ ( drawn / ( wall / 1000 ) ).toFixed( 1 ) } fps, ${ ( wall / drawn ).toFixed( 1 ) } ms apart` );
	console.log( `density pr ${ after.d && after.d.pr } = ${ after.d && after.d.mpx } Mpx` );
	console.log( `main thread busy ${ total.toFixed( 0 ) } of ${ wall.toFixed( 0 ) } ms = ${ ( 100 * total / wall ).toFixed( 0 ) }%` +
		`,  ${ ( total / drawn ).toFixed( 2 ) } ms a frame\n` );
	console.log( '    ms   /frame   share   function' );
	for ( const r of rows.slice( 0, 22 ) ) {
		if ( r.ms < 0.5 ) break;
		console.log( `${ r.ms.toFixed( 0 ).padStart( 6 ) }  ${ ( r.ms / drawn ).toFixed( 2 ).padStart( 6 ) }  ${
			( 100 * r.ms / wall ).toFixed( 1 ).padStart( 5 ) }%   ${ label( r.n ) }` );
	}
	await b.close();
} )();
