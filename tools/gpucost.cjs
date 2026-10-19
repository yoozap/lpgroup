#!/usr/bin/env node
/* What a drawn frame actually costs, in GPU milliseconds rather than in rAF
 * intervals - the wall clock on this machine swings 30% between runs, the GPU
 * timestamps do not. Also reports the draw calls and triangles per frame.
 *   node tools/gpucost.cjs [pageA] [pageB] [rounds]
 */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
/* The render page is lab.html; / is the sales site. An argument that
 * starts with ? is a query on the lab, anything else is a page of its own. */
const page_ = ( a ) => ( ! a || a.startsWith( '?' ) ) ? 'lab.html' + a : a;
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const med = ( a ) => { const s = [ ...a ].sort( ( x, y ) => x - y ); return s[ s.length >> 1 ]; };
const PAGES = [ process.argv[ 2 ] || '', process.argv[ 3 ] || '_baseline.html' ];
const ROUNDS = + ( process.argv[ 4 ] || 2 );
const SCENE2 = process.env.SCENE2 === '1';

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=1600,900', '--user-data-dir=' + path.join( os.tmpdir(), 'lp-gpu' ) ] } );
	const acc = {};
	for ( let r = 0; r < ROUNDS; r ++ ) for ( const pg of PAGES ) {
		const p = await b.newPage();
		await p.setViewport( { width: 1600, height: 900, deviceScaleFactor: 2 } );
		await p.goto( 'http://127.0.0.1:8777/' + page_( pg ), { waitUntil: 'domcontentloaded' } );
		await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
			{ timeout: 180000, polling: 100 } );
		await sleep( + ( process.env.SETTLE || 12000 ) );
		if ( SCENE2 ) { await p.evaluate( () => document.getElementById( 's_2' ).click() ); await sleep( 9000 ); }
		if ( process.env.TWEAK ) { await p.evaluate( process.env.TWEAK ); await sleep( 1500 ); }
		const out = await p.evaluate( async () => {
			const R = window.__renderer;
			const gpu = [], draws = [], tris = [];
			let last = performance.now();
			for ( let i = 0; i < 130; i ++ ) {
				if ( window.__invalidate ) window.__invalidate( 2 );
				await new Promise( r => requestAnimationFrame( r ) );
				const t = performance.now();
				if ( i > 9 ) { gpu.push( t - last );
					draws.push( R.info.render.drawCalls ); tris.push( R.info.render.triangles ); }
				last = t;
			}
			return { gpu, draws, tris };
		} );
		const k = pg || 'new';
		( acc[ k ] = acc[ k ] || [] ).push( [ med( out.gpu ), med( out.draws ), med( out.tris ) ] );
		console.log( k.padEnd( 16 ), 'frame', med( out.gpu ).toFixed( 2 ), 'ms  draws', med( out.draws ),
			'tris', med( out.tris ) );
		await p.close();
	}
	console.log( '---' );
	for ( const [ k, v ] of Object.entries( acc ) )
		console.log( k.padEnd( 16 ), 'median of runs', med( v.map( x => x[ 0 ] ) ).toFixed( 2 ) + ' ms' );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
