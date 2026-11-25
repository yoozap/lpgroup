#!/usr/bin/env node
/* What the real building's FLOOR VIEW costs per frame against the idle
 * street, and what its flat hover costs - in one page boot, interleaved, so
 * the machine's drift between rounds cannot fake a difference.
 *
 *   node tools/planhover.cjs [w] [h] [dsf] [rounds] [frames] [level]
 *
 * Re-pointed 2026-11-24 from the old show flat (`__storey` / `__plan2d`) to
 * the real levels (`LP.openLevel`, `__lvPin`). ADAPT is off (`?moveres=1`)
 * and the density pinned, so rows differ only in what is drawn. Draw calls
 * and triangles are summed over every pass of one frame (`info.autoReset`
 * off for it): the pipeline's last render is the output quad, and reading
 * after the frame otherwise reports that one quad.                       */
const puppeteer = require( '/Users/wazzap/.npm/_npx/0f94ee7615faf582/node_modules/puppeteer-core' );
const path = require( 'path' ), os = require( 'os' );
const sleep = ( ms ) => new Promise( r => setTimeout( r, ms ) );
const W = + ( process.argv[ 2 ] || 1600 ), H = + ( process.argv[ 3 ] || 900 );
const DSF = + ( process.argv[ 4 ] || 1 ), ROUNDS = + ( process.argv[ 5 ] || 5 );
const N = + ( process.argv[ 6 ] || 30 ), LEVEL = process.argv[ 7 ] || 'L06';
const med = ( a ) => { const s = a.slice().sort( ( x, y ) => x - y ); return s.length ? s[ s.length >> 1 ] : 0; };

( async () => {
	const b = await puppeteer.launch( { headless: 'new',
		executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
		args: [ '--enable-unsafe-webgpu', '--use-angle=metal', '--no-first-run',
			'--window-size=' + W + ',' + H,
			'--user-data-dir=' + path.join( os.tmpdir(), 'lp-planhover' ) ] } );
	const p = await b.newPage();
	await p.setViewport( { width: W, height: H, deviceScaleFactor: DSF } );
	await p.goto( 'http://127.0.0.1:8777/index.html?rail=0&moveres=1&lang=en',
		{ waitUntil: 'domcontentloaded' } );
	await p.waitForFunction( "document.getElementById('boot').classList.contains('gone')",
		{ timeout: 180000, polling: 120 } );
	await sleep( 6000 );

	/* One frame forced N times, timed rAF to rAF, plus the draws and
	 * triangles of one whole frame. `shadow` redraws the sun's map first. */
	const measure = ( shadow ) => p.evaluate( async ( shadow, n ) => {
		const R = window.__renderer;
		let S = null;
		window.__scene.traverse( ( o ) => { if ( o.isLight && o.shadow && o.shadow.mapSize && o.shadow.mapSize.x >= 2048 ) S = o; } );
		const ts = [];
		for ( let i = 0; i < n + 8; i ++ ) {
			if ( shadow && S ) S.shadow.needsUpdate = true;
			const t0 = performance.now();
			window.__invalidate( 2 );
			await new Promise( r => requestAnimationFrame( r ) );
			if ( i >= 8 ) ts.push( performance.now() - t0 );
		}
		R.info.autoReset = false; R.info.reset();
		if ( shadow && S ) S.shadow.needsUpdate = true;
		window.__invalidate( 1 );
		await new Promise( r => requestAnimationFrame( r ) );
		const draws = R.info.render.drawCalls, tris = R.info.render.triangles;
		R.info.autoReset = true;
		ts.sort( ( a, b ) => a - b );
		return { med: + ts[ ts.length >> 1 ].toFixed( 2 ), draws, tris, pr: + R.getPixelRatio().toFixed( 2 ) };
	}, shadow, N );

	const toStreet = async () => { await p.evaluate( () => window.LP.setScene( 1 ) ); await sleep( 2500 ); };
	const toLevel = async () => {
		await p.evaluate( ( id ) => window.LP.openLevel( id ), LEVEL );
		for ( let i = 0; i < 100; i ++ ) { if ( await p.evaluate( () => window.__lv().amt === 1 && window.__lv().tweens === 0 ) ) break; await sleep( 200 ); }
		await sleep( 800 );
	};
	const rows = { 'street, idle': [], [ 'floor view ' + LEVEL ]: [], [ 'floor view, one flat lit' ]: [],
		[ 'floor view, shadow redrawn' ]: [] };
	const shape = {};
	for ( let r = 0; r < ROUNDS; r ++ ) {
		await toStreet();
		const a = await measure( false ); rows[ 'street, idle' ].push( a.med ); shape[ 'street, idle' ] = a;
		await toLevel();
		const c = await measure( false ); rows[ 'floor view ' + LEVEL ].push( c.med ); shape[ 'floor view ' + LEVEL ] = c;
		await p.evaluate( () => window.__lvPin( 3, 1 ) ); await sleep( 300 );
		const d = await measure( false ); rows[ 'floor view, one flat lit' ].push( d.med ); shape[ 'floor view, one flat lit' ] = d;
		await p.evaluate( () => window.__lvPin( 0 ) );
		const e = await measure( true ); rows[ 'floor view, shadow redrawn' ].push( e.med ); shape[ 'floor view, shadow redrawn' ] = e;
		process.stderr.write( `round ${ r + 1 }/${ ROUNDS }  ${ a.med } / ${ c.med } / ${ d.med } / ${ e.med } ms\n` );
	}
	/* ...and the hover itself, live: frames while one flat's dial moves. */
	const live = await p.evaluate( async () => {
		const ts = [];
		let last = performance.now();
		const t0 = last;
		window.__lvPin( 0 );
		await new Promise( ( done ) => {
			const step = ( t ) => { ts.push( t - last ); last = t; if ( t - t0 < 1200 ) requestAnimationFrame( step ); else done(); };
			// a flat lit the way the pointer lights it, then let go to ease
			window.__lvPin( 5, 0.01 ); window.__lvPin( 0 );
			requestAnimationFrame( step );
		} );
		return ts.length;
	} );
	console.log( `\n${ W }x${ H } @${ DSF }   ${ ROUNDS } rounds of ${ N } forced frames, level ${ LEVEL }\n` );
	const base = med( rows[ 'street, idle' ] );
	for ( const [ k, v ] of Object.entries( rows ) ) {
		const m = med( v ), s = shape[ k ];
		console.log( `  ${ k.padEnd( 28 ) } ${ m.toFixed( 2 ).padStart( 7 ) } ms   ${ m === base ? '        ' : ( ( m - base >= 0 ? '+' : '' ) + ( m - base ).toFixed( 2 ) + ' ms' ).padStart( 9 ) }` +
			`   ${ String( s.draws ).padStart( 4 ) } draws  ${ ( s.tris / 1e6 ).toFixed( 2 ) } M tris  pr ${ s.pr }` );
		console.log( `  ${ ' '.repeat( 28 ) } ${ v.map( x => x.toFixed( 1 ) ).join( '  ' ) }` );
	}
	console.log( `  live frames drawn in 1.2 s of a hover easing out: ${ live }` );
	await b.close();
} )();
