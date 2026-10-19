#!/usr/bin/env node
/* Walk the show flat on foot, on the sales page, and report what the body
 * did: where it ended up, how much floor it had round it at each stop, and
 * how far each door had swung.
 *   node tools/walkcheck.cjs [room] [query]
 * `free` is the number to read - it must never fall under `need` while the
 * body is in the open, and a body that never moves has walked into a wall
 * the grid should not have had. Shots land in perf-shots/walk-*.png.     */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const SHOTS = path.join( __dirname, '..', 'perf-shots' );
const room = + ( process.argv[ 2 ] || 0 );
const q = process.argv[ 3 ] || '?walklog=1';

( async () => {
	fs.mkdirSync( SHOTS, { recursive: true } );
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1400,800', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-walk-' + process.pid ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1400, height: 800, deviceScaleFactor: 1 } );
	const bad = [];
	page.on( 'console', m => { const t = m.text();
		if ( /\[walk\]/.test( t ) ) console.log( '  ' + t );
		else if ( /error|failed|invalid|undefined is not|unmapped/i.test( t ) ) bad.push( t.slice( 0, 200 ) ); } );
	page.on( 'pageerror', e => bad.push( 'PAGEERROR ' + String( e ).slice( 0, 200 ) ) );
	await page.goto( 'http://127.0.0.1:8777/' + q, { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 100 } );
	await sleep( 2500 );
	// the storey from above, then one flat on it, then into a room on foot
	await page.evaluate( () => window.LP.setScene( 2, undefined, 'plan' ) );
	await sleep( 5000 );
	await page.evaluate( () => window.LP.planFocusTo( 0 ) );
	await sleep( 3000 );
	await page.evaluate( ( r ) => window.LP.roomTo( r ), room );
	await sleep( 3000 );
	console.log( 'room :', JSON.stringify( await page.evaluate( () => window.__room() ) ) );
	const w0 = await page.evaluate( () => window.__walk() );
	console.log( 'walk :', JSON.stringify( w0 ) );
	await page.screenshot( { path: path.join( SHOTS, 'walk-0-stance.png' ) } );

	const hold = async ( key, ms, tag ) => {
		await page.keyboard.down( key );
		/* Sampled MID-STRIDE as well as at the end: the gait scales with
		 * how fast the body is going, so every number in it is zero by the
		 * time the keys are up, and a walk with no bob at all would read
		 * exactly the same at the stops. */
		await sleep( Math.round( ms * 0.6 ) );
		const mid = await page.evaluate( () => window.__walk() );
		console.log( `${ tag.padEnd( 14 ) } mid-stride v ${ mid.v }`
			+ ` bob ${ JSON.stringify( mid.bob ) } free ${ mid.free }` );
		await sleep( ms - Math.round( ms * 0.6 ) );
		await page.keyboard.up( key );
		await sleep( 900 );
		const w = await page.evaluate( () => window.__walk() );
		console.log( `${ tag.padEnd( 14 ) } at ${ JSON.stringify( w.at ) } free ${ w.free }`
			+ ` v ${ w.v } bob ${ JSON.stringify( w.bob ) }`
			+ ( w.doors ? '\n                 doors ' + w.doors.map( d => d.key + ' ' + d.t ).join( '  ' ) : '' ) );
		await page.screenshot( { path: path.join( SHOTS, 'walk-' + tag + '.png' ) } );
		return w;
	};
	await hold( 'w', 1400, '1-forward' );
	await hold( 'd', 900, '2-right' );
	await hold( 'w', 1800, '3-forward' );
	await hold( 's', 1200, '4-back' );
	console.log( bad.length ? 'ERRORS:\n  ' + bad.slice( 0, 4 ).join( '\n  ' ) : 'clean' );
	await browser.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
