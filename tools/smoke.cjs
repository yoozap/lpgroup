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
	await click( 's_2' ); await sleep( 8000 ); await shot( '2-flat' );
	await click( 'm_top' ); await sleep( 2000 );
	await click( 't_plan' ); await sleep( 2500 ); await shot( '3-plan' );
	await click( 't_mirror' ); await sleep( 1500 ); await shot( '4-plan-unmirrored' );
	await click( 't_mirror' ); await click( 't_plan' );
	await click( 't_hide' ); await sleep( 1500 ); await shot( '5-no-furniture' );
	await click( 't_hide' );
	await click( 'm_orbit' ); await sleep( 1500 );
	await click( 'm_hero' ); await sleep( 1500 );
	await click( 's_1' ); await sleep( 8000 ); await shot( '6-back-to-street' );
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
