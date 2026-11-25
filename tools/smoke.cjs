#!/usr/bin/env node
/* Walks the page's controls and reports anything the console complains about.
 *   node tools/smoke.cjs [query]
 * Writes perf-shots/smoke-*.png for the states worth looking at.           */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
/* The render page is lab.html; / is the sales site. An argument that
 * starts with ? is a query on the lab, anything else is a page of its own. */
const page_ = ( a ) => ( ! a || a.startsWith( '?' ) ) ? 'lab.html' + a : a;
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const SHOTS = path.join( __dirname, '..', 'perf-shots' );

( async () => {
	fs.mkdirSync( SHOTS, { recursive: true } );
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1400,800', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-smoke' ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1400, height: 800, deviceScaleFactor: 1 } );
	const bad = [];
	page.on( 'console', m => { const t = m.text();
		if ( /error|failed|invalid|undefined is not|unmapped/i.test( t ) ) bad.push( t.slice( 0, 180 ) ); } );
	page.on( 'pageerror', e => bad.push( 'PAGEERROR ' + String( e ).slice( 0, 180 ) ) );
	await page.goto( 'http://127.0.0.1:8777/' + page_( process.argv[ 2 ] || '' ), { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 100 } );
	const shot = async ( n ) => { await sleep( 1200 ); await page.screenshot( { path: path.join( SHOTS, 'smoke-' + n + '.png' ) } ); };
	const click = async ( id ) => { await page.evaluate( ( id ) => document.getElementById( id ).click(), id ); };

	await sleep( 2000 );
	await shot( '1-street' );
	/* The real building (2026-11-24): scene 2 is a level now. The lab's own
	 * Scene 2 button opens the show flat's level; the rest is driven through
	 * window.LP, which the lab carries too. The old show flat's toggles
	 * (t_plan, t_mirror, t_hide) are gone with it. */
	const lp = ( js ) => page.evaluate( js );
	await click( 's_2' ); await sleep( 9000 ); await shot( '2-show-flat' );
	await lp( "LP.openLevel('L05')" ); await sleep( 6000 ); await shot( '3-level-L05' );
	await lp( "LP.openLevel('L01')" ); await sleep( 6000 ); await shot( '4-level-L01-offices' );
	await lp( "LP.openFlat('47-a')" ); await sleep( 7000 ); await shot( '5-flat-47-a' );
	// a room dot lands the visitor on foot (app.js "walking the building")
	await lp( "LP.roomTo(0)" ); await sleep( 4000 ); await shot( '6-room' );
	const onFoot = await lp( "!!(window.__bw && window.__bw.on)" );
	if ( ! onFoot ) bad.push( 'landing in a room did not start the walk' );
	await lp( "LP.roomTo(null)" ); await sleep( 3000 );
	await lp( "LP.closeFlat()" ); await sleep( 2500 );
	// in at a street door, a few steps into the hall, and back out
	await lp( "LP.walk({portal:'C1'})" ); await sleep( 7000 );
	await lp( "window.__bw.step(150,{forward:1})" ); await sleep( 2000 ); await shot( '6b-walk-hall-C1' );
	const hall = await lp( "window.__bw.s && window.__bw.s.surface" );
	if ( hall !== 'hall' ) bad.push( 'walking in at C1 did not reach the hall (' + hall + ')' );
	await lp( "LP.walkExit('street')" ); await sleep( 3000 );
	await click( 'm_orbit' ); await sleep( 1500 );
	await click( 'm_hero' ); await sleep( 1500 );
	await click( 's_1' ); await sleep( 6000 ); await shot( '7-back-to-street' );
	const lv = await lp( "JSON.stringify(window.__lv())" );
	console.log( 'levels', lv.slice( 0, 400 ) );
	await click( 't_ao' ); await sleep( 1200 ); await click( 't_ao' );
	await click( 't_grade' ); await sleep( 1200 ); await click( 't_grade' );
	await sleep( 1500 );
	const state = await page.evaluate( () => ( {
		fps: document.getElementById( 'fps' ).textContent,
		drawn: ( window.__perf || {} ).rendered,
		marks: ( window.__perf || {} ).marks,
	} ) );
	console.log( 'state', JSON.stringify( state ) );
	console.log( bad.length ? 'COMPLAINTS:\n' + [ ...new Set( bad ) ].join( '\n' ) : 'console clean' );
	await browser.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
