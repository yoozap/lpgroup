#!/usr/bin/env node
/* The first half minute of the page as a visitor feels it: every drawn
 * frame's interval, the density it was drawn at, and what the adaptive
 * ladder was doing - second by second. This is the rig for "it lags", as
 * opposed to the rigs that ask what one frame costs.
 *
 *   node tools/ridecost.cjs [secs] [w] [h] [dsf] [extra query]
 *   node tools/ridecost.cjs 20                       # the hero as it ships
 *   node tools/ridecost.cjs 20 1600 900 2 'ss=1'     # without the still SS
 *   node tools/ridecost.cjs 20 1600 900 2 'hover=1'  # pointer parked on the facade
 *
 * `hover=1` is this rig's own flag, not the page's: it parks the pointer on
 * the facade so the x-ray storey is open the whole time.                   */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const SECS = + ( process.argv[ 2 ] || 20 );
const W = + ( process.argv[ 3 ] || 1600 ), H = + ( process.argv[ 4 ] || 900 );
const DSF = + ( process.argv[ 5 ] || 2 );
const EXTRA = ( process.argv[ 6 ] || '' ).replace( /(^|&)hover=1(&|$)/, '$1' ).replace( /&$/, '' );
const HOVER = /(^|&)hover=1(&|$)/.test( process.argv[ 6 ] || '' );
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };
const pct = ( a, q ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ Math.min( s.length - 1, Math.floor( s.length * q ) ) ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-ride' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	const url = 'http://127.0.0.1:8777/index.html' + ( EXTRA ? '?' + EXTRA : '' );
	const t0 = Date.now();
	await p.goto( url, { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	const boot = Date.now() - t0;

	/* The watcher rides the page's own rAF - it does NOT invalidate, because
	 * the question here is what the page draws of its own accord. A frame
	 * that was not drawn is not counted: the interval is taken from the
	 * page's own rendered-frame counter. */
	await p.evaluate( () => {
		window.__ride = [];
		let last = performance.now(), seen = window.__perf.rendered || 0;
		const tick = () => {
			const now = performance.now();
			const r = window.__perf.rendered || 0;
			if ( r > seen ) {
				const d = window.__density ? window.__density() : {};
				window.__ride.push( [ + ( now - last ).toFixed( 2 ), d.pr || 0, d.mpx || 0,
					d.still ? 1 : 0, d.step === undefined ? -1 : d.step ] );
				seen = r; last = now;
			}
			requestAnimationFrame( tick );
		};
		requestAnimationFrame( tick );
	} );

	if ( HOVER ) {
		// park the pointer on the facade: find a point that lights a storey
		let hot = 0;
		for ( const fx of [ 0.62, 0.70, 0.54, 0.78 ] ) {
			for ( const fy of [ 0.52, 0.44, 0.60, 0.36 ] ) {
				await p.mouse.move( Math.round( W * fx ), Math.round( H * fy ) );
				await sleep( 220 );
				hot = ( await p.evaluate( () => window.__floor().hot ) );
				if ( hot ) break;
			}
			if ( hot ) break;
		}
		console.log( hot ? `pointer parked on storey ${ hot }` : 'pointer found no storey' );
	}

	await sleep( SECS * 1000 );
	const ride = await p.evaluate( () => window.__ride );
	const d = await p.evaluate( () => window.__density() );

	console.log( `index.html${ EXTRA ? '?' + EXTRA : '' }${ HOVER ? '  +hover' : '' }` +
		`   ${ W }x${ H } @${ DSF }   boot ${ ( boot / 1000 ).toFixed( 1 ) } s` +
		`   ${ ride.length } frames in ${ SECS } s = ${ ( ride.length / SECS ).toFixed( 1 ) } fps\n` );

	// second by second, so the boot crawl and the still spikes are visible
	console.log( ' second   frames   med ms   p95 ms   pr    Mpx   still' );
	let t = 0, i = 0;
	for ( let s = 0; s < SECS; s ++ ) {
		const bucket = [];
		while ( i < ride.length && t + ride[ i ][ 0 ] <= ( s + 1 ) * 1000 ) { t += ride[ i ][ 0 ]; bucket.push( ride[ i ++ ] ); }
		if ( ! bucket.length ) { console.log( `  ${ String( s ).padStart( 4 ) }        0        -        -     -      -     -` ); continue; }
		const ms = bucket.map( x => x[ 0 ] );
		console.log( `  ${ String( s ).padStart( 4 ) }   ${ String( bucket.length ).padStart( 6 ) }` +
			`   ${ med( ms ).toFixed( 1 ).padStart( 6 ) }   ${ pct( ms, 0.95 ).toFixed( 1 ).padStart( 6 ) }` +
			`   ${ med( bucket.map( x => x[ 1 ] ) ).toFixed( 2 ) }  ${ med( bucket.map( x => x[ 2 ] ) ).toFixed( 2 ).padStart( 5 ) }` +
			`   ${ med( bucket.map( x => x[ 3 ] ) ) ? 'yes' : 'no' }` );
	}
	const all = ride.map( x => x[ 0 ] );
	console.log( `\n  whole ride: median ${ med( all ).toFixed( 1 ) } ms   p95 ${ pct( all, 0.95 ).toFixed( 1 ) } ms` +
		`   worst ${ Math.max( ...all ).toFixed( 1 ) } ms   over 20 ms: ` +
		`${ ( all.filter( x => x > 20 ).length / all.length * 100 ).toFixed( 0 ) }%` );
	console.log( `  settled at pr ${ d.pr } (step ${ d.step }) = ${ d.mpx } Mpx` );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
