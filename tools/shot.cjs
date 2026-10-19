#!/usr/bin/env node
/* One boot, one screenshot of Scene 1 with the HUD and the wipe out of the
 * way: node tools/shot.cjs <out.png> [query] [waitMsAfterBoot]            */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
/* The render page is lab.html; / is the sales site. An argument that
 * starts with ? is a query on the lab, anything else is a page of its own. */
const page_ = ( a ) => ( ! a || a.startsWith( '?' ) ) ? 'lab.html' + a : a;
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const out = process.argv[ 2 ], q = process.argv[ 3 ] || '', waitMs = + ( process.argv[ 4 ] || 4000 );
( async () => {
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1600,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-shot-' + process.pid ) ] } );
	const page = await browser.newPage();
	await page.setViewport( { width: 1600, height: 900, deviceScaleFactor: 2 } );
	const errs = [];
	page.on( 'console', m => { const t = m.text(); if ( /error|failed|Invalid/i.test( t ) ) errs.push( t.slice( 0, 200 ) ); } );
	await page.goto( 'http://127.0.0.1:8777/' + page_( q ), { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 100 } );
	await sleep( waitMs );
	await page.evaluate( () => { document.getElementById( 'hud' ).style.display = 'none';
		document.getElementById( 'frame' ).classList.remove( 'cmp' );
		if ( window.__invalidate ) window.__invalidate( 40 ); } );
	await sleep( 1500 );
	await page.screenshot( { path: out } );
	console.log( out, errs.length ? 'ERRORS: ' + errs.slice( 0, 3 ).join( ' | ' ) : 'clean' );
	await browser.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
