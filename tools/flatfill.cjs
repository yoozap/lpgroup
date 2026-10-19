#!/usr/bin/env node
/* Where the open flat's frame actually goes.
 *
 *   node tools/flatfill.cjs [w] [h] [dsf]
 *
 * Two questions, both answered by measuring rather than by reading passes:
 *
 *  1. FILL or GEOMETRY? The frame is drawn at a range of pixel ratios and
 *     the wall clock is fitted against the megapixels. The SLOPE is what a
 *     pixel costs; the INTERCEPT is everything that does not care how many
 *     there are. A big slope means the only levers are pixels and shader
 *     work; a big intercept means there is fixed work worth cutting.
 *
 *  2. What does the CITY cost in there? The street and the storeys over the
 *     open one are taken away and the same frame is measured again. The
 *     camera is under a ceiling, so nothing of either can be seen except
 *     through the glazing.
 *
 * Every row is measured at the same density, interleaved, in one boot.    */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 2 );
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-flatfill' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0', { waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 20000 );

	// hold the density still ourselves: the ladder would move under the rows
	await p.evaluate( () => {
		const R = window.__renderer;
		window.__pin = ( pr ) => {
			R.setPixelRatio( pr );
			R.setSize( innerWidth, innerHeight, false );
			R.domElement.style.width = innerWidth + 'px';
			R.domElement.style.height = innerHeight + 'px';
		};
		window.__mpx = () => innerWidth * innerHeight * window.__renderer.getPixelRatio() ** 2 / 1e6;
	} );

	const shot = ( n = 20 ) => p.evaluate( async ( n ) => {
		const R = window.__renderer, ts = [];
		for ( let i = 0; i < n + 8; i ++ ) {
			const t0 = performance.now();
			window.__invalidate( 2 );
			await new Promise( r => requestAnimationFrame( r ) );
			if ( i >= 8 ) ts.push( performance.now() - t0 );
		}
		ts.sort( ( a, b ) => a - b );
		return { ms: + ts[ ts.length >> 1 ].toFixed( 2 ), mpx: + window.__mpx().toFixed( 2 ),
			draws: R.info.render.drawCalls, tris: R.info.render.triangles };
	}, n );

	const go = async ( where ) => {
		if ( where === 'flat' ) { await p.evaluate( () => { window.__storey( 7, 'plan' ); } ); await sleep( 6000 );
			await p.evaluate( () => window.__focus( 2 ) ); await sleep( 5000 ); }
		if ( where === 'room' ) { await p.evaluate( () => window.__room( 0 ) ); await sleep( 5000 ); }
	};

	const PRS = [ 0.7, 1.0, 1.4, 1.8, 2.2 ];
	const report = async ( label ) => {
		const pts = [];
		for ( const pr of PRS ) {
			await p.evaluate( ( pr ) => window.__pin( pr ), pr );
			await sleep( 500 );
			pts.push( await shot() );
		}
		// least squares: ms = a * mpx + c
		const n = pts.length;
		const sx = pts.reduce( ( s, q ) => s + q.mpx, 0 ), sy = pts.reduce( ( s, q ) => s + q.ms, 0 );
		const sxx = pts.reduce( ( s, q ) => s + q.mpx * q.mpx, 0 );
		const sxy = pts.reduce( ( s, q ) => s + q.mpx * q.ms, 0 );
		const a = ( n * sxy - sx * sy ) / ( n * sxx - sx * sx );
		const c = ( sy - a * sx ) / n;
		console.log( `\n${ label }   ${ pts[ 0 ].draws } draws  ${ ( pts[ 0 ].tris / 1e6 ).toFixed( 2 ) } M tris` );
		console.log( '   Mpx     ms' );
		for ( const q of pts ) console.log( `  ${ q.mpx.toFixed( 2 ).padStart( 5 ) }  ${ q.ms.toFixed( 1 ).padStart( 6 ) }` );
		console.log( `  fill  ${ a.toFixed( 2 ) } ms per Mpx      fixed  ${ c.toFixed( 2 ) } ms per frame` );
		return { a, c, pts };
	};

	console.log( `\n${ W }x${ H } @${ DSF }` );
	await go( 'flat' );
	await report( 'ONE FLAT OPEN - as shipped' );
	await go( 'room' );
	const roomNow = await report( 'INSIDE A ROOM - as shipped' );

	const hide = ( ks ) => p.evaluate( ( ks ) => {
		const g = window.__groups();
		for ( const k of [ 'main', 'tower' ] ) if ( g[ k ] ) g[ k ].visible = ! ks.includes( k );
		window.__invalidate( 4 );
	}, ks );

	await hide( [ 'tower' ] ); await sleep( 1500 );
	const roomTower = await report( 'INSIDE A ROOM - tower hidden (safe: it is over your ceiling)' );
	await hide( [ 'main', 'tower' ] ); await sleep( 1500 );
	const roomCut = await report( 'INSIDE A ROOM - street AND tower hidden' );
	await hide( [] ); await sleep( 1500 );
	const roomBack = await report( 'INSIDE A ROOM - as shipped (repeat)' );
	console.log( `\ntower alone, at matched density:` );
	for ( let i = 0; i < PRS.length; i ++ ) {
		const on = ( roomNow.pts[ i ].ms + roomBack.pts[ i ].ms ) / 2;
		console.log( `  ${ on.toFixed( 1 ).padStart( 6 ) } -> ${ roomTower.pts[ i ].ms.toFixed( 1 ).padStart( 6 ) } ms` +
			`   ${ ( on - roomTower.pts[ i ].ms ).toFixed( 1 ).padStart( 6 ) } ms saved` );
	}

	console.log( `\nwhat the city costs inside a room, at matched density:` );
	for ( let i = 0; i < PRS.length; i ++ ) {
		const on = ( roomNow.pts[ i ].ms + roomBack.pts[ i ].ms ) / 2, off = roomCut.pts[ i ].ms;
		console.log( `  ${ roomNow.pts[ i ].mpx.toFixed( 2 ).padStart( 5 ) } Mpx   ` +
			`${ on.toFixed( 1 ).padStart( 6 ) } -> ${ off.toFixed( 1 ).padStart( 6 ) } ms   ` +
			`${ ( on - off ).toFixed( 1 ).padStart( 6 ) } ms saved` );
	}
	console.log( '' );
	await b.close();
} )().catch( e => { console.error( e ); process.exit( 1 ); } );
