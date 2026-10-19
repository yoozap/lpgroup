#!/usr/bin/env node
/* Boot, click Scene 2, wait for the move to finish, shoot.
 *   node tools/shot2.cjs <out.png> [page+query] [settleMs]                */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
/* The render page is lab.html; / is the sales site. An argument that
 * starts with ? is a query on the lab, anything else is a page of its own. */
const page_ = ( a ) => ( ! a || a.startsWith( '?' ) ) ? 'lab.html' + a : a;
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const out = process.argv[ 2 ], q = process.argv[ 3 ] || '', settle = + ( process.argv[ 4 ] || 9000 );
( async () => {
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1600,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-shot2-' + process.pid ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1600, height: 900, deviceScaleFactor: 2 } );
	const errs = [];
	page.on( 'console', m => { const t = m.text(); if ( /error|failed|Invalid/i.test( t ) && ! /404/.test( t ) ) errs.push( t.slice( 0, 160 ) ); } );
	await page.goto( 'http://127.0.0.1:8777/' + page_( q ), { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 100 } );
	await sleep( 2500 );
	await page.evaluate( () => document.getElementById( 's_2' ).click() );
	await sleep( settle );
	await page.evaluate( () => { document.getElementById( 'hud' ).style.display = 'none';
		if ( window.__invalidate ) window.__invalidate( 40 ); } );
	await sleep( 1500 );
	await page.screenshot( { path: out } );
	console.log( out, errs.length ? 'ERRORS: ' + errs.slice( 0, 2 ).join( ' | ' ) : 'clean' );
	await browser.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
