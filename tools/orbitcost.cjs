#!/usr/bin/env node
/* What a MOVING frame costs: the camera is swung round the building and the
 * frame intervals are taken while it moves - the case the page now drops
 * resolution for. Alternates the two pages so machine drift hits both.
 *   node tools/orbitcost.cjs [rounds]
 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
/* The render page is lab.html; / is the sales site. An argument that
 * starts with ? is a query on the lab, anything else is a page of its own. */
const page_ = ( a ) => ( ! a || a.startsWith( '?' ) ) ? 'lab.html' + a : a;
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const med = ( a ) => { const s = [ ...a ].sort( ( x, y ) => x - y ); return s[ s.length >> 1 ]; };
const ROUNDS = + ( process.argv[ 2 ] || 2 );
const PAGES = process.argv.slice( 3 ).length ? process.argv.slice( 3 ) : [ '', '?moveres=1' ];

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1600,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-orbit' ) ] } );
	const acc = {};
	for ( let r = 0; r < ROUNDS; r ++ ) for ( const pg of PAGES ) {
		const p = await b.newPage();
		await p.setViewport( { width: 1600, height: 900, deviceScaleFactor: 2 } );
		await p.goto( 'http://127.0.0.1:8777/' + page_( pg ), { waitUntil: 'domcontentloaded' } );
		await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
			{ timeout: 180000, polling: 100 } );
		await sleep( 12000 );                      // let any background warm finish
		const out = await p.evaluate( async () => {
			const cam = window.__camera;
			const tx = 10, ty = 17, tz = - 95;      // the hero target
			const dx = cam.position.x - tx, dz = cam.position.z - tz;
			const rad = Math.hypot( dx, dz ); let ang = Math.atan2( dz, dx );
			const ts = []; let last = performance.now();
			for ( let i = 0; i < 140; i ++ ) {
				ang += 0.004;
				cam.position.set( tx + rad * Math.cos( ang ), cam.position.y, tz + rad * Math.sin( ang ) );
				cam.lookAt( tx, ty, tz );
				cam.updateMatrixWorld();
				await new Promise( r => requestAnimationFrame( r ) );
				const t = performance.now();
				if ( i > 19 ) ts.push( t - last );
				last = t;
			}
			return ts;
		} );
		const k = pg || 'new';
		( acc[ k ] = acc[ k ] || [] ).push( med( out ) );
		console.log( k.padEnd( 16 ), 'moving frame', med( out ).toFixed( 1 ), 'ms' );
		await p.close();
	}
	console.log( '---' );
	for ( const [ k, v ] of Object.entries( acc ) )
		console.log( k.padEnd( 16 ), 'median of runs', med( v ).toFixed( 1 ) + ' ms' );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
