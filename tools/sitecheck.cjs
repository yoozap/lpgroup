#!/usr/bin/env node
/* Boots the sales page, waits for the hero's scene, reports anything the
 * console complains about and writes full-page shots at two widths.
 *   node tools/sitecheck.cjs [query] */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const SHOTS = path.join( __dirname, '..', 'perf-shots' );
const q = process.argv[ 2 ] || '';

( async () => {
	fs.mkdirSync( SHOTS, { recursive: true } );
	const browser = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1500,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-site' ) ] } );
	const page = await browser.newPage();
	const bad = [];
	page.on( 'console', m => { const t = m.text();
		if ( /error|failed|invalid|undefined is not|cannot read/i.test( t ) ) bad.push( t.slice( 0, 180 ) ); } );
	page.on( 'pageerror', e => bad.push( 'PAGEERROR ' + String( e ).slice( 0, 180 ) ) );
	page.on( 'requestfailed', r => { if ( ! /photos\//.test( r.url() ) ) bad.push( 'FAILED ' + r.url().slice( -60 ) ); } );

	await page.setViewport( { width: 1500, height: 900, deviceScaleFactor: 1 } );
	await page.goto( 'http://127.0.0.1:8777/' + q, { waitUntil: 'domcontentloaded' } );
	await page.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 150 } );
	await sleep( 3500 );
	await page.screenshot( { path: path.join( SHOTS, 'site-hero.png' ) } );

	// the picker, the prices and the form, each in view
	for ( const [ name, sel ] of [ [ 'numbers', '#numbers' ], [ 'about', '#about' ],
			[ 'location', '#location' ],
			[ 'amenities', '#amenities' ], [ 'prices', '#prices' ], [ 'gallery', '#gallery' ],
			[ 'developer', '#developer' ], [ 'faq', '#faq' ], [ 'contacts', '#contacts' ],
			[ 'foot', '#foot' ] ] ) {
		await page.evaluate( ( s ) => document.querySelector( s ).scrollIntoView(), sel );
		await sleep( 900 );
		await page.screenshot( { path: path.join( SHOTS, 'site-' + name + '.png' ) } );
	}

	// what the page says about itself once everything is built
	const report = await page.evaluate( () => ( {
		cards: document.querySelectorAll( '.pcard' ).length,
		walks: document.querySelectorAll( '.walk' ).length,
		faqs: document.querySelectorAll( '.faq details' ).length,
		opts: document.getElementById( 'l-flat' ).options.length,
		calc: document.getElementById( 'c-out' ).textContent,
		scene: window.LP ? window.LP.scene : 'no scene',
		unfilled: [ ...document.querySelectorAll( '[data-v]' ) ]
			.filter( n => /^\s*$/.test( n.textContent ) && ! n.dataset.href ).map( n => n.dataset.v ),
		overflow: document.documentElement.scrollWidth > innerWidth + 1
			? document.documentElement.scrollWidth : 0,
	} ) );
	console.log( report );

	// phone
	await page.setViewport( { width: 390, height: 844, deviceScaleFactor: 2 } );
	await sleep( 1600 );
	await page.evaluate( () => scrollTo( 0, 0 ) );
	await sleep( 1800 );
	await page.screenshot( { path: path.join( SHOTS, 'site-phone.png' ) } );
	const narrow = await page.evaluate( () => document.documentElement.scrollWidth > 391
		? document.documentElement.scrollWidth : 0 );
	if ( narrow ) console.log( 'PHONE OVERFLOW', narrow );

	console.log( bad.length ? 'COMPLAINTS:\n  ' + [ ...new Set( bad ) ].slice( 0, 8 ).join( '\n  ' ) : 'clean' );
	await browser.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
