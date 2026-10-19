#!/usr/bin/env node
/* The hover's glazing, a dial at a time. One boot, the pointer parked on
 * whatever storey answers it first, and a screenshot per parameter set -
 * so the sets are compared in the same frame of the same load rather than
 * across boots, which this machine swings 30% between.
 *
 *   node tools/glasstune.cjs <outdir> '<json [{name, ...dials}]>' [dx,dy,w,h]
 *
 * The dials are the keys of `window.__glass`: f0, f90, body, green, env,
 * bow, sun, grime, mod, joint, city, amount. Anything left out of a set
 * keeps whatever the set before it left behind, so a sweep of one dial only
 * has to name that dial. The crop follows the hovered storey.
 *
 *   node tools/glasstune.cjs /tmp/g '[{"name":"a","amount":0},
 *                                     {"name":"b","amount":1}]'            */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' ), fs = require( 'fs' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const dir = process.argv[ 2 ];
const sets = JSON.parse( process.argv[ 3 ] );
/* the crop follows the pointer: [dx, dy, w, h] around the storey it lit */
const crop = ( process.argv[ 4 ] || '-470,-105,1120,235' ).split( ',' ).map( Number );
const W = 1600, H = 900;
( async () => {
	fs.mkdirSync( dir, { recursive: true } );
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-gtune-' + process.pid ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: 2 } );
	const errs = [];
	p.on( 'console', m => { const t = m.text();
		if ( /error|failed|Invalid|warn/i.test( t ) ) errs.push( t.slice( 0, 240 ) ); } );
	p.on( 'pageerror', e => errs.push( 'PAGEERROR ' + e.message.slice( 0, 300 ) ) );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0', { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 16000 );
	let pt = null;
	outer: for ( const fx of [ 0.62, 0.70, 0.54, 0.78 ] )
		for ( const fy of [ 0.44, 0.52, 0.36, 0.60 ] ) {
			const x = Math.round( W * fx ), y = Math.round( H * fy );
			await p.mouse.move( x, y ); await sleep( 300 );
			const f = await p.evaluate( () => window.__floor() );
			if ( f.hot ) { pt = [ x, y, f.hot ]; break outer; }
		}
	if ( ! pt ) { console.log( 'no storey answered' ); await b.close(); process.exit( 1 ); }
	await p.mouse.move( pt[ 0 ], pt[ 1 ] );
	await sleep( 2500 );
	console.log( 'storey ' + pt[ 2 ] + ' at ' + pt[ 0 ] + ',' + pt[ 1 ] );
	for ( const s of sets ) {
		const { name, ...dials } = s;
		await p.evaluate( ( d ) => window.__glass.set( d ), dials );
		await p.mouse.move( pt[ 0 ], pt[ 1 ] + 1 );
		await p.mouse.move( pt[ 0 ], pt[ 1 ] );
		await p.evaluate( () => window.__invalidate( 40 ) );
		await sleep( 1600 );
		const f = path.join( dir, name + '.png' );
		await p.screenshot( { path: f, clip: {
			x: Math.max( 0, pt[ 0 ] + crop[ 0 ] ), y: Math.max( 0, pt[ 1 ] + crop[ 1 ] ),
			width: crop[ 2 ], height: crop[ 3 ] } } );
		console.log( '  ' + name, JSON.stringify( dials ) );
	}
	if ( errs.length ) console.log( 'LOG:\n  ' + errs.slice( 0, 8 ).join( '\n  ' ) );
	await b.close();
} )().catch( e => { console.error( e.message ); process.exit( 1 ); } );
