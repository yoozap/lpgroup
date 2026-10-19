#!/usr/bin/env node
/* What the page settles on at each depth of scene 2, once it has stood
 * still long enough to spend its still-frame budget.
 *
 *   node tools/flatquality.cjs [w] [h] [dsf]
 *
 * The number that matters is `pr` - the effective pixel ratio the parked
 * frame is drawn at. That is the sharpness a visitor who has stopped
 * moving actually sees.                                                   */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 2 );

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-flatq' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0', { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 20000 );

	/* Stand still and keep asking for frames until the page has counted
	 * enough of them to spend the supersample, then read what it settled
	 * on. Nothing is moved here: that is the whole point of the state. */
	const settle = ( secs = 14 ) => p.evaluate( async ( secs ) => {
		const R = window.__renderer, end = performance.now() + secs * 1000;
		const ts = [];
		while ( performance.now() < end ) {
			const t0 = performance.now();
			window.__invalidate( 1 );
			await new Promise( r => requestAnimationFrame( r ) );
			ts.push( performance.now() - t0 );
		}
		const tail = ts.slice( - 40 ).sort( ( a, b ) => a - b );
		return { ...window.__density(), draws: R.info.render.drawCalls,
			triM: + ( R.info.render.triangles / 1e6 ).toFixed( 2 ),
			ms: + tail[ tail.length >> 1 ].toFixed( 1 ) };
	}, secs );

	const rows = [];
	const at = async ( label, fn ) => { await fn(); await sleep( 2000 );
		const r = await settle();
		rows.push( [ label, r ] );
		process.stderr.write( `${ label }: pr ${ r.pr }  ${ r.mpx } Mpx  ${ r.ms } ms\n` ); };

	await at( 'street', () => p.evaluate( () => window.__storey( 0 ) ) );
	await at( 'floor view', () => p.evaluate( () => window.__storey( 7, 'plan' ) ) );
	await at( 'one flat open', () => p.evaluate( () => window.__focus( 2 ) ) );
	await at( 'inside a room', () => p.evaluate( () => window.__room( 0 ) ) );

	console.log( `\n${ W }x${ H } @${ DSF }   settled (parked) frame\n` );
	console.log( 'state                   pr     Mpx    draws   M tris    ms   ms/Mpx  city' );
	for ( const [ k, r ] of rows ) {
		const cost = r.inFlat ? r.msPerMpxFlat : r.msPerMpx;
		console.log( `  ${ k.padEnd( 20 ) }${ String( r.pr ).padStart( 6 ) }` +
			`${ String( r.mpx ).padStart( 8 ) }${ String( r.draws ).padStart( 8 ) }` +
			`${ String( r.triM ).padStart( 9 ) }${ String( r.ms ).padStart( 7 ) }` +
			`${ String( cost ).padStart( 8 ) }   ${ r.cityHidden ? 'hidden' : 'drawn' }` );
	}
	console.log( '' );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
