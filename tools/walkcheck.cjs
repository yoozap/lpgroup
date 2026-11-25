#!/usr/bin/env node
/* Walk on foot on the sales page, with the KEYBOARD, and report what the body
 * did: where it ended up, how much floor it had round it at each stop, the
 * gait mid-stride, and the doors standing open.
 *   node tools/walkcheck.cjs [flat] [query]       (flat default 37)
 *
 * Re-pointed at the real building (2026-11-24): the body is web/walk.js's,
 * hosted by app.js ("walking the building"). The way in is the one a
 * visitor takes from the floor view - open the flat, click a room dot - and
 * landing in the room IS walking. `free` is the number to read: it must
 * never fall under `need` (the body's radius) while the body is in the
 * open, and a body that never moves has walked into a wall. The page must
 * also go quiet (no frame drawn) once the keys are up. Shots land in
 * perf-shots/walk-*.png. Exit 1 on any failure. */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const SHOTS = path.join( __dirname, '..', 'perf-shots' );
const FLAT = process.argv[ 2 ] || '37';
const q = process.argv[ 3 ] || '?lang=en';

( async () => {
	fs.mkdirSync( SHOTS, { recursive: true } );
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1400,800', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-walk-' + process.pid ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1400, height: 800, deviceScaleFactor: 1 } );
	const bad = [], fail = [];
	page.on( 'console', m => { const t = m.text();
		if ( /error|failed|invalid|undefined is not|unmapped/i.test( t ) && ! /404/.test( t ) ) bad.push( t.slice( 0, 200 ) ); } );
	page.on( 'pageerror', e => bad.push( 'PAGEERROR ' + String( e ).slice( 0, 200 ) ) );
	await page.goto( 'http://127.0.0.1:8777/' + q, { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 100 } );
	await sleep( 2500 );
	const until = async ( pred, ms = 30000 ) => { const t0 = Date.now(); while ( Date.now() - t0 < ms ) { if ( await page.evaluate( pred ) ) return true; await sleep( 150 ); } return false; };
	// the floor view, the flat, then a room dot - as a visitor clicks them
	await page.evaluate( ( n ) => window.LP.openFlat( n ), FLAT );
	if ( ! await until( `window.__lv().focus === '${ FLAT }' && !window.__lv().tweens` ) ) fail.push( 'the flat never opened' );
	await sleep( 1200 );
	await page.evaluate( () => { const d = document.querySelector( '#roomdots .rdot:not([hidden])' ); if ( d ) d.click(); } );
	if ( ! await until( 'window.__bw.on && !window.__lv().tweens', 30000 ) ) fail.push( 'landing in the room did not start the walk' );
	await sleep( 1500 );
	const st = () => page.evaluate( () => { const s = window.__bw.s, W = window.__bw.W;
		if ( ! s ) return null;
		const B = W.debug.B;
		return { level: s.level, flat: s.flat, room: s.room && s.room.name, at: [ +B.x.toFixed( 3 ), +B.y.toFixed( 3 ) ],
			free: +W.debug.free( s.level, B.x, B.y ).toFixed( 3 ), need: W.WALK.R, v: +Math.hypot( B.vx, B.vy ).toFixed( 2 ),
			bob: [ +B.bobY.toFixed( 4 ), +B.sway.toFixed( 4 ) ], eye: +( s.eye[ 1 ] - s.pos.world[ 1 ] ).toFixed( 3 ),
			doors: s.doors.map( d => d.id + '@' + d.angle.toFixed( 0 ) ) }; } );
	const w0 = await st();
	console.log( 'stance:', JSON.stringify( w0 ) );
	await page.screenshot( { path: path.join( SHOTS, 'walk-0-stance.png' ) } );
	if ( ! w0 || String( w0.flat ) !== FLAT ) fail.push( 'not standing in flat ' + FLAT );
	// the canvas has the keys (not a page control)
	await page.mouse.click( 900, 420 );
	await sleep( 400 );
	const hold = async ( key, ms, tag ) => {
		const a = await st();
		await page.keyboard.down( key );
		/* Sampled MID-STRIDE as well as at the end: the gait scales with
		 * how fast the body is going, so every number in it is zero by the
		 * time the keys are up. */
		await sleep( Math.round( ms * 0.6 ) );
		const mid = await st();
		console.log( `${ tag.padEnd( 14 ) } mid-stride v ${ mid.v } bob ${ JSON.stringify( mid.bob ) } free ${ mid.free }` );
		await sleep( ms - Math.round( ms * 0.6 ) );
		await page.keyboard.up( key );
		await sleep( 900 );
		const w = await st();
		console.log( `${ tag.padEnd( 14 ) } at ${ JSON.stringify( w.at ) } ${ w.room } free ${ w.free } v ${ w.v } eye ${ w.eye }`
			+ ( w.doors.length ? '\n                 doors open ' + w.doors.join( '  ' ) : '' ) );
		await page.screenshot( { path: path.join( SHOTS, 'walk-' + tag + '.png' ) } );
		if ( Math.min( mid.free, w.free ) < w.need - 0.01 ) fail.push( `${ tag }: free ${ Math.min( mid.free, w.free ) } under ${ w.need }` );
		if ( Math.abs( w.eye - 1.6 ) > 0.03 ) fail.push( `${ tag }: eye ${ w.eye }` );
		if ( w.v !== 0 ) fail.push( `${ tag }: still moving after the keys came up` );
		return { a, mid, w, moved: Math.hypot( w.at[ 0 ] - a.at[ 0 ], w.at[ 1 ] - a.at[ 1 ] ) };
	};
	const r = [ await hold( 'w', 1400, '1-forward' ), await hold( 'd', 900, '2-right' ),
		await hold( 'w', 1800, '3-forward' ), await hold( 's', 1200, '4-back' ) ];
	if ( ! r.some( x => x.moved > 0.3 ) ) fail.push( 'the body never moved' );
	if ( ! r.some( x => Math.abs( x.mid.bob[ 0 ] ) > 1e-4 ) ) fail.push( 'no gait mid-stride' );
	// standing still: quiet within a few seconds
	let quiet = false;
	for ( let k = 0; k < 6 && ! quiet; k ++ ) {
		const a = await page.evaluate( () => window.__perf.rendered ); await sleep( 2000 );
		quiet = ( await page.evaluate( () => window.__perf.rendered ) ) === a;
	}
	console.log( 'idle once the keys are up:', quiet );
	if ( ! quiet ) fail.push( 'the page kept drawing with the body standing still' );
	// out again with Escape: back to the flat in the floor view
	await page.keyboard.press( 'Escape' );
	if ( ! await until( `!window.__bw.on && window.__lv().focus === '${ FLAT }' && !window.__lv().tweens`, 20000 ) ) fail.push( 'Escape did not bring the flat back' );
	await sleep( 1000 );
	await page.screenshot( { path: path.join( SHOTS, 'walk-5-out.png' ) } );
	console.log( bad.length ? 'CONSOLE:\n  ' + [ ...new Set( bad ) ].slice( 0, 6 ).join( '\n  ' ) : 'console clean' );
	if ( bad.length ) fail.push( 'console' );
	console.log( fail.length ? 'FAIL\n  ' + fail.join( '\n  ' ) : 'PASS' );
	await browser.close();
	process.exit( fail.length ? 1 : 0 );
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
